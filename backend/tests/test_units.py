"""Unit tests that need no database."""

import uuid

import pyotp

from app import security
from app.services.ai_provider import UnavailableProvider, apply_guardrails


def test_root_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").json() == {"status": "healthy", "service": "drch-backend"}


def test_password_hashing_is_argon2id_and_verifies():
    h = security.hash_password("a long passphrase")
    assert h.startswith("$argon2id$")
    assert security.verify_password(h, "a long passphrase")
    assert not security.verify_password(h, "wrong")


def test_malformed_hash_is_a_failed_login_not_a_crash():
    # The seeded admin carries a placeholder, not a real Argon2 hash.
    assert not security.verify_password("$argon2id$v=19$m=65536,t=3,p=4$drch_bootstrap_admin_hash", "x")
    assert not security.verify_password(None, "x")


def test_token_purpose_is_enforced():
    uid = uuid.uuid4()
    mfa_token = security.issue_token(uid, 1, security.MFA, 5)
    assert security.decode_token(mfa_token, security.ACCESS) is None
    assert security.decode_token(mfa_token, security.MFA)["sub"] == str(uid)
    assert security.decode_token("not-a-token", security.ACCESS) is None


def test_mfa_secret_round_trip_and_totp():
    secret = security.new_totp_secret()
    assert security.decrypt_mfa_secret(security.encrypt_mfa_secret(secret)) == secret
    assert security.verify_totp(secret, pyotp.TOTP(secret).now())
    assert not security.verify_totp(secret, "000000x")


def test_ai_unavailable_never_invents_a_result():
    outcome = UnavailableProvider().triage({})
    assert outcome.status == "UNAVAILABLE"
    assert outcome.suggested_scenario is None and outcome.suggested_priority is None


def test_ai_guardrails_accept_valid_output():
    out = apply_guardrails(
        {"model": "m1", "scenario": "urban_flooding", "priority": "high", "confidence": 0.9,
         "factors": [{"name": "stranded people", "weight": 0.7}]}
    )
    assert out.status == "GENERATED"
    assert out.suggested_scenario == "URBAN_FLOODING" and out.suggested_priority == "HIGH"


def test_ai_guardrails_low_confidence():
    out = apply_guardrails({"model": "m1", "scenario": "cyclone", "priority": "LOW", "confidence": 0.2})
    assert out.status == "LOW_CONFIDENCE"


def test_ai_guardrails_flag_out_of_scope():
    out = apply_guardrails({"model": "m1", "scenario": "landslide", "priority": "HIGH", "confidence": 0.95})
    assert out.suggested_scenario is None
    assert out.factors["out_of_scope"] is True
    assert out.status == "LOW_CONFIDENCE"

def test_ai_guardrails_reject_earthquake_out_of_scope():
    out = apply_guardrails({"model": "m1", "scenario": "earthquake", "priority": "HIGH", "confidence": 0.95})
    assert out.suggested_scenario is None
    assert out.factors["out_of_scope"] is True
    assert out.status == "LOW_CONFIDENCE"


def test_ai_guardrails_discard_malformed_output():
    for raw in (None, "text", {"scenario": "cyclone"}, {"model": "m", "scenario": "cyclone",
                                                         "priority": "URGENT", "confidence": 0.9},
                {"model": "m", "scenario": "cyclone", "priority": "HIGH", "confidence": 7}):
        out = apply_guardrails(raw)
        assert out.status == "UNSAFE_OUTPUT"
        assert out.suggested_priority is None and out.suggested_scenario is None


