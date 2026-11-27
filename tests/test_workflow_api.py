"""The workflow over HTTP: roles, illegal moves, filters, photos, and the end-to-end walk of one report."""
from datetime import timedelta

import cv2
import numpy as np
import pytest
from conftest import add_event
from fastapi.testclient import TestClient

from roadsense.common.config import settings
from roadsense.common.db import now, row, session
from roadsense.core import ledger, open311, reports, workflow
from roadsense.services import agent_api

HRM = "Halifax Regional Municipality"
AUTH = {"Authorization": "Bearer test-token"}
api = TestClient(agent_api.app)
SOON = (workflow.today() + timedelta(days=5)).isoformat()
_n = {"i": 0}


def person(email, role, uid=None):
    h = {**AUTH, "X-RoadSense-User": email, "X-RoadSense-Role": role}
    return {**h, "X-RoadSense-User-Id": str(uid)} if uid is not None else h


def user(email, role) -> int:
    with session() as conn:
        conn.execute("INSERT INTO users (email, role, created_at) VALUES (?, ?, ?)", (email, role, now()))
        return conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]


def new_report(lat=None) -> int:
    _n["i"] += 1
    eid = f"ev-api{_n['i']}"
    add_event(eid, lat or 44.60 + _n["i"] * 0.003, -63.58)
    with session() as conn:
        conn.execute("UPDATE events SET verified_confidence = 0.9 WHERE id = ?", (eid,))
        return reports.create_or_merge(conn, eid, "high", "x", HRM, 15, jurisdiction=HRM)["report"]["id"]


def payload_hash(rid):
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone())
    return open311.payload_hash(open311.build_payload(r))


def jpeg(color=128, exif=False) -> bytes:
    data = cv2.imencode(".jpg", np.full((60, 80, 3), color, np.uint8))[1].tobytes()
    if exif:  # an APP1 Exif segment right after SOI, as a phone camera writes it (with a GPS tag inside)
        seg = b"Exif\x00\x00GPSLatitude=44.64"
        data = data[:2] + b"\xff\xe1" + (len(seg) + 2).to_bytes(2, "big") + seg + data[2:]
    return data


@pytest.fixture
def staff(db):
    return {"rev": person("rev@x.test", "reviewer"), "insp_id": (i := user("insp@x.test", "inspector")),
            "insp": person("insp@x.test", "inspector", i), "other": person("o@x.test", "inspector", user("o@x.test",
                                                                                                         "inspector")),
            "driver": person("d@x.test", "driver"), "viewer": person("v@x.test", "viewer")}


def test_roles_and_illegal_moves_over_http(staff):
    rid = new_report()
    h = payload_hash(rid)
    for who in ("driver", "viewer", "insp"):
        assert api.post(f"/reports/{rid}/approve", json={"payload_hash": h}, headers=staff[who]).status_code == 403
    assert api.post(f"/reports/{rid}/approve", json={"payload_hash": "stale"}, headers=staff["rev"]).status_code == 409
    r = api.post(f"/reports/{rid}/approve", json={"payload_hash": h}, headers=staff["rev"])
    assert r.status_code == 200 and r.json()["status"] == "awaiting_inspection"
    assert r.json()["allowed_actions"] == ["assign"] and r.json()["status_label"] == "Awaiting inspection"
    again = api.post(f"/reports/{rid}/approve", json={"payload_hash": h}, headers=staff["rev"])
    assert again.status_code == 409 and "awaiting inspection" in again.json()["detail"]
    assert api.post(f"/reports/{rid}/reject", headers=staff["rev"]).status_code == 409

    assert api.post(f"/reports/{rid}/assign", json={"inspector_id": staff["insp_id"]},
                    headers=staff["insp"]).status_code == 403
    r = api.post(f"/reports/{rid}/assign", json={"inspector_id": staff["insp_id"]}, headers=staff["rev"])
    assert r.json()["inspector_id"] == staff["insp_id"]

    form = {"outcome": "repair_needed", "repair_eta": SOON, "severity_band": "S3"}
    assert api.post(f"/reports/{rid}/inspection", data=form, headers=staff["other"]).status_code == 403
    assert api.post(f"/reports/{rid}/inspection", data=form, headers=staff["viewer"]).status_code == 403
    assert api.post(f"/reports/{rid}/inspection", data={**form, "repair_eta": ""},
                    headers=staff["insp"]).status_code == 422
    assert api.post(f"/reports/{rid}/inspection", data={**form, "outcome": "maybe"},
                    headers=staff["insp"]).status_code == 422
    r = api.post(f"/reports/{rid}/inspection", data=form, headers=staff["insp"])
    assert r.status_code == 200 and r.json()["status"] == "repair_needed" and r.json()["severity_band"] == "S3"
    assert set(r.json()["allowed_actions"]) == {"repaired", "reschedule"}

    later = (workflow.today() + timedelta(days=9)).isoformat()
    assert api.patch(f"/reports/{rid}/eta", json={"repair_eta": later}, headers=staff["insp"]).json()["repair_eta"] \
        == later
    r = api.post(f"/reports/{rid}/repaired", data={"notes": "hot mix"}, headers=staff["insp"])
    assert r.json()["status"] == "repaired" and r.json()["repair_notes"] == "hot mix"
    assert api.post(f"/reports/{rid}/reopen", json={"reason": ""}, headers=staff["insp"]).status_code == 422
    r = api.post(f"/reports/{rid}/reopen", json={"reason": "came back"}, headers=staff["insp"])
    assert r.json()["status"] == "reopened" and r.json()["reopen_count"] == 1


