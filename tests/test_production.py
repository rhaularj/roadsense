"""Production-readiness behaviour: decision-layer fixes, delivery, privacy, identity, city data and condition."""
import json
import time

import cv2
import httpx
import numpy as np
import pytest
from conftest import add_event
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

from roadsense.agents.llm import LLMUnavailable, cache_key, check_residency
from roadsense.common.config import settings
from roadsense.common.db import row, session
from roadsense.core import condition, delivery, external, media, open311, privacy, reports
from roadsense.mcp_servers import municipality_server, reports_server

HRM = "Halifax Regional Municipality"
AUTH = {"Authorization": "Bearer test-token"}


def evidence(event_id, verified=0.8, verifier_class=None):
    with session() as conn:
        conn.execute("UPDATE events SET verified_confidence = ?, verifier_class = ? WHERE id = ?",
                     (verified, verifier_class, event_id))


def make_report(event_id, lat=44.643, lon=-63.58, code="D40", trip="trip1"):
    add_event(event_id, lat, lon, code=code, trip=trip)
    with session() as conn:
        return reports.create_or_merge(conn, event_id, "high", "x", HRM, 15, jurisdiction=HRM)


def approve(report_id, by="reviewer@roadsense.test"):
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        p = open311.build_payload(r)
        reports.set_status(conn, report_id, "approved", by, approved_payload_hash=open311.payload_hash(p),
                           approved_payload=json.dumps(p, sort_keys=True), approved_by=by)
        return p


# ---------------- decision layer ----------------
def test_one_pothole_seen_as_two_classes_is_one_report(db):
    first = make_report("ev-x1")["report"]
    add_event("ev-x2", 44.64301, -63.58, code="D20", trip="trip2")
    evidence("ev-x2", verifier_class="D40")  # the verifier saw a pothole where the edge saw an alligator crack
    with session() as conn:
        second = reports.create_or_merge(conn, "ev-x2", "medium", "x", HRM, 15, jurisdiction=HRM)
    assert second["action"] == "merged" and second["report"]["id"] == first["id"]
    assert second["report"]["confirmations"] == 2


def test_rejected_damage_is_not_proposed_again(db):
    rid = make_report("ev-r1")["report"]["id"]
    with session() as conn:
        reports.set_status(conn, rid, "rejected", "reviewer@roadsense.test")
    add_event("ev-r2", 44.64302, -63.58, trip="trip2")
    with session() as conn:
        again = reports.create_or_merge(conn, "ev-r2", "high", "x", HRM, 15, jurisdiction=HRM)
        pending = conn.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending_approval'").fetchone()[0]
    assert again["action"] == "suppressed" and again["report"]["id"] == rid and pending == 0


def test_rule_severity_and_map_jurisdiction_win_over_the_agent(db):
    add_event("ev-g1", 44.6800, -63.6797, area=0.001, conf=0.9)  # small, on Highway 102 (provincial)
    out = reports_server.create_or_merge("ev-g1", "high", "City of Toronto", "agent invents an authority")
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (out["report_id"],)).fetchone())
        actions = {a for (a,) in conn.execute("SELECT action FROM audit")}
    assert r["severity"] == "medium" and r["jurisdiction"] == "Nova Scotia Public Works"
    assert {"severity_disagreement", "jurisdiction_overridden"} <= actions


def test_llm_cache_key_keeps_event_ids():
    a = [{"role": "user", "content": "decide", "id": "trip1-3-aaa"}]
    b = [{"role": "user", "content": "decide", "id": "trip2-9-bbb"}]
    assert cache_key(["m"], a, None) != cache_key(["m"], b, None)
    assert cache_key(["m"], a, None, legacy=True) == cache_key(["m"], b, None, legacy=True)  # old demo cache


