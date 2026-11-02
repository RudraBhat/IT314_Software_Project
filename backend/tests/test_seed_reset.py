"""Tests for scripts/seed_reset.py safety guards, dynamic cleanup, and idempotency."""

import sys
from pathlib import Path

# Ensure scripts directory is importable
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from seed_reset import check_safety_guard, reset_seeds


def test_seed_reset_safety_guard_allowed_targets():
    """Verify safe targets are allowed without FORCE flag."""
    safe_urls = [
        "postgresql://postgres:password@localhost:5432/drch_db",
        "postgresql://postgres:password@127.0.0.1:5432/drch_db",
        "postgresql://postgres:password@postgres-postgis:5432/drch_db",
        "postgresql://postgres:password@drch_postgres:5432/drch_db",
        "postgresql://user:pass@remote-host.internal:5432/drch_test",
        "postgresql://user:pass@remote-host.internal:5432/my_dev_db",
    ]
    for url in safe_urls:
        is_safe, msg = check_safety_guard(url, force=False)
        assert is_safe is True, f"Expected {url} to be safe, got: {msg}"


def test_seed_reset_safety_guard_refuses_cloud_and_production():
    """Verify cloud and production targets are strictly refused by default."""
    unsafe_urls = [
        "postgresql://drch_owner:secret@ep-cool-fog-123456.us-east-2.aws.neon.tech/drch_prod",
        "postgresql://drch_user:secret@dpg-c12345-a.oregon-postgres.render.com/drch_production",
        "postgresql://admin:secret@rds.us-west-2.amazonaws.com:5432/drch",
    ]
    for url in unsafe_urls:
        is_safe, msg = check_safety_guard(url, force=False)
        assert is_safe is False, f"Expected {url} to be refused!"
        assert "Refusing execution" in msg


def test_seed_reset_safety_guard_force_override():
    """Verify FORCE=1 allows explicit override on cloud/production databases."""
    neon_url = "postgresql://drch_owner:secret@ep-cool-fog-123456.us-east-2.aws.neon.tech/drch_prod"
    is_safe, msg = check_safety_guard(neon_url, force=True)
    assert is_safe is True
    assert "FORCE=1 override active" in msg


def test_seed_reset_lifecycle_and_idempotency(sql):
    """Verify seed reset lifecycle:
    1. Seed users and seed operational rows exist after reset.
    2. Junk incident and non-audited junk user are wiped clean.
    3. Users with audit log history are preserved (no trigger violation).
    4. Running reset twice yields identical counts (idempotent).
    """
    # 1. Arrange: insert transient junk user, audited junk user, and junk incident
    junk_user_id = "f0000000-0000-0000-0000-000000000888"
    audited_user_id = "f0000000-0000-0000-0000-000000000777"
    junk_inc_id = "f0000000-0000-0000-0000-000000000999"

    # Insert transient junk user (no audit history)
    sql.execute(
        """
        INSERT INTO users (user_id, role_id, email, phone, full_name, status)
        SELECT %s::uuid, role_id, 'junk.user.transient@example.in', '+919999990001', 'Junk User', 'ACTIVE'
        FROM roles WHERE code = 'NORMAL_USER'
        ON CONFLICT (email) DO NOTHING
        """,
        (junk_user_id,),
    )
    sql.execute(
        """
        INSERT INTO user_auth (user_id, password_hash, mfa_enabled)
        VALUES (%s::uuid, 'fake_hash_transient', FALSE)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (junk_user_id,),
    )

    # Insert audited junk user (has row in audit_logs)
    sql.execute(
        """
        INSERT INTO users (user_id, role_id, email, phone, full_name, status)
        SELECT %s::uuid, role_id, 'junk.user.audited@example.in', '+919999990002', 'Audited User', 'ACTIVE'
        FROM roles WHERE code = 'NORMAL_USER'
        ON CONFLICT (email) DO NOTHING
        """,
        (audited_user_id,),
    )
    sql.execute(
        """
        INSERT INTO user_auth (user_id, password_hash, mfa_enabled)
        VALUES (%s::uuid, 'fake_hash_audited', FALSE)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (audited_user_id,),
    )
    sql.execute(
        """
        INSERT INTO audit_logs (actor_id, action, entity_type, result, rationale)
        VALUES (%s::uuid, 'TEST_AUDIT_RECORD', 'USER', 'SUCCESS', 'Verify audit immutability preservation')
        """,
        (audited_user_id,),
    )

    # Insert junk incident
    sql.execute(
        """
        INSERT INTO incidents (
            incident_id, incident_ref, reporter_id, scenario, description,
            reported_urgency, status, latitude, longitude, address_text, is_simulated
        )
        VALUES (
            %s::uuid,
            'INC-JUNK-9999',
            'a0000000-0000-0000-0000-000000000001'::uuid,
            'URBAN_FLOODING',
            'Temporary junk incident for testing seed reset wipe',
            'LOW', 'SUBMITTED', 23.0, 72.5, 'Junk Street', TRUE
        )
        """,
        (junk_inc_id,),
    )

    # Verify junk fixtures exist before reset
    assert sql.execute("SELECT 1 FROM incidents WHERE incident_ref = 'INC-JUNK-9999'").fetchone() is not None
    assert sql.execute("SELECT 1 FROM users WHERE user_id = %s::uuid", (junk_user_id,)).fetchone() is not None
    assert sql.execute("SELECT 1 FROM users WHERE user_id = %s::uuid", (audited_user_id,)).fetchone() is not None

    # 2. Run seed reset (first pass)
    counts1 = reset_seeds(force=False)

    # Seed operational rows must exist
    assert counts1["incidents"] == 4
    assert counts1["resources"] == 14
    assert counts1["donation_campaigns"] == 3

    # Seed users must exist
    assert sql.execute("SELECT 1 FROM users WHERE email = 'admin@drch.gov.in'").fetchone() is not None
    assert sql.execute("SELECT 1 FROM users WHERE email = 'ingest-system@drch.gov.in'").fetchone() is not None

    # Transient junk incident and unreferenced user are wiped
    assert sql.execute("SELECT 1 FROM incidents WHERE incident_ref = 'INC-JUNK-9999'").fetchone() is None
    assert sql.execute("SELECT 1 FROM users WHERE user_id = %s::uuid", (junk_user_id,)).fetchone() is None

    # Audited user is preserved because audit_logs is append-only
    assert sql.execute("SELECT 1 FROM users WHERE user_id = %s::uuid", (audited_user_id,)).fetchone() is not None

    # 3. Run seed reset a second time (second pass - idempotency check)
    counts2 = reset_seeds(force=False)
    assert counts2 == counts1, f"Seed reset is not idempotent: {counts2} != {counts1}"

    # Audited user and seed rows still intact on second pass
    assert sql.execute("SELECT 1 FROM users WHERE user_id = %s::uuid", (audited_user_id,)).fetchone() is not None
    assert sql.execute("SELECT 1 FROM users WHERE email = 'admin@drch.gov.in'").fetchone() is not None