def test_report_lists_filter_by_inspector_status_and_overdue(staff):
    mine, theirs, late = new_report(), new_report(), new_report()
    past = (workflow.today() - timedelta(days=10)).isoformat() + "T12:00:00+00:00"
    with session() as conn:
        for rid in (mine, theirs, late):
            workflow.transition(conn, rid, "approve", "rev", "reviewer", at=past)
        workflow.transition(conn, mine, "assign", "rev", "reviewer", inspector_id=staff["insp_id"])
        workflow.transition(conn, late, "assign", "rev", "reviewer", inspector_id=staff["insp_id"], at=past)
        workflow.transition(conn, late, "repair_needed", "rev", "reviewer", at=past,
                            repair_eta=(workflow.today() - timedelta(days=3)).isoformat())
    me = api.get("/reports", params={"inspector_id": "me"}, headers=staff["insp"]).json()
    assert {r["id"] for r in me} == {mine, late}
    assert api.get("/reports", params={"inspector_id": "me"}, headers=staff["rev"]).status_code == 400
    overdue = api.get("/reports", params={"overdue": "true"}, headers=staff["rev"]).json()
    assert [r["id"] for r in overdue] == [late] and overdue[0]["overdue"] is True
    waiting = api.get("/reports", params={"status": "awaiting_inspection"}, headers=staff["rev"]).json()
    assert [r["id"] for r in waiting] == [theirs]
    assert api.get("/reports", params={"status": "submitted"}, headers=staff["rev"]).status_code == 400
    assert api.get("/stats", headers=AUTH).json()["overdue"] == 1
    d = api.get(f"/reports/{mine}", headers=staff["insp"]).json()
    assert d["report"]["inspector"]["email"] == "insp@x.test" and "approved_payload" not in d["report"]