def test_residency_refuses_foreign_and_free_llms():
    object.__setattr__(settings, "data_residency", "ca")
    object.__setattr__(settings, "residency_llm_hosts", ["llm.ca-central.example"])
    try:
        with pytest.raises(LLMUnavailable, match="not in ROADSENSE_RESIDENCY_LLM_HOSTS"):
            check_residency("https://openrouter.ai/api/v1", ["paid/model"])
        with pytest.raises(LLMUnavailable, match="free models"):
            check_residency("https://llm.ca-central.example/v1", ["x/y:free"])
        check_residency("https://llm.ca-central.example/v1", ["x/y"])
    finally:
        object.__setattr__(settings, "data_residency", "any")
        object.__setattr__(settings, "residency_llm_hosts", [])


def test_severity_band_and_repair_target():
    assert reports.severity_band("D40", 0.30, 0.01) == "S3"
    assert reports.severity_band("D40", 0.30, 0.01, jolt_g=0.8) == "S4"  # an IMU jolt corroborates depth
    assert reports.severity_band("D00", None, 0.5) == "S2"                 # a line crack is never urgent
    assert reports.repair_target_days("S4", "motorway") == 4 and reports.repair_target_days("S2", "residential") == 30


# ---------------- delivery ----------------
def test_delivery_sends_the_approved_snapshot_and_retries(db, monkeypatch):
    rid = make_report("ev-d1")["report"]["id"]
    approved = approve(rid)
    add_event("ev-d2", 44.64301, -63.58, trip="trip2")  # a second driver after approval
    with session() as conn:
        merged = reports.create_or_merge(conn, "ev-d2", "high", "x", HRM, 15, jurisdiction=HRM)["report"]
    assert merged["confirmations"] == 2 and merged["pending_update"] == 1

    calls = []

    def flaky(payload, report=None):
        calls.append(payload)
        if len(calls) == 1:
            raise delivery.DeliveryError("city system down")
        return {"channel": "open311", "service_request_id": "77", "notice": "ok"}

    monkeypatch.setattr(delivery, "submit", flaky)
    with pytest.raises(ToolError, match="attempt 1"):
        municipality_server.deliver(rid)
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone())
    assert r["status"] == "approved" and r["delivery_attempts"] == 1 and r["next_attempt_at"]
    assert municipality_server.deliver(rid)["service_request_id"] == "77"
    assert calls[-1] == approved  # the payload the reviewer saw, not one rebuilt with 2 confirmations

    sent = []
    monkeypatch.setattr(delivery, "update", lambda *a, **k: sent.append(a) or {"ok": True})
    assert municipality_server.push_update(rid)["ok"] and "2 independent drivers" in sent[0][3]


def test_delivery_gives_up_after_max_attempts(db, monkeypatch):
    rid = make_report("ev-m1")["report"]["id"]
    approve(rid)
    monkeypatch.setattr(delivery, "submit", lambda *a, **k: (_ for _ in ()).throw(delivery.DeliveryError("down")))
    for _ in range(settings.max_delivery_attempts):
        with pytest.raises(ToolError):
            municipality_server.deliver(rid)
    with session() as conn:
        assert conn.execute("SELECT status FROM reports WHERE id = ?", (rid,)).fetchone()[0] == "delivery_failed"


