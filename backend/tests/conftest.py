"""Test setup for the Disaster Management API.

Integration tests run against an isolated database whose name must end in
"_test" (default: drch_test on the DATABASE_URL server). The suite never
touches the application database and never deletes rows: each test creates
its own uniquely named data. When no database is reachable, DB-backed tests
are skipped and only the unit tests run (e.g. in CI without Postgres).
"""

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from psycopg import sql as pgsql

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "backend" / "db"


def _test_database_url() -> str | None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        base = os.getenv("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
        if not base:
            return None
        parts = urlsplit(base)
        url = urlunsplit(parts._replace(path="/drch_test"))
    if not urlsplit(url).path.rstrip("/").endswith("_test"):
        raise RuntimeError("Refusing to run tests: the test database name must end with '_test'")
    return url


TEST_DB_URL = _test_database_url()

# Test-only secrets, set before the app reads its settings.
os.environ["DATABASE_URL"] = TEST_DB_URL or ""
os.environ["JWT_SECRET"] = "test-only-secret-" + "x" * 32
os.environ["MFA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DISPATCH_ACK_TIMEOUT_MINUTES"] = "15"
os.environ.pop("AI_TRIAGE_URL", None)


def _db_available() -> bool:
    if not TEST_DB_URL:
        return False
    try:
        with psycopg.connect(TEST_DB_URL, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


DB_AVAILABLE = _db_available()


def _ensure_schema() -> None:
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        has_core = conn.execute("SELECT to_regclass('public.incidents')").fetchone()[0]
        if not has_core:
            for m in sorted((SQL_DIR / "migrations").glob("*.sql")):
                conn.execute(m.read_text(encoding="utf-8"))
        else:
            for m in sorted((SQL_DIR / "migrations").glob("*.sql")):
                if m.name != "01_schema.sql":
                    conn.execute(m.read_text(encoding="utf-8"))
        # Apply all seeds in ascending version order
        for s in sorted((SQL_DIR / "seeds").glob("*.sql")):
            conn.execute(s.read_text(encoding="utf-8"))


DB_FIXTURE_NAMES = {"sql", "make", "citizen_user", "staff_user", "field_user"}


def pytest_collection_modifyitems(config, items):
    db_marker = pytest.mark.db
    for item in items:
        # Auto-apply the 'db' marker to any test requesting DB-backed fixtures
        if (
            hasattr(item, "fixturenames")
            and any(f in DB_FIXTURE_NAMES for f in item.fixturenames)
            and "db" not in item.keywords
        ):
            item.add_marker(db_marker)

    if DB_AVAILABLE:
        _ensure_schema()
        return

    skip = pytest.mark.skip(reason="test database not reachable (set TEST_DATABASE_URL)")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs the PostgreSQL test database")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    passed_reps = terminalreporter.stats.get("passed", [])
    failed_reps = terminalreporter.stats.get("failed", [])
    skipped_reps = terminalreporter.stats.get("skipped", [])

    passed = len(passed_reps)
    failed = len(failed_reps)
    skipped = len(skipped_reps)
    total_ran = passed + failed

    db_passed = sum(1 for rep in passed_reps if "db" in getattr(rep, "keywords", {}))
    non_db_passed = passed - db_passed

    db_failed = sum(1 for rep in failed_reps if "db" in getattr(rep, "keywords", {}))
    non_db_failed = failed - db_failed

    db_skipped = sum(1 for rep in skipped_reps if "db" in getattr(rep, "keywords", {}))
    non_db_skipped = skipped - db_skipped

    req_db_on = os.getenv("REQUIRE_DB_TESTS") == "1"

    terminalreporter.write_sep("=", "DRCH SUITE EXECUTION SUMMARY", bold=True)
    terminalreporter.write_line(f"Executed Tests: {total_ran} (Passed: {passed}, Failed: {failed})")
    terminalreporter.write_line(f"Skipped Tests:  {skipped}")
    terminalreporter.write_line(f"  DB-backed Tests: Passed: {db_passed}, Failed: {db_failed}, Skipped: {db_skipped}")
    terminalreporter.write_line(f"  Non-DB Tests:    Passed: {non_db_passed}, Failed: {non_db_failed}, Skipped: {non_db_skipped}")
    terminalreporter.write_line(f"REQUIRE_DB_TESTS: {'ON (active)' if req_db_on else 'OFF (inactive)'}")


def evaluate_ci_guard(require_db: bool, db_tests_ran: bool) -> bool:
    """Evaluate whether the test run satisfies the REQUIRE_DB_TESTS guard.

    Returns:
        True: Run is OK (guard inactive or at least one DB test executed).
        False: Guard is active and zero DB tests were executed.
    """
    return not (require_db and not db_tests_ran)


def pytest_sessionfinish(session, exitstatus):
    require_db = os.getenv("REQUIRE_DB_TESTS") == "1"
    if require_db:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            db_tests_ran = any(
                "db" in rep.keywords
                for rep in reporter.stats.get("passed", []) + reporter.stats.get("failed", [])
            )
            if not evaluate_ci_guard(require_db=require_db, db_tests_ran=db_tests_ran):
                print("\nFATAL [CI Guard]: REQUIRE_DB_TESTS=1 is active, but 0 DB-backed tests were executed!")
                session.exitstatus = 1


# ----------------------------------------------------------------------- fixtures


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from main import app

    # No context manager: the background escalation loop is exercised directly in tests.
    return TestClient(app)


@pytest.fixture
def sql():
    """Direct database access for arranging and asserting state."""
    from psycopg.rows import dict_row

    with psycopg.connect(TEST_DB_URL, autocommit=True, row_factory=dict_row) as conn:
        yield conn


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Factory:
    def __init__(self, conn):
        self.conn = conn

    def user(self, role: str = "DISASTER_MGMT", permissions=(), password="correct-horse-battery", mfa=True):
        from app import security

        email = f"{unique('user')}@test.drch"
        user_id = self.conn.execute(
            """
            INSERT INTO users (role_id, email, full_name, phone, status)
            SELECT role_id, %s, %s, '+910000000000', 'ACTIVE' FROM roles WHERE code = %s
            RETURNING user_id
            """,
            (email, f"Test {role.title()}", role),
        ).fetchone()["user_id"]
        secret = security.new_totp_secret()
        self.conn.execute(
            "INSERT INTO user_auth (user_id, password_hash, mfa_enabled, mfa_secret) VALUES (%s, %s, %s, %s)",
            (user_id, security.hash_password(password), mfa, security.encrypt_mfa_secret(secret) if mfa else None),
        )
        for perm in permissions:
            self.conn.execute(
                "INSERT INTO staff_permissions (user_id, permission) VALUES (%s, %s)", (user_id, perm)
            )
        return {"user_id": user_id, "email": email, "password": password, "totp_secret": secret}

    def token(self, user: dict, mfa: bool = True) -> dict:
        from app import security

        tv = self.conn.execute(
            "SELECT token_version FROM user_auth WHERE user_id = %s", (user["user_id"],)
        ).fetchone()["token_version"]
        token = security.issue_token(user["user_id"], tv, security.ACCESS, 30, mfa=mfa)
        return {"Authorization": f"Bearer {token}"}

    def staff(self, *permissions: str) -> dict:
        user = self.user("DISASTER_MGMT", permissions)
        return {**user, "headers": self.token(user)}

    def incident(self, reporter_id=None, **fields):
        reporter_id = reporter_id or self.user("NORMAL_USER", mfa=False)["user_id"]
        values = {
            "incident_ref": unique("TST")[:30],
            "reporter_id": reporter_id,
            "scenario": "URBAN_FLOODING",
            "description": "Water rising at the junction; people stranded on rooftops.",
            "reported_urgency": "HIGH",
            "people_affected": 12,
            "address_text": unique("Junction"),
            "latitude": 23.0225,
            "longitude": 72.5714,
        }
        values.update(fields)
        query = pgsql.SQL("INSERT INTO incidents ({}) VALUES ({}) RETURNING *").format(
            pgsql.SQL(", ").join(pgsql.Identifier(k) for k in values),
            pgsql.SQL(", ").join(pgsql.Placeholder() for _ in values),
        )
        return self.conn.execute(query, list(values.values())).fetchone()

    def agency(self, active=True):
        return self.conn.execute(
            "INSERT INTO agencies (name, agency_type, contact_phone, is_active) VALUES (%s, 'FIRE', '101', %s) "
            "RETURNING *",
            (unique("Agency"), active),
        ).fetchone()

    def resource(self, quantity=1, type_="TEAM", agency_id=None):
        return self.conn.execute(
            """
            INSERT INTO resources (agency_id, type, name, quantity_total, quantity_available,
                                   current_geom)
            VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(72.57, 23.02), 4326)::geography)
            RETURNING *
            """,
            (agency_id, type_, unique("Resource"), quantity, quantity),
        ).fetchone()


    def citizen(self, password: str = "citizen-test-pass") -> dict:
        user = self.user("NORMAL_USER", password=password, mfa=False)
        return {**user, "headers": self.token(user, mfa=False)}

    def field_team_user(self, resource_id=None, callsign: str = "Bravo-1", is_leader: bool = True, password: str = "field-team-pass") -> dict:
        user = self.user("FIELD_TEAM", password=password, mfa=False)
        if not resource_id:
            res = self.resource(type_="TEAM")
            resource_id = res["resource_id"]
        self.conn.execute(
            """
            INSERT INTO field_team_members (user_id, resource_id, callsign, is_leader)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, resource_id) DO NOTHING
            """,
            (user["user_id"], resource_id, callsign, is_leader),
        )
        return {**user, "headers": self.token(user, mfa=False), "resource_id": resource_id}


@pytest.fixture
def make(sql):
    return Factory(sql)


@pytest.fixture
def citizen_user(make):
    return make.citizen()


@pytest.fixture
def staff_user(make):
    return make.staff("DISPATCH", "SUPERVISOR")


@pytest.fixture
def field_user(sql, make):
    has_role = sql.execute("SELECT 1 FROM roles WHERE code = 'FIELD_TEAM'").fetchone()
    row = sql.execute("SELECT to_regclass('public.field_team_members') AS tbl").fetchone()
    has_table = row and row["tbl"]
    if not has_role or not has_table:
        pytest.skip("field_team_members table or FIELD_TEAM role does not exist yet")
    return make.field_team_user()