def test_inspection_photo_is_checked_reencoded_and_served(staff):
    rid = new_report()
    with session() as conn:
        workflow.transition(conn, rid, "approve", "rev", "reviewer")
        workflow.transition(conn, rid, "assign", "rev", "reviewer", inspector_id=staff["insp_id"])
    url = f"/reports/{rid}/inspection"
    form = {"outcome": "no_repair_needed", "notes": "surface only"}
    before = set(settings.media_dir.glob("photo-*.jpg"))
    bad = api.post(url, data=form, files={"photo": ("x.txt", b"hello", "text/plain")}, headers=staff["insp"])
    assert bad.status_code == 415
    big = api.post(url, data=form, files={"photo": ("x.jpg", b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024), "image/jpeg")},
                   headers=staff["insp"])
    assert big.status_code == 413
    gif = api.post(url, data=form, files={"photo": ("x.gif", b"GIF89a....", "image/gif")}, headers=staff["insp"])
    assert gif.status_code == 415
    assert set(settings.media_dir.glob("photo-*.jpg")) == before  # nothing kept from refused uploads
    ok = api.post(url, data=form, files={"photo": ("site.jpg", jpeg(exif=True), "image/jpeg")}, headers=staff["insp"])
    assert ok.status_code == 200
    r = ok.json()
    kind, _, pid = r["inspection_photo"].partition(":")
    assert r["status"] == "closed" and r["closed_reason"] == "no_repair_needed" and kind == "inspection"
    stored = (settings.media_dir / f"photo-{pid}.jpg").read_bytes()
    assert stored.startswith(b"\xff\xd8") and b"Exif" not in stored and b"GPSLatitude" not in stored
    assert api.get(f"/photos/{pid}.jpg").status_code == 401
    assert api.get(f"/photos/{pid}.jpg", headers=AUTH).content == stored


def test_png_photo_on_repair_and_orphans_are_dropped(staff):
    rid = new_report()
    png = cv2.imencode(".png", np.full((40, 40, 3), 200, np.uint8))[1].tobytes()
    before = set(settings.media_dir.glob("photo-*.jpg"))
    early = api.post(f"/reports/{rid}/repaired", files={"photo": ("p.png", png, "image/png")}, headers=staff["rev"])
    assert early.status_code == 409 and set(settings.media_dir.glob("photo-*.jpg")) == before
    with session() as conn:
        workflow.transition(conn, rid, "approve", "rev", "reviewer")
        workflow.transition(conn, rid, "assign", "rev", "reviewer", inspector_id=staff["insp_id"])
        workflow.transition(conn, rid, "repair_needed", "rev", "reviewer", repair_eta=SOON)
    r = api.post(f"/reports/{rid}/repaired", data={"notes": "done"}, files={"photo": ("p.png", png, "image/png")},
                 headers=staff["rev"]).json()
    assert r["repair_photo"].startswith("repair:") and r["verification_status"] == "awaiting"


# ---------------- the web app: roles, the assign picker, photos ----------------
def signed_in(email=None, password=None):
    from roadsense.web import auth
    from roadsense.web.app import app

    auth.bootstrap_admin()
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email or settings.admin_email,
                                        "password": password or settings.admin_password})
    return c, r.json()["csrf"]


def test_web_roles_for_inspectors(db):
    admin, csrf = signed_in()
    for email, role in (("insp@roadsense.test", "inspector"), ("rev@roadsense.test", "reviewer")):
        assert admin.post("/api/users", headers={"X-CSRF-Token": csrf},
                          json={"email": email, "role": role, "password": "Inspector-Passw0rd1"}).status_code == 200
    insp, icsrf = signed_in("insp@roadsense.test", "Inspector-Passw0rd1")
    rev, _ = signed_in("rev@roadsense.test", "Inspector-Passw0rd1")
    assert "inspect" in insp.get("/api/me").json()["permissions"] and \
        "review" not in insp.get("/api/me").json()["permissions"]
    assert insp.post("/api/reports/1/approve", headers={"X-CSRF-Token": icsrf},
                     json={"payload_hash": "x"}).status_code == 403
    assert insp.post("/api/reports/1/assign", headers={"X-CSRF-Token": icsrf},
                     json={"inspector_id": 1}).status_code == 403
    picker = rev.get("/api/users", params={"role": "inspector"}).json()
    assert [u["email"] for u in picker] == ["insp@roadsense.test"] and set(picker[0]) == {"id", "email", "name", "role"}
    assert rev.get("/api/users").status_code == 403  # the full list stays admin-only
    assert insp.get("/api/users", params={"role": "inspector"}).status_code == 403
    assert TestClient(admin.app).get("/api/media/photo/abc.jpg").status_code == 401
    assert admin.get("/api/media/photo/bad$id.jpg").status_code == 400
    assert admin.get("/api/media/photo/abc123.jpg").status_code == 404


