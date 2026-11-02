"""RBAC matrix generated from the live route table (Sprint 3: RBAC & Security Audit Matrix).

Every protected route is called with no token, a wrong-role token, and (for staff routes) a staff
token without MFA. The expected answer is always 401/403 and never a 2xx/404/422, which proves the
guard runs before any handler logic. A new route that forgets its guard fails this test.
"""

import uuid

import pytest

pytestmark = pytest.mark.db

PUBLIC_PREFIXES = ("/api/v1/public", "/api/v1/auth", "/api/v1/internal", "/api/v1/donations", "/api/v1/health")


def _routes():
    from main import app

    seen = []
    for path, methods in app.openapi()["paths"].items():
        if not path.startswith("/api/v1") or path.startswith(PUBLIC_PREFIXES) or path in ("/api/v1/me", "/api/v1/auth/me"):
            continue
        for method in sorted(m.upper() for m in methods if m.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}):
            seen.append((method, path))
    return seen


def _fill(path: str) -> str:
    out = path
    while "{" in out:
        start, end = out.index("{"), out.index("}")
        out = out[:start] + str(uuid.uuid4()) + out[end + 1:]
    return out


def _call(client, method, path, headers=None):
    return client.request(method, _fill(path), headers=headers or {}, json={})


ROUTES = _routes()


def test_route_table_is_not_empty():
    assert len(ROUTES) > 60


@pytest.mark.parametrize("method,path", ROUTES)
def test_unauthenticated_is_401(client, method, path):
    assert _call(client, method, path).status_code == 401, f"{method} {path} is reachable without a token"


@pytest.mark.parametrize("method,path", [r for r in ROUTES if r[1].startswith("/api/v1/dm")])
def test_dm_routes_reject_other_roles_and_missing_mfa(client, make, method, path):
    citizen, field = make.citizen(), make.field_team_user()
    assert _call(client, method, path, citizen["headers"]).status_code == 403, f"citizen reached {method} {path}"
    assert _call(client, method, path, field["headers"]).status_code == 403, f"field user reached {method} {path}"
    staff = make.user("DISASTER_MGMT", permissions=("SUPERVISOR",))
    no_mfa = make.token(staff, mfa=False)
    assert _call(client, method, path, no_mfa).status_code == 401, f"staff without MFA reached {method} {path}"


@pytest.mark.parametrize("method,path", [r for r in ROUTES if r[1].startswith("/api/v1/field")])
def test_field_routes_reject_other_roles(client, make, method, path):
    assert _call(client, method, path, make.citizen()["headers"]).status_code == 403
    assert _call(client, method, path, make.staff("DISPATCH")["headers"]).status_code == 403


@pytest.mark.parametrize("method,path", [r for r in ROUTES if r[1].startswith(("/api/v1/me", "/api/v1/incidents"))])
def test_citizen_routes_reject_staff_and_field(client, make, method, path):
    assert _call(client, method, path, make.staff("DISPATCH")["headers"]).status_code == 403
    assert _call(client, method, path, make.field_team_user()["headers"]).status_code == 403


@pytest.mark.parametrize(
    "method,path,permission",
    [
        ("POST", "/api/v1/dm/staff", "SUPERVISOR"),
        ("POST", "/api/v1/dm/incidents/{id}/dispatches", "DISPATCH"),
        ("POST", "/api/v1/dm/incidents/{id}/closure", "CLOSURE"),
        ("POST", "/api/v1/dm/public-updates/{id}/publish", "PUBLISHER"),
        ("POST", "/api/v1/dm/moderation/{id}/decision", "MODERATOR"),
    ],
)
def test_permission_gated_routes_reject_staff_without_that_permission(client, make, method, path, permission):
    others = tuple(p for p in ("PUBLISHER", "MODERATOR", "CLOSURE", "DISPATCH", "SUPERVISOR") if p != permission)
    staff = make.staff(*others)
    r = _call(client, method, path, staff["headers"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_REQUIRED"
