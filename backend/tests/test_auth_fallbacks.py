"""Regression tests for security-sensitive database and demo fallbacks."""

import uuid
from contextlib import contextmanager

import pytest
from starlette.requests import Request


def test_database_error_does_not_grant_a_demo_principal(monkeypatch):
    from app import auth
    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://unavailable")
    monkeypatch.setenv("JWT_SECRET", "test-secret-" + "x" * 32)
    get_settings.cache_clear()

    @contextmanager
    def unavailable_database():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(auth.db, "read_only", unavailable_database)
    try:
        with pytest.raises(RuntimeError, match="database unavailable"):
            auth.load_principal(uuid.uuid4(), 1, mfa=True)
    finally:
        get_settings.cache_clear()


def test_mfa_database_error_does_not_issue_an_access_token(monkeypatch):
    from app import db, security
    from app.config import get_settings
    from app.routers.auth import MfaVerifyRequest, verify_mfa

    monkeypatch.setenv("DATABASE_URL", "postgresql://unavailable")
    monkeypatch.setenv("JWT_SECRET", "test-secret-" + "x" * 32)
    get_settings.cache_clear()

    @contextmanager
    def unavailable_database():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(db, "transaction", unavailable_database)
    challenge = security.issue_token(
        uuid.UUID("a0000000-0000-0000-0000-000000000001"),
        1,
        security.MFA,
        5,
    )
    request = Request({"type": "http", "client": ("127.0.0.1", 1234)})
    try:
        with pytest.raises(RuntimeError, match="database unavailable"):
            verify_mfa(MfaVerifyRequest(mfa_token=challenge, code="123456"), request)
    finally:
        get_settings.cache_clear()


def test_staff_creation_database_error_is_not_reported_as_success(monkeypatch):
    from app import db
    from app.config import get_settings
    from app.routers.dm.staff import CreateStaffRequest, create_staff

    monkeypatch.setenv("DATABASE_URL", "postgresql://unavailable")
    monkeypatch.setenv("JWT_SECRET", "test-secret-" + "x" * 32)
    get_settings.cache_clear()

    @contextmanager
    def unavailable_database():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(db, "transaction", unavailable_database)
    body = CreateStaffRequest(
        email="new.staff@example.com",
        full_name="New Staff",
        password="long-password-123",
    )
    try:
        with pytest.raises(RuntimeError, match="database unavailable"):
            create_staff(body, principal=None)
    finally:
        get_settings.cache_clear()


def test_no_default_jwt_secret_exists(monkeypatch):
    from app.config import get_settings

    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_settings.cache_clear()
    assert get_settings().jwt_secret is None
    get_settings.cache_clear()


def test_principal_is_read_fresh_on_every_request(monkeypatch):
    """No cache sits in front of authorisation: each call runs the query again and re-checks
    status, token_version and lock state against the row it just read."""
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    from app import auth

    uid = _uuid.uuid4()
    state = {"status": "ACTIVE", "token_version": 1, "locked_until": None, "role": "DISASTER_MGMT"}
    calls = {"n": 0}

    class _Conn:
        def execute(self, *_a, **_k):
            calls["n"] += 1
            row = {
                "user_id": uid, "email": "a@b.c", "full_name": "A", "mfa_enabled": True,
                "permissions": ["DISPATCH"], **state,
            }
            return type("R", (), {"fetchone": lambda self: row})()

    @contextmanager
    def fake_read_only():
        yield _Conn()

    monkeypatch.setattr(auth.db, "read_only", fake_read_only)
    first = auth.load_principal(uid, 1, mfa=True)
    assert first is not None and first.permissions == frozenset({"DISPATCH"}) and first.mfa_verified
    state["token_version"] = 2  # password reset, logout or MFA reset
    assert auth.load_principal(uid, 1, mfa=True) is None
    state["token_version"], state["status"] = 1, "DISABLED"
    assert auth.load_principal(uid, 1, mfa=True) is None
    state["status"], state["locked_until"] = "ACTIVE", datetime.now(UTC) + timedelta(minutes=5)
    assert auth.load_principal(uid, 1, mfa=True) is None
    assert calls["n"] == 4  # never served from a cache


def test_idle_check_pings_only_connections_that_sat_idle(monkeypatch):
    import time

    from app import db

    pinged = []
    monkeypatch.setattr(db.ConnectionPool, "check_connection", staticmethod(lambda conn: pinged.append(conn)))

    class _Conn:
        pass

    fresh, stale, unknown = _Conn(), _Conn(), _Conn()
    db._last_used[fresh] = time.monotonic()
    db._last_used[stale] = time.monotonic() - db._IDLE_PING_SECONDS - 1
    for conn in (fresh, stale, unknown):
        db._check_if_idle(conn)
    assert pinged == [stale]