def test_sso_accepts_the_inspector_role():
    from roadsense.web import auth

    assert "inspector" in auth.ROLES and auth.allowed({"role": "inspector"}, "inspect")
    assert not auth.allowed({"role": "inspector"}, "review") and not auth.allowed({"role": "driver"}, "inspect")


# ---------------- end to end ----------------
def test_one_report_walks_the_whole_workflow_with_an_intact_ledger(staff):
    """review → assign → inspection (repair needed, ETA) → repaired → re-detection reopens → repair needed →
    repaired → verified by two clean passes; every step in the timeline; the integrity check stays green."""
    import json

    rid = new_report(lat=44.643)
    with session() as conn:
        lat, lon = conn.execute("SELECT lat, lon FROM reports WHERE id = ?", (rid,)).fetchone()
    rev, insp = staff["rev"], staff["insp"]
    assert api.post(f"/reports/{rid}/approve", json={"payload_hash": payload_hash(rid)}, headers=rev).status_code == 200
    api.post(f"/reports/{rid}/assign", json={"inspector_id": staff["insp_id"]}, headers=rev)
    api.post(f"/reports/{rid}/inspection", data={"outcome": "repair_needed", "repair_eta": SOON}, headers=insp)
    assert api.post(f"/reports/{rid}/repaired", data={"notes": "patched"}, headers=insp).json()["status"] == "repaired"

    add_event("ev-e2e-again", lat + 3 / 111_320, lon, trip="trip-later")  # a later trip sees the pothole again
    with session() as conn:
        conn.execute("UPDATE events SET verified_confidence = 0.9 WHERE id = 'ev-e2e-again'")
        out = reports.create_or_merge(conn, "ev-e2e-again", "high", "x", HRM, 15, jurisdiction=HRM,
                                      actor="agent:triage")
    assert out["action"] == "reopened" and out["report"]["status"] == "reopened"

    api.post(f"/reports/{rid}/inspection", data={"outcome": "repair_needed", "repair_eta": SOON}, headers=insp)
    assert api.get(f"/reports/{rid}", headers=insp).json()["report"]["status"] == "repair_needed"
    assert api.post(f"/reports/{rid}/repaired", headers=insp).json()["status"] == "repaired"

    from roadsense.core import repair

    for trip, south in (("trip-p1", 10), ("trip-p2", 8)):
        with session() as conn:
            conn.execute("INSERT INTO road_passes (id, trip_id, lat, lon, heading, captured_at, image_path, box, "
                         "sharpness, brightness, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (f"p-{trip}", trip, lat - south / 111_320, lon, 0.0, now(), "x.jpg", json.dumps([0, 0, 9, 9]),
                          150.0, 120.0, now()))
            repair.check_passes(conn, trip)
    d = api.get(f"/reports/{rid}", headers=rev).json()
    assert d["report"]["status_label"] == "Repaired (verified)" and d["report"]["reopen_count"] == 1
    steps = [a["action"].removeprefix("ledger_workflow_") for a in d["trail"] if a["action"].startswith("ledger_workflow_")]
    assert steps == ["approve", "assign", "repair_needed", "repaired", "reopen", "repair_needed", "repaired"]
    reopen = next(a for a in d["trail"] if a["action"] == "ledger_workflow_reopen")
    assert reopen["actor"] == "verify:repair"  # RoadSense reopened it, not the agent that triaged the sighting
    whole = api.get("/service-standards/integrity", headers=rev).json()
    mine = api.get("/service-standards/integrity", params={"report_id": rid}, headers=rev).json()
    assert whole["ok"] and mine["ok"] and mine["entries"] >= 12
    with session() as conn:
        assert ledger.verify(conn)["ok"]
        c = conn.execute("SELECT stage, reopened_count, completed_at FROM service_clocks WHERE report_id = ?",
                         (rid,)).fetchone()
    assert tuple(c)[:2] == ("closed", 1) and c[2]


