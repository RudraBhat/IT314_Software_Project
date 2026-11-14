"""Advisory photo analysis (S3-08): upload validation, advisory-only behaviour and the model-unavailable path."""

from unittest.mock import AsyncMock, patch

import pytest

from app.uploads import safe_filename, sniff_image_type

BASE = "/api/v1/dm"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64


# ----------------------------------------------------------------------- helpers (no database)


def test_sniff_image_type_reads_the_bytes_not_the_label():
    assert sniff_image_type(JPEG) == "image/jpeg"
    assert sniff_image_type(PNG) == "image/png"
    assert sniff_image_type(WEBP) == "image/webp"
    assert sniff_image_type(b"%PDF-1.7 not an image") is None
    assert sniff_image_type(b'{"x": 1}') is None
    assert sniff_image_type(b"") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "photo"),
        ("", "photo"),
        ("flood%20scene.jpg", "flood scene.jpg"),
        ("..%2F..%2Fetc%2Fpasswd", "passwd"),
        ("C%3A%5Cusers%5Cme%5Cpic.png", "pic.png"),
        ("a" * 300 + ".jpg", ("a" * 300 + ".jpg")[:100]),
        ("%E0%AA%97%E0%AB%81%E0%AA%9C.jpg", "ગુજ.jpg"),
    ],
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


# ----------------------------------------------------------------------- endpoint (database)


def _model_replies(payload: dict, status: int = 200):
    """Patch the image classifier call so no real model is needed."""
    response = AsyncMock()
    response.status_code = status
    response.json = lambda: payload
    http = AsyncMock()
    http.post.return_value = response
    patcher = patch("app.routers.dm.ai.httpx.AsyncClient")
    patcher.start().return_value.__aenter__.return_value = http
    return patcher, http


def _upload(client, staff, incident, body=JPEG, content_type="image/jpeg", filename="scene.jpg"):
    return client.post(
        f"{BASE}/incidents/{incident['incident_id']}/photo-analyse",
        headers={**staff["headers"], "content-type": content_type, "x-filename": filename},
        content=body,
    )


@pytest.fixture
def image_service(monkeypatch):
    monkeypatch.setenv("AI_IMAGE_SERVICE_URL", "http://image-service.test")


def test_wrong_content_type_is_415(client, make, staff_user):
    incident = make.incident()
    resp = _upload(client, staff_user, incident, content_type="text/plain")
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_multipart_is_not_accepted(client, make, staff_user):
    resp = _upload(client, make.staff("DISPATCH"), make.incident(), content_type="multipart/form-data; boundary=x")
    assert resp.status_code == 415


def test_bytes_that_are_not_an_image_are_415(client, make, staff_user, image_service):
    resp = _upload(client, staff_user, make.incident(), body=b'{"not": "an image"}')
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "INVALID_IMAGE"


def test_oversized_upload_is_413_before_it_is_processed(client, make, staff_user, image_service):
    resp = _upload(client, staff_user, make.incident(), body=JPEG + b"\x00" * (10 * 1024 * 1024))
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_unknown_incident_is_404(client, make, staff_user, image_service):
    resp = _upload(client, staff_user, {"incident_id": "00000000-0000-0000-0000-000000000000"})
    assert resp.status_code == 404


def test_citizen_cannot_analyse_photos(client, citizen_user, make, image_service):
    resp = _upload(client, citizen_user, make.incident())
    assert resp.status_code == 403


def test_model_not_configured_is_503(client, make, staff_user, monkeypatch):
    monkeypatch.delenv("AI_IMAGE_SERVICE_URL", raising=False)
    resp = _upload(client, staff_user, make.incident())
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_PHOTO_UNAVAILABLE"


def test_model_error_or_garbage_is_503(client, make, staff_user, image_service):
    for status, payload in ((500, {}), (200, {"prediction": None}), (200, {"confidence": "high"})):
        patcher, _ = _model_replies(payload, status)
        try:
            resp = _upload(client, staff_user, make.incident())
        finally:
            patcher.stop()
        assert resp.status_code == 503, (status, payload)


def test_flood_photo_suggests_a_scenario_without_touching_the_incident(client, make, sql, staff_user, image_service):
    incident = make.incident()
    before = sql.execute("SELECT status, verified_priority, version FROM incidents WHERE incident_id = %s", (incident["incident_id"],)).fetchone()
    patcher, http = _model_replies({"prediction": "flood", "confidence": 0.91, "needs_review": False, "top3": []})
    try:
        resp = _upload(client, staff_user, incident, body=PNG, content_type="image/png", filename="../../x%2Fflood.png")
    finally:
        patcher.stop()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["suggested_scenario"] == "urban_flooding"
    assert body["is_out_of_scope"] is False and body["no_disaster_detected"] is False
    assert body["filename"] == "flood.png"
    # The model is called with the sniffed type and the cleaned file name.
    sent = http.post.call_args.kwargs["files"]["file"]
    assert sent[0] == "flood.png" and sent[2] == "image/png"

    after = sql.execute("SELECT status, verified_priority, version FROM incidents WHERE incident_id = %s", (incident["incident_id"],)).fetchone()
    assert after == before  # advisory only: nothing is verified, prioritised or changed
    audit = sql.execute(
        "SELECT result FROM audit_logs WHERE entity_id = %s AND action = 'AI_PHOTO_ANALYSED'", (incident["incident_id"],)
    ).fetchall()
    assert len(audit) == 1 and audit[0]["result"] == "SUCCESS"


@pytest.mark.parametrize(
    ("prediction", "scenario", "out_of_scope", "no_disaster"),
    [
        ("fire", "industrial_fire", False, False),
        ("hurricane", "cyclone", False, False),
        ("earthquake", None, True, False),  # not one of the three supported scenarios
        ("landslide", None, True, False),
        ("other_disaster", None, True, False),
        ("not_disaster", None, False, True),
    ],
)
def test_class_mapping(client, make, staff_user, image_service, prediction, scenario, out_of_scope, no_disaster):
    patcher, _ = _model_replies({"prediction": prediction, "confidence": 0.8, "needs_review": False})
    try:
        resp = _upload(client, staff_user, make.incident(), body=WEBP, content_type="image/webp")
    finally:
        patcher.stop()
    assert resp.status_code == 200
    body = resp.json()
    assert (body["suggested_scenario"], body["is_out_of_scope"], body["no_disaster_detected"]) == (scenario, out_of_scope, no_disaster)


def test_analytics_reports_decisions_by_scenario_and_confidence_band(client, staff_user):
    resp = client.get(f"{BASE}/analytics", headers=staff_user["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["ai_by_decision"], list)
    assert "confidence_bands" in body["definitions"]