def test_cityworks_and_arcgis_adapters(monkeypatch, tmp_path):
    seen = []

    def fake_post(url, data=None, files=None, timeout=None):
        seen.append((url, data, files))
        req = httpx.Request("POST", url)
        if url.endswith("Authenticate"):
            return httpx.Response(200, json={"Status": 0, "Value": {"Token": "tok"}}, request=req)
        if url.endswith("ServiceRequest/Create"):
            return httpx.Response(200, json={"Status": 0, "Value": {"RequestId": 4242}}, request=req)
        if url.endswith("addFeatures"):
            return httpx.Response(200, json={"addResults": [{"success": True, "objectId": 9}]}, request=req)
        return httpx.Response(200, json={"Status": 0, "Value": {}}, request=req)

    monkeypatch.setattr(delivery.httpx, "post", fake_post)
    object.__setattr__(settings, "cityworks_url", "https://cw.example/cityworks")
    object.__setattr__(settings, "arcgis_layer_url", "https://gis.example/FeatureServer/0")
    try:
        payload = {"authority": HRM, "channel": "cityworks", "service_code": "POTHOLE", "lat": 44.6, "long": -63.5,
                   "address_string": "Spring Garden Rd", "description": "Pothole", "media_url": "https://x/m.jpg",
                   "attributes": {"severity": "high", "confirmations": 2, "p1_candidate": True}}
        info = open311.service_info(HRM)
        assert delivery._cityworks_submit(payload, info, None)["service_request_id"] == "4242"
        assert json.loads(seen[1][1]["data"])["Priority"] == "1" and seen[1][1]["token"] == "tok"
        assert delivery._arcgis_submit(payload, info, None)["service_request_id"] == "9"
    finally:
        object.__setattr__(settings, "cityworks_url", "")
        object.__setattr__(settings, "arcgis_layer_url", "")
        delivery._cw_token.clear()


# ---------------- privacy ----------------
def test_signed_media_links(db):
    from roadsense.services import agent_api

    settings.media_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(settings.media_dir / "ev-media1.jpg"), np.zeros((20, 20, 3), np.uint8))
    c = TestClient(agent_api.app)
    assert c.get("/media/ev-media1.jpg").status_code == 403
    exp = int(time.time()) + 60
    assert c.get(media.signed_path("ev-media1", exp)).status_code == 200
    assert c.get(media.signed_path("ev-media1", exp).replace("sig=", "sig=0")).status_code == 403
    assert c.get(media.signed_path("ev-media1", int(time.time()) - 5)).status_code == 403  # expired
    assert c.get("/media/ev-media1.jpg", headers=AUTH).status_code == 200
    # the expiry comes from the report's creation time, so the approved payload hash is stable
    assert media.signed_url("e", "2026-11-01T00:00:00+00:00") == media.signed_url("e", "2026-11-01T00:00:00+00:00")


def test_server_redacts_frames_the_device_did_not_blur(tmp_path):
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)  # sharp detail everywhere
    path = tmp_path / "f.jpg"
    cv2.imwrite(str(path), frame)
    out = privacy.server_redact(path, [100, 100, 160, 150])
    assert out["reapplied"] is True
    again = privacy.server_redact(path, [100, 100, 160, 150])
    assert again["reapplied"] is False and again["outside_sharpness"] < privacy.SHARPNESS_LIMIT


def test_retention_purges_rejected_photos_and_car_positions(db):
    add_event("ev-old", 44.64, -63.58, status="rejected")
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / "ev-old.jpg").write_bytes(b"\xff\xd8x")
    with session() as conn:
        conn.execute("UPDATE events SET created_at = '2020-01-01T00:00:00+00:00', car_lat = 44.6, car_lon = -63.5")
        out = privacy.purge(conn)
        car = conn.execute("SELECT car_lat FROM events WHERE id = 'ev-old'").fetchone()[0]
    assert out["rejected_media"] == 1 and out["car_positions"] == 1 and car is None
    assert not (settings.media_dir / "ev-old.jpg").exists()


def test_event_upload_does_not_overwrite_existing_evidence(db):
    from roadsense.services import agent_api

    ev = {"id": "trip1-3-keepme", "trip_id": "trip1", "class_code": "D40", "class_name": "Pothole",
          "confidence": 0.7, "frames_seen": 4, "box": [10, 10, 60, 60], "box_area_ratio": 0.02, "lat": 44.643,
          "lon": -63.58, "captured_at": "2026-11-02T12:00:00Z"}
    img = cv2.imencode(".jpg", np.zeros((80, 80, 3), np.uint8))[1].tobytes()
    c = TestClient(agent_api.app)
    c.post("/events", data={"event": json.dumps(ev)}, files={"image": ("e.jpg", img, "image/jpeg")}, headers=AUTH)
    before = (settings.media_dir / "trip1-3-keepme.jpg").read_bytes()
    other = cv2.imencode(".jpg", np.full((80, 80, 3), 255, np.uint8))[1].tobytes()
    r = c.post("/events", data={"event": json.dumps(ev)}, files={"image": ("e.jpg", other, "image/jpeg")},
               headers=AUTH)
    assert r.json()["duplicate"] is True and (settings.media_dir / "trip1-3-keepme.jpg").read_bytes() == before