def test_geo_boundary_and_district_resolution(monkeypatch):
    from app.geo import district_for, is_in_gujarat

    def mock_resolve(lat, lon):
        if abs(lat - 23.0225) < 0.1 and abs(lon - 72.5714) < 0.1:
            return "Ahmedabad", "Gujarat"
        if abs(lat - 21.1702) < 0.1 and abs(lon - 72.8311) < 0.1:
            return "Surat", "Gujarat"
        if abs(lat - 23.2420) < 0.1 and abs(lon - 69.6669) < 0.1:
            return "Kutch", "Gujarat"
        if abs(lat - 28.6139) < 0.1 and abs(lon - 77.2090) < 0.1:
            return "Central Delhi", "Delhi"
        if abs(lat - 19.0760) < 0.1 and abs(lon - 72.8777) < 0.1:
            return "Mumbai City", "Maharashtra"
        return None, None

    monkeypatch.setattr("app.geo.resolve_district_online", mock_resolve)

    # Inside Gujarat
    assert is_in_gujarat(23.0225, 72.5714) is True
    assert district_for(23.0225, 72.5714) == "Ahmedabad"

    assert is_in_gujarat(21.1702, 72.8311) is True
    assert district_for(21.1702, 72.8311) == "Surat"

    assert is_in_gujarat(23.2420, 69.6669) is True
    assert district_for(23.2420, 69.6669) == "Kutch"

    # Outside Gujarat
    assert is_in_gujarat(28.6139, 77.2090) is False  # Delhi
    assert district_for(28.6139, 77.2090) is None

    assert is_in_gujarat(19.0760, 72.8777) is False  # Mumbai
    assert district_for(19.0760, 72.8777) is None


def test_dynamic_geocoder_osm_fallback(monkeypatch):
    """Verify OpenStreetMap reverse geocoder parses live dynamic district response."""
    import json
    from unittest.mock import MagicMock

    from app.geo import resolve_district_online

    # Simulate OpenStreetMap Nominatim response
    fake_osm_response = json.dumps({
        "address": {
            "state_district": "Ahmedabad District",
            "state": "Gujarat",
            "country": "India"
        }
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.json.return_value = json.loads(fake_osm_response)

    monkeypatch.setattr("app.geo.httpx.get", lambda *args, **kwargs: mock_resp)

    district, state = resolve_district_online(23.0225, 72.5714)
    assert district == "Ahmedabad"
    assert state == "Gujarat"


def test_dynamic_geocoder_google_maps(monkeypatch):
    """Verify Google Maps geocoder parses live dynamic district response."""
    import json
    from unittest.mock import MagicMock

    from app.geo import resolve_district_online

    fake_google_response = json.dumps({
        "results": [
            {
                "address_components": [
                    {"long_name": "Surat", "types": ["administrative_area_level_2", "political"]},
                    {"long_name": "Gujarat", "types": ["administrative_area_level_1", "political"]},
                    {"long_name": "India", "types": ["country", "political"]}
                ]
            }
        ]
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.json.return_value = json.loads(fake_google_response)

    monkeypatch.setattr("app.geo.httpx.get", lambda *args, **kwargs: mock_resp)

    # Mock settings with google_maps_api_key
    from app import config
    orig_settings = config.get_settings()
    mock_settings = MagicMock(wraps=orig_settings)
    mock_settings.google_maps_api_key = "fake_test_key"
    monkeypatch.setattr("app.geo.get_settings", lambda: mock_settings)

    district, state = resolve_district_online(21.1702, 72.8311)
    assert district == "Surat"
    assert state == "Gujarat"


def test_ci_db_guard_decision_logic():
    """Exercise REQUIRE_DB_TESTS guard decision logic in isolation.

    Cases:
    - guard on and zero DB tests => fail (False)
    - guard on and some DB tests => ok (True)
    - guard off and zero DB tests => ok (True)
    - guard off and some DB tests => ok (True)
    """
    try:
        from conftest import evaluate_ci_guard
    except ImportError:
        from tests.conftest import evaluate_ci_guard

    # Guard on and zero DB tests => fail
    assert evaluate_ci_guard(require_db=True, db_tests_ran=False) is False

    # Guard on and some DB tests => ok
    assert evaluate_ci_guard(require_db=True, db_tests_ran=True) is True

    # Guard off and zero DB tests => ok
    assert evaluate_ci_guard(require_db=False, db_tests_ran=False) is True

    # Guard off and some DB tests => ok
    assert evaluate_ci_guard(require_db=False, db_tests_ran=True) is True

