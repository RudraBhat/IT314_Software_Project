"""Issue #97: a PostGIS failure must surface as "unavailable", never as invented teams."""

import uuid
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from app.auth import Principal
from app.routers.dm.recommendations import (
    RECOMMENDATIONS_UNAVAILABLE,
    get_incident_team_recommendations,
)
from app.services.recommendations import _FALLBACK_TEAMS, recommend_candidate_teams


@pytest.fixture(autouse=True)
def _database_configured():
    with patch(
        "app.routers.dm.recommendations.get_settings",
        return_value=MagicMock(database_url="postgresql://mocked/drch_test"),
    ):
        yield


@pytest.fixture
def dispatcher() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email="dispatcher@example.com",
        full_name="Dispatcher",
        role="DISASTER_MGMT",
        mfa_verified=True,
        permissions=frozenset({"DISPATCH"}),
    )


def _connection_with_failing_spatial_query(incident_id: uuid.UUID) -> MagicMock:
    """Incident lookup succeeds; the PostGIS ranking query raises."""
    incident_row = {
        "incident_id": incident_id,
        "incident_ref": "INC-2026-000001",
        "scenario": "URBAN_FLOODING",
        "status": "VERIFIED",
        "district": "Ahmedabad",
        "latitude": 23.03,
        "longitude": 72.58,
    }

    def execute(query, *_args, **_kwargs):
        if "ST_Distance" in str(query):
            raise psycopg.errors.InternalError("function st_distance(geography) does not exist")
        result = MagicMock()
        result.fetchone.return_value = incident_row
        return result

    conn = MagicMock()
    conn.execute.side_effect = execute
    return conn


def test_forced_spatial_error_returns_unavailable_without_teams(dispatcher):
    incident_id = uuid.uuid4()
    conn = _connection_with_failing_spatial_query(incident_id)

    with patch("app.db.transaction") as transaction:
        transaction.return_value.__enter__.return_value = conn
        response = get_incident_team_recommendations(incident_id, dispatcher, limit=5)

    assert response.unavailable is True
    assert response.recommendations == []
    assert response.unavailable_reason == RECOMMENDATIONS_UNAVAILABLE
    assert response.requires_confirmation is True
    seed_names = {t["name"] for t in _FALLBACK_TEAMS}
    assert not any(r.team_name in seed_names for r in response.recommendations)


def test_spatial_error_propagates_from_the_service():
    """The service itself never swallows the error and substitutes seed teams."""
    conn = MagicMock()
    conn.execute.side_effect = psycopg.errors.InternalError("boom")
    with pytest.raises(psycopg.Error):
        recommend_candidate_teams(23.0, 72.5, "URBAN_FLOODING", conn=conn)


def test_live_database_candidates_are_not_marked_fallback():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {
            "resource_id": uuid.uuid4(),
            "name": "Live Boat Team",
            "agency_id": uuid.uuid4(),
            "agency_name": "SDRF",
            "status": "AVAILABLE",
            "quantity_available": 1,
            "capabilities": {"boat": True},
            "distance_km": 3.0,
        }
    ]
    recs = recommend_candidate_teams(23.0, 72.5, "URBAN_FLOODING", conn=conn)
    assert len(recs) == 1
    assert recs[0].is_fallback is False


def test_offline_seed_roster_is_always_labelled_fallback():
    recs = recommend_candidate_teams(23.0373, 72.5613, "URBAN_FLOODING", limit=3)
    assert recs, "seed roster should rank at least one team"
    assert all(r.is_fallback for r in recs)


@pytest.mark.db
def test_savepoint_keeps_the_transaction_usable_after_a_spatial_error(sql, monkeypatch):
    """Against real PostgreSQL: the failed ranking does not abort the request's transaction."""
    from app import db
    from app.config import get_settings
    from app.routers.dm.recommendations import _rank_teams_or_none
    from app.services import recommendations as service

    monkeypatch.setattr(service, "_POSTGIS_RECOMMEND_SQL", "SELECT no_such_function_for_issue_97()")
    get_settings.cache_clear()
    with db.transaction() as conn:
        result = _rank_teams_or_none(conn, latitude=23.0, longitude=72.5, scenario="URBAN_FLOODING")
        assert result is None
        assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
