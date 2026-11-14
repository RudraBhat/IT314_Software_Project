"""Unit tests for Shlok's operations scripts: scripts/db_backup.py (S3-12) and scripts/load_test.py (S3-13).

No database or network: only the safety guards and the statistics are exercised.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from db_backup import database_name, default_backup_path, restore_allowed, split_password
from load_test import percentile, summarise


def test_password_is_removed_from_the_url_and_returned_separately():
    url, password = split_password("postgresql://owner:p%40ss@ep-x.neon.tech:5432/neondb?sslmode=require")
    assert password == "p@ss"
    assert "p%40ss" not in url and "p@ss" not in url
    assert url == "postgresql://owner@ep-x.neon.tech:5432/neondb?sslmode=require"


def test_url_without_password_is_unchanged():
    url = "postgresql://localhost/drch_db"
    assert split_password(url) == (url, None)


@pytest.mark.parametrize("name", ["drch_restore", "drch_test", "neondb_restore"])
def test_restore_into_restore_or_test_databases_is_allowed(name):
    allowed, _ = restore_allowed(f"postgresql://u:p@h/{name}", force=False)
    assert allowed


@pytest.mark.parametrize("name", ["neondb", "drch_db", "drch_restore_old"])
def test_restore_into_a_live_database_is_refused_without_force(name):
    allowed, reason = restore_allowed(f"postgresql://u:p@h/{name}", force=False)
    assert not allowed and "--force" in reason


def test_force_allows_a_declared_rollback():
    allowed, reason = restore_allowed("postgresql://u:p@h/neondb", force=True)
    assert allowed and "overwritten" in reason


def test_restore_needs_a_database_name():
    allowed, _ = restore_allowed("postgresql://u:p@h/", force=True)
    assert not allowed


def test_default_backup_path_is_in_the_ignored_backups_folder():
    path = default_backup_path("postgresql://u:p@h/neondb", now=datetime(2026, 11, 14, 10, 30, tzinfo=UTC))
    assert path.parent.name == "backups" and path.name == "neondb-20261114T103000Z.dump"
    assert database_name("postgresql://u@h:5432/drch_db?sslmode=require") == "drch_db"


def test_backups_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "backups/" in ignored and "*.dump" in ignored


def test_nearest_rank_percentile():
    samples = [float(n) for n in range(1, 101)]  # 1..100 ms
    assert percentile(samples, 50) == 50.0
    assert percentile(samples, 95) == 95.0
    assert percentile(samples, 99) == 99.0
    assert percentile([], 95) == 0.0
    assert percentile([7.0], 95) == 7.0


def test_summary_counts_errors_and_throughput():
    result = summarise("GET /x", [10.0, 20.0, 30.0], errors=1, elapsed_s=2.0)
    assert result["requests"] == 4 and result["errors"] == 1 and result["error_rate"] == 0.25
    assert result["throughput_rps"] == 2.0 and result["p95_ms"] == 30.0 and result["max_ms"] == 30.0
