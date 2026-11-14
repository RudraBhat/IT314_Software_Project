"""RBAC matrix generated from the live route table (Sprint 3: RBAC & Security Audit Matrix).

Every protected route is called with no token, a wrong-role token, and (for staff routes) a staff
token without MFA. The expected answer is always 401/403 and never a 2xx/404/422, which proves the
guard runs before any handler logic. A new route that forgets its guard fails this test.

Roles covered (S3-02): public (no token), citizen, field, dispatcher (DISASTER_MGMT) and admin
(APP_MGMT). Admin manages accounts through invitations only and has no operational access.
"""

import uuid

import pytest

pytestmark = pytest.mark.db

# The payment webhook has no bearer token by design: it is authenticated by the gateway's HMAC
# signature over the raw body (tests/test_donations.py covers the tampered-signature case).
PUBLIC_PREFIXES = (
    "/api/v1/public", "/api/v1/auth", "/api/v1/internal", "/api/v1/donations", "/api/v1/health",
    "/api/v1/payments/webhook",
)


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


OPERATIONAL_PREFIXES = ("/api/v1/dm", "/api/v1/field", "/api/v1/me", "/api/v1/incidents")


@pytest.mark.parametrize("method,path", [r for r in ROUTES if r[1].startswith(OPERATIONAL_PREFIXES)])
def test_admin_has_no_operational_access(client, make, method, path):
    """APP_MGMT is not a dispatcher, responder or citizen: every operational route answers 403."""
    admin = make.token(make.user("APP_MGMT"))
    assert _call(client, method, path, admin).status_code == 403, f"admin reached {method} {path}"


def test_only_admin_or_supervisor_passes_the_invitation_guard(client, make):
    """The admin's one job: invitations. 422 (empty body) proves the role guard let the caller through."""
    path = "/api/v1/auth/invitations"
    assert _call(client, "POST", path, make.token(make.user("APP_MGMT"))).status_code == 422
    assert _call(client, "POST", path, make.staff("SUPERVISOR")["headers"]).status_code == 422
    for headers in (make.citizen()["headers"], make.field_team_user()["headers"], make.staff("DISPATCH")["headers"]):
        assert _call(client, "POST", path, headers).status_code == 403
