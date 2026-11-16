"""Administrator staff account directory: GET /api/v1/admin/accounts."""

import uuid

import pytest

pytestmark = pytest.mark.db

URL = "/api/v1/admin/accounts"
SAFE_KEYS = {
    "user_id", "email", "full_name", "role", "designation", "status", "mfa_enabled", "last_login_at",
    "is_locked", "permissions", "team_name", "created_at", "is_you",
}


def _admin(make):
    admin = make.user("APP_MGMT")
    return admin, make.token(admin)


def _find(client, headers, **params):
    r = client.get(URL, headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_admin_sees_staff_accounts_with_only_safe_fields(make, client):
    admin, headers = _admin(make)
    body = _find(client, headers, q=admin["email"])
    assert body["total"] == 1
    item = body["items"][0]
    assert set(item) == SAFE_KEYS, "no phone, password hash, MFA secret or session data may be listed"
    assert item["email"] == admin["email"] and item["role"] == "APP_MGMT"
    assert item["status"] == "ACTIVE" and item["mfa_enabled"] is True and item["is_you"] is True
    assert item["is_locked"] is False


def test_citizens_are_never_listed(make, client):
    _, headers = _admin(make)
    citizen = make.citizen()
    assert _find(client, headers, q=citizen["email"])["total"] == 0


def test_dispatcher_permissions_and_field_team_are_shown(make, client):
    _, headers = _admin(make)
    dispatcher = make.user("DISASTER_MGMT", permissions=("DISPATCH", "PUBLISHER"))
    responder = make.field_team_user()
    d = _find(client, headers, q=dispatcher["email"])["items"][0]
    assert d["role"] == "DISASTER_MGMT" and d["permissions"] == ["DISPATCH", "PUBLISHER"] and d["is_you"] is False
    f = _find(client, headers, q=responder["email"])["items"][0]
    assert f["role"] == "FIELD_TEAM" and f["team_name"]


def test_filters_by_role_status_and_search(make, client, sql):
    _, headers = _admin(make)
    tag = uuid.uuid4().hex[:10]
    dispatcher = make.user("DISASTER_MGMT")
    pending = make.user("FIELD_TEAM")
    sql.execute("UPDATE users SET full_name = %s WHERE user_id = %s", (f"Alpha {tag}", dispatcher["user_id"]))
    sql.execute("UPDATE users SET full_name = %s, status = 'PENDING_SETUP' WHERE user_id = %s", (f"Beta {tag}", pending["user_id"]))
    assert _find(client, headers, q=tag)["total"] == 2
    only_dm = _find(client, headers, q=tag, role="DISASTER_MGMT")
    assert [i["user_id"] for i in only_dm["items"]] == [str(dispatcher["user_id"])]
    only_pending = _find(client, headers, q=tag, status="PENDING_SETUP")
    assert [i["user_id"] for i in only_pending["items"]] == [str(pending["user_id"])]
    assert _find(client, headers, q=tag, role="APP_MGMT")["total"] == 0
    assert _find(client, headers, q=f"alpha {tag}")["total"] == 1  # case-insensitive


def test_search_treats_percent_and_underscore_literally(make, client):
    _, headers = _admin(make)
    assert _find(client, headers, q="%")["total"] == 0
    assert _find(client, headers, q="zzzz_not_a_wildcard_%_zzzz")["total"] == 0


def test_paging(make, client, sql):
    _, headers = _admin(make)
    tag = uuid.uuid4().hex[:10]
    for i in range(3):
        user = make.user("DISASTER_MGMT")
        sql.execute("UPDATE users SET full_name = %s WHERE user_id = %s", (f"Pager {tag} {i}", user["user_id"]))
    first = _find(client, headers, q=tag, limit=2, page=1)
    second = _find(client, headers, q=tag, limit=2, page=2)
    assert first["total"] == 3 and first["pages"] == 2 and len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert not {i["user_id"] for i in first["items"]} & {i["user_id"] for i in second["items"]}


def test_locked_account_is_flagged(make, client, sql):
    _, headers = _admin(make)
    user = make.user("DISASTER_MGMT")
    sql.execute("UPDATE user_auth SET locked_until = now() + interval '1 hour' WHERE user_id = %s", (user["user_id"],))
    assert _find(client, headers, q=user["email"])["items"][0]["is_locked"] is True
    sql.execute("UPDATE user_auth SET locked_until = now() - interval '1 hour' WHERE user_id = %s", (user["user_id"],))
    assert _find(client, headers, q=user["email"])["items"][0]["is_locked"] is False


def test_summary_counts_all_staff_whatever_the_filter(make, client):
    _, headers = _admin(make)
    everything = _find(client, headers)["summary"]
    filtered = _find(client, headers, role="FIELD_TEAM", status="DISABLED")["summary"]
    assert filtered == everything
    assert everything["total"] >= 1 and everything["by_role"]["APP_MGMT"] >= 1 and everything["by_status"]["ACTIVE"] >= 1
    assert "NORMAL_USER" not in everything["by_role"]


@pytest.mark.parametrize("params", [{"role": "NORMAL_USER"}, {"status": "BOGUS"}, {"limit": 0}, {"page": 0}])
def test_invalid_filters_are_rejected(make, client, params):
    _, headers = _admin(make)
    assert client.get(URL, headers=headers, params=params).status_code == 422


def test_only_an_mfa_verified_administrator_can_open_it(make, client):
    admin = make.user("APP_MGMT")
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=make.token(admin, mfa=False)).status_code == 401
    assert client.get(URL, headers=make.citizen()["headers"]).status_code == 403
    assert client.get(URL, headers=make.field_team_user()["headers"]).status_code == 403
    assert client.get(URL, headers=make.staff("DISPATCH")["headers"]).status_code == 403
    supervisor = make.staff("SUPERVISOR")
    assert client.get(URL, headers=supervisor["headers"]).status_code == 403  # dispatch supervisors do not get the directory