# ---------------- city data, feeds, condition ----------------
def test_city_requests_sync_dedupes_and_closes_the_loop(db):
    rid = make_report("ev-c1")["report"]["id"]
    with session() as conn:
        reports.set_status(conn, rid, "submitted", "test", service_request_id="5", channel="open311")
    geojson = {"features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-63.58, 44.64301]},
         "properties": {"OBJECTID": 11, "REQUEST_TYPE": "Pothole repair", "STATUS": "Closed"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-63.6, 44.7]},
         "properties": {"OBJECTID": 12, "REQUEST_TYPE": "Streetlight out", "STATUS": "Open"}}]}
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=geojson)))
    with session() as conn:
        reports.link_external(conn, row(conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()), 15)
        external._store(conn, {"id": "city:11", "source": "city_sr", "status": "open", "lat": 44.64301,
                               "lon": -63.58})
        reports.link_external(conn, row(conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()), 15)
        out = external.sync_city_requests(conn, "https://gis.example/FeatureServer/0", client=client)
        status = conn.execute("SELECT status FROM reports WHERE id = ?", (rid,)).fetchone()[0]
    assert out["skipped"] == 1 and out["reports_fixed"] == [rid] and status == "fixed"


def test_waze_feed_corroborates_reports(db):
    rid = make_report("ev-w1")["report"]["id"]
    feed = {"alerts": [{"uuid": "w-1", "subtype": "HAZARD_ON_ROAD_POT_HOLE", "location": {"x": -63.58, "y": 44.64305},
                        "pubMillis": 1762000000000}, {"uuid": "w-2", "subtype": "ACCIDENT_MAJOR",
                                                      "location": {"x": -63.5, "y": 44.6}}]}
    items = external.parse_waze_alerts(feed)
    with session() as conn:
        out = external.ingest_detections(conn, "waze", items)
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone())
    assert len(items) == 1 and out["matched_reports"] == 1 and r["corroborations"] == 1


def test_condition_index_and_deterioration(db):
    make_report("ev-k1")
    with session() as conn:
        conn.execute("UPDATE reports SET severity_band = 'S4', road_name = 'Spring Garden Rd'")
        segs = condition.segments(conn)
        conn.execute("UPDATE events SET width_m = 0.2, captured_at = '2026-10-01T00:00:00+00:00' WHERE id = 'ev-k1'")
    add_event("ev-k2", 44.64301, -63.58, trip="trip2")
    with session() as conn:
        reports.create_or_merge(conn, "ev-k2", "high", "x", HRM, 15, jurisdiction=HRM)
        conn.execute("UPDATE events SET width_m = 0.35, captured_at = '2026-10-15T00:00:00+00:00' WHERE id = 'ev-k2'")
        trend = condition.deterioration(conn, segs[0]["report_ids"][0])
    assert segs[0]["road"] == "Spring Garden Rd" and segs[0]["condition_index"] < 70 and segs[0]["estimate"]
    assert trend["passes"] == 2 and trend["trend"] == "worsening" and trend["growth_per_week"] > 0


def test_reviewer_can_correct_a_disputed_class(db):
    rid = make_report("ev-cl1")["report"]["id"]
    with session() as conn:
        r = reports.reclassify(conn, rid, "D20", "reviewer@roadsense.test")
        labels = conn.execute("SELECT label, class_code FROM labels").fetchall()
    assert r["class_code"] == "D20" and r["class_name"] == "Alligator crack" and r["class_disputed"] == 0
    assert [tuple(x) for x in labels] == [("reclassified", "D20")]