# ---------------- forwarding (ROADSENSE_FORWARD_MODE) ----------------
def test_by_default_approving_never_contacts_anything(staff, monkeypatch):
    import httpx

    from roadsense.core import delivery
    from roadsense.mcp_servers import municipality_server
    from roadsense.services import jobs

    def boom(*a, **k):
        raise AssertionError("an external service was contacted")

    for target, name in ((delivery, "submit"), (httpx, "post"), (httpx, "get"), (httpx.Client, "request")):
        monkeypatch.setattr(target, name, boom)
    queued = []
    monkeypatch.setattr(agent_api.worker, "submit", lambda *a, **k: queued.append(a) or "job")
    rid = new_report()
    with session() as conn:
        conn.execute("UPDATE reports SET jurisdiction = 'Nova Scotia Public Works' WHERE id = ?", (rid,))
    r = api.post(f"/reports/{rid}/approve", json={"payload_hash": payload_hash(rid)}, headers=staff["rev"])
    assert r.status_code == 200 and r.json()["status"] == "awaiting_inspection" and "referral" not in r.json()
    assert queued == []  # not even queued
    with pytest.raises(Exception, match="forwarding to other road authorities is off"):
        municipality_server.deliver(rid)
    assert api.post(f"/reports/{rid}/resend", headers=staff["rev"]).status_code == 409
    with session() as conn:
        conn.execute("UPDATE reports SET delivery_attempts = 1, next_attempt_at = '2020-01-01T00:00:00+00:00'")
    assert "retry_deliveries" not in jobs.Worker().schedule()
    assert api.get("/system", headers=AUTH).json()["workflow"]["forwarding"] is False


def test_forwarding_refers_only_roads_another_authority_owns(staff, forwarding, monkeypatch):
    from roadsense.core import delivery
    from roadsense.mcp_servers import municipality_server

    sent = []
    monkeypatch.setattr(delivery, "submit", lambda p, r=None: sent.append(p["authority"]) or {
        "channel": "referral", "service_request_id": "REF-9", "notice": "ok"})
    queued = []
    monkeypatch.setattr(agent_api.worker, "submit", lambda kind, **k: queued.append(k["report_id"]) or "job")
    monkeypatch.setattr(agent_api.worker, "get", lambda job_id: {"id": job_id, "status": "queued"})
    own, provincial = new_report(), new_report()
    with session() as conn:
        conn.execute("UPDATE reports SET jurisdiction = 'Nova Scotia Public Works' WHERE id = ?", (provincial,))
    a = api.post(f"/reports/{own}/approve", params={"wait": False}, json={"payload_hash": payload_hash(own)},
                 headers=staff["rev"]).json()
    b = api.post(f"/reports/{provincial}/approve", params={"wait": False},
                 json={"payload_hash": payload_hash(provincial)}, headers=staff["rev"]).json()
    assert "referral" not in a and b["referral"]["status"] == "queued" and queued == [provincial]
    with pytest.raises(Exception, match="not another road authority"):
        municipality_server.deliver(own)
    assert municipality_server.deliver(provincial)["service_request_id"] == "REF-9" and sent == [
        "Nova Scotia Public Works"]
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (provincial,)).fetchone())
        clock = conn.execute("SELECT authority FROM service_clocks WHERE report_id = ?", (provincial,)).fetchone()
        own_clock = conn.execute("SELECT authority FROM service_clocks WHERE report_id = ?", (own,)).fetchone()
    assert (r["status"], r["closed_reason"]) == ("closed", "referred") and workflow.label(r) == "Closed (Referred)"
    assert clock[0] == "Nova Scotia Public Works" and own_clock[0] == HRM


def test_metrics_count_statuses_overdue_reopens_and_time_to_repair(staff):
    a, b = new_report(), new_report()
    with session() as conn:
        for rid in (a, b):
            workflow.transition(conn, rid, "approve", "rev", "reviewer", at="2026-11-02T12:00:00+00:00")
            workflow.transition(conn, rid, "assign", "rev", "reviewer", inspector_id=staff["insp_id"],
                                at="2026-11-02T13:00:00+00:00")
            workflow.transition(conn, rid, "repair_needed", "rev", "reviewer", repair_eta="2026-11-10",
                                at="2026-11-03T12:00:00+00:00")
        workflow.transition(conn, a, "repaired", "rev", "reviewer", at="2026-11-06T12:00:00+00:00")
        workflow.transition(conn, a, "reopen", "rev", "reviewer", reason="x", at="2026-11-07T12:00:00+00:00")
        workflow.transition(conn, a, "repair_needed", "rev", "reviewer", repair_eta="2026-11-09",
                            at="2026-11-07T13:00:00+00:00")
        workflow.transition(conn, a, "repaired", "rev", "reviewer", at="2026-11-08T12:00:00+00:00")
    text = api.get("/metrics", headers=AUTH).text
    assert 'roadsense_reports{status="repaired"} 1' in text and 'roadsense_reports{status="repair_needed"} 1' in text
    assert "roadsense_reports_overdue 1" in text  # b: due 10 Nov, still not repaired
    assert "roadsense_report_reopens 1" in text
    assert "roadsense_approve_to_repaired_days_median 6" in text  # a: approved 2 Nov, repaired (last) 8 Nov


