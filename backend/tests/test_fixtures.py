"""Database fixture integration tests.

Verifies the test factory fixtures:
1. citizen_user can authenticate (single-step password login, issues access token).
2. staff_user passes the MFA check (two-step password + TOTP verification).
3. citizen is refused on /dm routes (returns 403 Forbidden).
4. field_user skips gracefully if field_team_members table or FIELD_TEAM role does not exist yet.
"""

import pyotp


def test_citizen_user_can_authenticate(client, citizen_user):
    """Citizen user fixture can authenticate via password login and access own profile."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": citizen_user["email"], "password": citizen_user["password"]},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["mfa_required"] is False
    assert "access_token" in data
    assert data["role"] == "NORMAL_USER"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"].lower() == citizen_user["email"].lower()
    assert me.json()["role"] == "NORMAL_USER"


def test_staff_user_passes_mfa_check(client, staff_user):
    """Staff user fixture initiates MFA on login and successfully verifies with TOTP code."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": staff_user["email"], "password": staff_user["password"]},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["mfa_required"] is True
    assert "mfa_token" in data
    mfa_token = data["mfa_token"]

    totp = pyotp.TOTP(staff_user["totp_secret"])
    code = totp.now()

    mfa_res = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert mfa_res.status_code == 200, mfa_res.text
    mfa_data = mfa_res.json()
    assert mfa_data["mfa_required"] is False
    assert "access_token" in mfa_data
    assert mfa_data["role"] == "DISASTER_MGMT"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {mfa_data['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "DISASTER_MGMT"


def test_citizen_refused_on_dm_route(client, citizen_user):
    """A citizen account attempting to access disaster management routes is denied with 403."""
    res = client.get("/api/v1/dm/incidents", headers=citizen_user["headers"])
    assert res.status_code == 403, res.text


def test_field_user_skips_gracefully_or_operates(client, field_user):
    """Field-user fixture operates or skips gracefully if field_team_members/FIELD_TEAM is missing."""
    assert field_user is not None
    assert "user_id" in field_user
    assert "headers" in field_user
    res = client.get("/api/v1/auth/me", headers=field_user["headers"])
    assert res.status_code == 200
