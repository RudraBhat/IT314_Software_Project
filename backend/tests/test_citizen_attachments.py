"""Citizen photo attachments (NU-FR-05): upload, list, download, remove, limits, isolation, moderation."""

import base64
import uuid

import pytest

pytestmark = pytest.mark.db

PAYLOAD = {
    "scenario": "urban_flooding",
    "description": "Severe waterlogging on the main market road, water entered shops.",
    "reported_urgency": "HIGH",
    "people_affected": 15,
    "location_source": "GPS",
    "latitude": 23.0225,
    "longitude": 72.5714,
}
# A valid 1x1 PNG; extra trailing bytes make distinct files with the same signature.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _png(n: int = 0) -> bytes:
    return PNG + bytes([n]) * n


def _incident(client, citizen) -> str:
    headers = {**citizen["headers"], "Idempotency-Key": str(uuid.uuid4())}
    r = client.post("/api/v1/incidents", json=PAYLOAD, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["incident_id"]


def _upload(client, citizen, iid, data=None, content_type="image/png", name="flood%20road.png"):
    headers = {**citizen["headers"], "Content-Type": content_type, "X-Filename": name}
    return client.post(f"/api/v1/me/incidents/{iid}/attachments", content=data if data is not None else PNG, headers=headers)


def test_upload_then_list_and_download_round_trip(client, make):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    up = _upload(client, citizen, iid)
    assert up.status_code == 201, up.text
    meta = up.json()
    assert meta["status"] == "Awaiting review" and meta["mime_type"] == "image/png"
    assert meta["file_name"] == "flood road.png" and meta["size_bytes"] == len(PNG)
    listing = client.get(f"/api/v1/me/incidents/{iid}/attachments", headers=citizen["headers"]).json()
    assert [i["evidence_id"] for i in listing["items"]] == [meta["evidence_id"]]
    download = client.get(f"/api/v1/me/incidents/{iid}/attachments/{meta['evidence_id']}", headers=citizen["headers"])
    assert download.status_code == 200 and download.content == PNG
    assert download.headers["content-type"] == "image/png" and download.headers["x-content-type-options"] == "nosniff"


def test_same_photo_twice_returns_the_first(client, make):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    first = _upload(client, citizen, iid)
    again = _upload(client, citizen, iid)
    assert again.status_code == 200 and again.json()["evidence_id"] == first.json()["evidence_id"]


def test_only_real_images_are_accepted(client, make):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    fake = _upload(client, citizen, iid, data=b"<script>alert(1)</script>", content_type="image/png")
    assert fake.status_code == 415 and fake.json()["error"]["code"] == "INVALID_IMAGE"
    wrong_type = _upload(client, citizen, iid, content_type="application/pdf")
    assert wrong_type.status_code == 415 and wrong_type.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_oversized_photo_is_refused(client, make):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    big = PNG + b"\0" * (5 * 1024 * 1024 + 1)
    r = _upload(client, citizen, iid, data=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_at_most_five_photos_per_report(client, make):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    for n in range(1, 6):
        assert _upload(client, citizen, iid, data=_png(n)).status_code == 201
    r = _upload(client, citizen, iid, data=_png(6))
    assert r.status_code == 409 and r.json()["error"]["code"] == "TOO_MANY_ATTACHMENTS"


def test_other_citizens_cannot_see_or_add_photos(client, make):
    owner, other = make.citizen(), make.citizen()
    iid = _incident(client, owner)
    evidence_id = _upload(client, owner, iid).json()["evidence_id"]
    assert client.get(f"/api/v1/me/incidents/{iid}/attachments", headers=other["headers"]).status_code == 404
    assert client.get(f"/api/v1/me/incidents/{iid}/attachments/{evidence_id}", headers=other["headers"]).status_code == 404
    assert _upload(client, other, iid, data=_png(2)).status_code == 404
    assert client.delete(f"/api/v1/me/incidents/{iid}/attachments/{evidence_id}", headers=other["headers"]).status_code == 404


def test_removing_a_photo_deletes_the_file_and_hides_it(client, make, sql):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    evidence_id = _upload(client, citizen, iid).json()["evidence_id"]
    gone = client.delete(f"/api/v1/me/incidents/{iid}/attachments/{evidence_id}", headers=citizen["headers"])
    assert gone.status_code == 200 and gone.json()["status"] == "Removed"
    assert client.get(f"/api/v1/me/incidents/{iid}/attachments/{evidence_id}", headers=citizen["headers"]).status_code == 404
    assert client.get(f"/api/v1/me/incidents/{iid}/attachments", headers=citizen["headers"]).json()["items"] == []
    assert sql.execute("SELECT 1 FROM evidence_blobs WHERE evidence_id = %s", (evidence_id,)).fetchone() is None
    state = sql.execute("SELECT scan_state FROM evidence_files WHERE evidence_id = %s", (evidence_id,)).fetchone()
    assert state["scan_state"] == "REJECTED"
    assert client.delete(f"/api/v1/me/incidents/{iid}/attachments/{evidence_id}", headers=citizen["headers"]).status_code == 404


def test_upload_is_audited_and_reaches_the_moderation_queue(client, make, sql):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    evidence_id = _upload(client, citizen, iid).json()["evidence_id"]
    row = sql.execute(
        "SELECT result FROM audit_logs WHERE entity_id = %s AND action = 'EVIDENCE_UPLOADED'", (evidence_id,)
    ).fetchone()
    assert row["result"] == "SUCCESS"
    staff = make.staff("MODERATOR")
    queue = client.get("/api/v1/dm/moderation/queue", headers=staff["headers"])
    assert queue.status_code == 200
    assert evidence_id in [str(i["evidence_id"]) for i in queue.json()["items"]]


def test_dispatcher_sees_the_photo_on_the_incident(client, make):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    _upload(client, citizen, iid)
    detail = client.get(f"/api/v1/dm/incidents/{iid}", headers=make.staff()["headers"]).json()
    assert len(detail["evidence"]) == 1 and detail["evidence"][0]["scan_state"] == "PENDING"


def test_photos_require_a_citizen_login(client, make):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    assert client.get(f"/api/v1/me/incidents/{iid}/attachments").status_code == 401
    staff = make.staff()
    assert client.get(f"/api/v1/me/incidents/{iid}/attachments", headers=staff["headers"]).status_code == 403


def test_moderator_can_open_the_photo_and_the_view_is_audited(client, make, sql):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    evidence_id = _upload(client, citizen, iid, data=_png(3)).json()["evidence_id"]
    moderator = make.staff("MODERATOR")

    queue = client.get("/api/v1/dm/moderation/queue", headers=moderator["headers"]).json()["items"]
    assert next(i for i in queue if i["evidence_id"] == evidence_id)["has_preview"] is True

    r = client.get(f"/api/v1/dm/moderation/{evidence_id}/content", headers=moderator["headers"])
    assert r.status_code == 200 and r.content == _png(3)
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in r.headers["cache-control"]
    viewed = sql.execute(
        "SELECT actor_id FROM audit_logs WHERE entity_id = %s AND action = 'EVIDENCE_VIEWED'", (evidence_id,)
    ).fetchall()
    assert [v["actor_id"] for v in viewed] == [moderator["user_id"]]


def test_only_moderators_can_open_photos_and_removed_photos_are_gone(client, make):
    citizen = make.citizen()
    iid = _incident(client, citizen)
    evidence_id = _upload(client, citizen, iid, data=_png(4)).json()["evidence_id"]
    url = f"/api/v1/dm/moderation/{evidence_id}/content"

    assert client.get(url, headers=make.staff("DISPATCH")["headers"]).status_code == 403
    assert client.get(url, headers=citizen["headers"]).status_code == 403

    client.delete(f"/api/v1/me/incidents/{iid}/attachments/{evidence_id}", headers=citizen["headers"])
    assert client.get(url, headers=make.staff("MODERATOR")["headers"]).status_code == 404
