"""Issue #96: routes that need the database answer 503 instead of inventing data.

With DATABASE_URL unset, no field identity, field profile, assignment list,
team recommendation or team-request list may be fabricated. Every such route
must return 503 DATABASE_UNAVAILABLE, matching the DM dashboard.
"""

import uuid
from pathlib import Path

import pytest

from app.auth import FieldPrincipal, Principal
from app.config import get_settings
from app.errors import ApiError

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def dm_principal() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email="dispatcher@example.com",
        full_name="Dispatcher",
        role="DISASTER_MGMT",
        mfa_verified=True,
        permissions=frozenset({"DISPATCH"}),
    )


@pytest.fixture
def field_principal() -> FieldPrincipal:
    return FieldPrincipal(
        user_id=uuid.uuid4(),
        email="responder@example.com",
        full_name="Responder",
        role="FIELD_TEAM",
        member_id=uuid.uuid4(),
        team_resource_id=uuid.uuid4(),
        team_name="Team",
        agency_id=None,
        agency_name=None,
        callsign=None,
        is_leader=False,
    )


def _assert_unavailable(call) -> None:
    with pytest.raises(ApiError) as exc_info:
        call()
    assert exc_info.value.status == 503
    assert exc_info.value.code == "DATABASE_UNAVAILABLE"


def test_field_profile_is_503(no_database, field_principal):
    from app.routers.field import get_field_profile

    _assert_unavailable(lambda: get_field_profile(field_principal))


def test_field_assignments_is_503(no_database, field_principal):
    from app.routers.field import get_field_assignments

    _assert_unavailable(lambda: get_field_assignments(field_principal, active=False))


def test_team_recommendations_is_503_and_does_not_echo_incident(no_database, dm_principal):
    from app.routers.dm.recommendations import get_incident_team_recommendations

    _assert_unavailable(
        lambda: get_incident_team_recommendations(uuid.uuid4(), dm_principal, limit=5)
    )


def test_team_request_list_is_503(no_database, dm_principal):
    from app.routers.dm.recommendations import list_team_requests

    _assert_unavailable(
        lambda: list_team_requests(dm_principal, status="OPEN", limit=50, offset=0)
    )


def test_dm_dashboard_is_503(no_database, dm_principal):
    from app.routers.dm.dashboard import dashboard

    _assert_unavailable(lambda: dashboard(dm_principal))


def test_no_demo_identity_left_in_application_code():
    """The hard-coded demo team, agency and phone number must not come back."""
    forbidden = ("Demo Field Unit", "ECHO-1", "+919876543210")
    sources = [*(BACKEND / "app").rglob("*.py")]
    offenders = [
        f"{path.relative_to(BACKEND)}: {needle}"
        for path in sources
        for needle in forbidden
        if needle in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