# ---------------- jobs ----------------
def test_jobs_are_durable_and_the_scheduler_queues_retries(db):
    from roadsense.services.jobs import Worker

    w = Worker()
    jid = w.submit("follow_up", actor="test")
    with session() as conn:
        conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (jid,))
    assert Worker().recover() == 1 and w.get(jid)["status"] == "queued"  # a restart re-queues interrupted work
    rid = make_report("ev-j1")["report"]["id"]
    approve(rid)
    with session() as conn:
        conn.execute("UPDATE reports SET delivery_attempts = 1, next_attempt_at = '2020-01-01T00:00:00+00:00'")
    assert "retry_deliveries" in w.schedule()
    assert "retry_deliveries" not in w.schedule()  # not queued twice


# ---------------- identity ----------------
@pytest.fixture
def web(db):
    from roadsense.web import app as webapp
    from roadsense.web import auth

    auth.bootstrap_admin()
    return TestClient(webapp.app)


def login(c, email="admin@roadsense.test", password="Test-Admin-Passw0rd"):
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["csrf"]


def test_sign_in_is_required_and_csrf_is_checked(web):
    assert web.get("/api/reports").status_code == 401
    assert web.post("/api/auth/login", json={"email": "admin@roadsense.test", "password": "nope"}).status_code == 401
    csrf = login(web)
    me = web.get("/api/me").json()
    assert me["authenticated"] and me["user"]["role"] == "admin" and "review" in me["permissions"]
    assert web.post("/api/users", json={"email": "v@roadsense.test", "role": "viewer"}).status_code == 403  # no CSRF
    made = web.post("/api/users", headers={"X-CSRF-Token": csrf},
                    json={"email": "v@roadsense.test", "role": "viewer", "password": "Viewer-Passw0rd1"})
    assert made.status_code == 200 and made.json()["role"] == "viewer"
    weak = web.post("/api/users", headers={"X-CSRF-Token": csrf},
                    json={"email": "w@roadsense.test", "role": "viewer", "password": "short"})
    assert weak.status_code == 422


def test_a_viewer_cannot_approve(web):
    csrf = login(web)
    web.post("/api/users", headers={"X-CSRF-Token": csrf},
             json={"email": "v2@roadsense.test", "role": "viewer", "password": "Viewer-Passw0rd1"})
    viewer = TestClient(web.app)
    vcsrf = login(viewer, "v2@roadsense.test", "Viewer-Passw0rd1")
    r = viewer.post("/api/reports/1/approve", headers={"X-CSRF-Token": vcsrf}, json={"payload_hash": "x"})
    assert r.status_code == 403 and "viewer" in r.json()["detail"]
    assert viewer.get("/api/users").status_code == 403


def test_agent_api_refuses_a_person_without_the_role(db):
    from roadsense.services import agent_api

    rid = make_report("ev-role1")["report"]["id"]
    c = TestClient(agent_api.app)
    r = c.post(f"/reports/{rid}/reject", headers={**AUTH, "X-RoadSense-User": "d@x.test", "X-RoadSense-Role": "driver"})
    assert r.status_code == 403
    ok = c.post(f"/reports/{rid}/reject", headers={**AUTH, "X-RoadSense-User": "r@x.test",
                                                   "X-RoadSense-Role": "reviewer"})
    assert ok.status_code == 200 and ok.json()["rejected_by"] == "r@x.test"


def test_security_headers(web):
    r = web.get("/")
    assert r.headers["X-Frame-Options"] == "DENY" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_production_warnings_flag_development_defaults():
    warnings = " ".join(settings.production_warnings)
    assert "data residency" in warnings and "PUBLIC_URL" in warnings
