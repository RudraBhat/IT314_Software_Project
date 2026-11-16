"""CLI: python -m app.cli create-admin, and reset-mfa for administrators."""

import argparse
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pyotp
import pytest

from app import cli, db, security

PASSWORD = "Correct-Horse-Battery-9!"


def _args(email: str | None = None, name: str = "Test Admin", **extra) -> argparse.Namespace:
    return argparse.Namespace(email=email or f"cli-admin-{uuid.uuid4().hex[:10]}@example.in", name=name, phone=None, designation=None, **extra)


@pytest.fixture
def automated(monkeypatch):
    """The password comes from the environment, the way a deployment script would supply it."""
    monkeypatch.setenv("RESQ_STAFF_PASSWORD", PASSWORD)


def _no_database(monkeypatch):
    @contextmanager
    def boom():
        raise AssertionError("the database must not be touched for invalid input")
        yield MagicMock()

    monkeypatch.setattr(db, "transaction", boom)


# ----------------------------------------------------------------------------- validation (no database)

@pytest.mark.parametrize("email", ["not-an-email", "a@b", "two words@example.in", ""])
def test_invalid_email_is_refused_before_anything_is_written(monkeypatch, automated, email):
    _no_database(monkeypatch)
    with pytest.raises(SystemExit, match="valid email"):
        cli.create_admin(_args(email=email or " "))


def test_blank_name_is_refused(monkeypatch, automated):
    _no_database(monkeypatch)
    with pytest.raises(SystemExit, match="full name"):
        cli.create_admin(_args(name="   "))


def test_short_password_is_refused(monkeypatch):
    _no_database(monkeypatch)
    monkeypatch.setenv("RESQ_STAFF_PASSWORD", "short1!")
    with pytest.raises(SystemExit, match="at least"):
        cli.create_admin(_args())


def test_the_command_is_registered():
    parser_help = cli.main.__doc__ or ""
    assert callable(cli.create_admin) and parser_help is not None
    with pytest.raises(SystemExit) as exc:
        cli.main(["create-admin", "--help"])
    assert exc.value.code == 0


# ----------------------------------------------------------------------------- against the test database

@pytest.mark.db
def test_create_admin_makes_an_admin_who_can_sign_in_and_list_accounts(client, sql, automated, capsys):
    args = _args()
    cli.create_admin(args)
    out = capsys.readouterr().out
    assert "Secret key" in out and "Created administrator account" in out
    assert PASSWORD not in out, "the password must never be printed"

    row = sql.execute(
        """
        SELECT u.user_id, u.status, r.code AS role, a.mfa_enabled, a.mfa_secret, a.password_hash
        FROM users u JOIN roles r USING (role_id) JOIN user_auth a ON a.user_id = u.user_id WHERE u.email = %s
        """,
        (args.email,),
    ).fetchone()
    assert row["role"] == "APP_MGMT" and row["status"] == "ACTIVE" and row["mfa_enabled"] is True
    assert row["password_hash"].startswith("$argon2id$")
    assert sql.execute("SELECT COUNT(*) AS n FROM staff_permissions WHERE user_id = %s", (row["user_id"],)).fetchone()["n"] == 0
    audited = sql.execute(
        "SELECT result FROM audit_logs WHERE entity_id = %s AND action = 'STAFF_PROVISIONED'", (row["user_id"],)
    ).fetchone()
    assert audited["result"] == "SUCCESS"

    first = client.post("/api/v1/auth/login", json={"email": args.email, "password": PASSWORD})
    assert first.status_code == 200 and first.json()["mfa_required"] is True
    code = pyotp.TOTP(security.decrypt_mfa_secret(row["mfa_secret"])).now()
    verified = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": first.json()["mfa_token"], "code": code})
    assert verified.status_code == 200
    headers = {"Authorization": f"Bearer {verified.json()['access_token']}"}
    listing = client.get("/api/v1/admin/accounts", headers=headers, params={"q": args.email})
    assert listing.status_code == 200 and listing.json()["items"][0]["is_you"] is True
    assert client.get("/api/v1/dm/incidents", headers=headers).status_code == 403  # no operational access


@pytest.mark.db
def test_duplicate_email_is_refused_and_nothing_is_added(sql, automated):
    args = _args()
    cli.create_admin(args)
    with pytest.raises(SystemExit, match="already exists"):
        cli.create_admin(args)
    assert sql.execute("SELECT COUNT(*) AS n FROM users WHERE email = %s", (args.email,)).fetchone()["n"] == 1


@pytest.mark.db
def test_reset_mfa_works_for_an_administrator_and_ends_their_sessions(client, make, sql, automated):
    admin = make.user("APP_MGMT")
    old_headers = make.token(admin)
    assert client.get("/api/v1/admin/accounts", headers=old_headers).status_code == 200
    before = sql.execute("SELECT mfa_secret FROM user_auth WHERE user_id = %s", (admin["user_id"],)).fetchone()["mfa_secret"]

    cli.reset_mfa(argparse.Namespace(email=admin["email"]))

    after = sql.execute("SELECT mfa_secret FROM user_auth WHERE user_id = %s", (admin["user_id"],)).fetchone()["mfa_secret"]
    assert bytes(before) != bytes(after)
    assert client.get("/api/v1/admin/accounts", headers=old_headers).status_code == 401  # old session revoked


@pytest.mark.db
def test_reset_mfa_and_set_permissions_still_refuse_other_roles(make, automated):
    citizen, field = make.citizen(), make.field_team_user()
    for person in (citizen, field):
        with pytest.raises(SystemExit, match="only manages"):
            cli.reset_mfa(argparse.Namespace(email=person["email"]))
    admin = make.user("APP_MGMT")
    with pytest.raises(SystemExit, match="only manages Disaster Management staff"):
        cli.set_permissions(argparse.Namespace(email=admin["email"], permissions="DISPATCH"))


def test_a_bad_mfa_encryption_key_gives_a_clear_message_and_writes_nothing(monkeypatch):
    class Connection:
        called = False

        def execute(self, *_args, **_kwargs):
            self.called = True

    def invalid_key(_secret):
        raise ValueError("Fernet key must be 32 url-safe base64-encoded bytes.")

    monkeypatch.setenv("RESQ_STAFF_PASSWORD", PASSWORD)
    monkeypatch.setattr(cli.security, "encrypt_mfa_secret", invalid_key)
    conn = Connection()
    with pytest.raises(SystemExit, match="MFA_ENCRYPTION_KEY is not a valid key"):
        cli._enrol_mfa(conn, "user-id", "ops@example.org")
    assert not conn.called
