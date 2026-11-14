"""Unit tests for scripts/generate_er_diagram.py (S3-16, owner Zalak). No database needed."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from generate_er_diagram import MIGRATIONS, parse, render

SAMPLE = """
-- a comment with CREATE TABLE ignored (x int);
CREATE TABLE users (
    user_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email     CITEXT NOT NULL UNIQUE,
    score     NUMERIC(5,2) CHECK (score > 0)
);
CREATE TABLE IF NOT EXISTS orders (
    order_id  UUID,
    user_id   UUID REFERENCES users(user_id) ON DELETE CASCADE,
    note      VARCHAR(200),
    PRIMARY KEY (order_id)
);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at TIMESTAMPTZ;
"""


def test_tables_columns_and_keys_are_parsed():
    tables = parse([SAMPLE])
    assert set(tables) == {"users", "orders"}
    users, orders = tables["users"], tables["orders"]
    assert users.columns["user_id"].keys == {"PK"} and users.columns["email"].keys == {"UK"}
    assert users.columns["score"].type == "numeric"
    assert orders.columns["order_id"].keys == {"PK"}
    assert orders.columns["user_id"].keys == {"FK"}
    assert "shipped_at" in orders.columns and orders.columns["shipped_at"].type == "timestamptz"
    assert orders.references == [("user_id", "users")]


def test_render_produces_mermaid_entities_and_relationships():
    text = render(parse([SAMPLE]))
    assert text.startswith("erDiagram")
    assert "uuid user_id PK" in text and "citext email UK" in text
    assert 'users ||--o{ orders : "user_id"' in text


def test_the_real_migrations_parse_into_the_core_tables():
    files = sorted(MIGRATIONS.glob("*.sql"), key=lambda p: p.name)
    tables = parse([f.read_text(encoding="utf-8") for f in files])
    for name in ("users", "incidents", "dispatch_orders", "donations", "audit_logs", "source_signals"):
        assert name in tables, name
    assert ("reporter_id", "users") in tables["incidents"].references