# ---------------- Inspector 1, 2 and 3: the assign picker, and the Reports page sections ----------------
def test_seeded_inspectors_fill_the_picker_once_and_cannot_sign_in(db):
    from roadsense.web import auth

    assert auth.seed_inspectors() == [e for e, _ in auth.INSPECTORS]  # created before the first admin
    auth.bootstrap_admin()  # the seeded inspectors do not count as a first user
    with session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] == 1
        conn.execute("UPDATE users SET active = 0 WHERE email = 'inspector3@roadsense.local'")
    assert auth.seed_inspectors() == []  # restarts never duplicate or re-activate them
    auth._attempts.clear()  # other tests' sign-ins share the per-client rate limit
    rev, _ = signed_in()
    assert [u["name"] for u in rev.get("/api/users", params={"role": "inspector"}).json()] == ["Inspector 1",
                                                                                                "Inspector 2"]
    for email, _ in auth.INSPECTORS:
        r = TestClient(rev.app).post("/api/auth/login", json={"email": email, "password": ""})
        assert r.status_code == 401
    auth._attempts.clear()  # these deliberate failures must not rate-limit the tests after this one


def test_reviewer_records_the_outcome_for_a_seeded_inspector(staff):
    from roadsense.web import auth

    auth.seed_inspectors()
    with session() as conn:
        insp1, insp2 = (conn.execute("SELECT id FROM users WHERE email = ?", (e,)).fetchone()[0]
                        for e, _ in auth.INSPECTORS[:2])
    rev = staff["rev"]
    fix, skip = new_report(), new_report()
    for rid, insp in ((fix, insp1), (skip, insp2)):
        api.post(f"/reports/{rid}/approve", json={"payload_hash": payload_hash(rid)}, headers=rev)
        r = api.post(f"/reports/{rid}/assign", json={"inspector_id": insp}, headers=rev).json()
        assert r["status"] == "inspection_assigned" and "no_repair_needed" in r["allowed_actions"]
    assigned = api.get("/reports", params={"status": "inspection_assigned"}, headers=rev).json()
    assert {r["id"] for r in assigned} == {fix, skip}

    api.post(f"/reports/{fix}/inspection", data={"outcome": "repair_needed", "repair_eta": SOON}, headers=rev)
    api.post(f"/reports/{skip}/inspection", data={"outcome": "no_repair_needed", "notes": "Surface only"},
             headers=rev)
    assert [r["id"] for r in api.get("/reports", params={"status": "repair_needed"}, headers=rev).json()] == [fix]
    closed = api.get("/reports", params={"status": "closed"}, headers=rev).json()
    assert [(r["id"], r["status_label"], r["inspection_notes"]) for r in closed] == [
        (skip, "Closed (Repair not needed)", "Surface only")]
    assert api.post(f"/reports/{fix}/repaired", data={"notes": "patched"}, headers=rev).json()["status"] == "repaired"


def test_my_inspections_page_is_gone_and_old_links_open_the_reports_tab():
    from roadsense.web.app import STATIC

    js, html = (STATIC / "app.js").read_text(encoding="utf-8"), (STATIC / "index.html").read_text(encoding="utf-8")
    assert "renderInspections" not in js and "My inspections" not in html and 'data-route="inspections"' not in html
    assert '"#/reports?status=inspection_assigned"' in js
