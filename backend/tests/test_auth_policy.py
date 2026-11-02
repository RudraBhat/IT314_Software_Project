"""Citizen registration contract (s.2.1): password policy, duplicate email, rate limiting."""

import uuid

import pytest

pytestmark = pytest.mark.db


def _register(client, password="Str0ng!pass", email=None):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email or f"{uuid.uuid4().hex[:10]}@example.in", "password": password, "full_name": "Ramesh Patel"},
    )


def test_register_returns_contract_fields_and_a_session(client):
    r = _register(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "NORMAL_USER" and body["status"] == "ACTIVE" and body["user_id"] and body["access_token"]


@pytest.mark.parametrize("password", ["short1!", "nodigits!!", "nospecial12", "        "])
def test_weak_passwords_are_rejected(client, password):
    r = _register(client, password)
    assert r.status_code == 422 and r.json()["error"]["code"] == "WEAK_PASSWORD"


def test_duplicate_email_code(client):
    email = f"{uuid.uuid4().hex[:10]}@example.in"
    assert _register(client, email=email).status_code == 201
    r = _register(client, email=email)
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_EMAIL"


def test_login_is_rate_limited(client, monkeypatch):
    from app import ratelimit

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    ratelimit.reset()
    try:
        codes = [client.post("/api/v1/auth/login", json={"email": "nobody@example.in", "password": "x"}).status_code
                 for _ in range(22)]
    finally:
        ratelimit.reset()
    assert codes[:20] == [401] * 20 and codes[20:] == [429, 429]
