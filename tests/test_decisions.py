"""The rules behind the agents' decisions: verdict guard, jurisdiction routing, approval lock, audit integrity."""
import sqlite3

import pytest
from conftest import add_event
from mcp.server.fastmcp.exceptions import ToolError

from roadsense.agents.contracts import VisionResult, validate
from roadsense.common.db import audit, session
from roadsense.core import geo, open311, reports
from roadsense.edge.camera import Camera, offset_position
from roadsense.edge.gps import haversine_m
from roadsense.mcp_servers import municipality_server, reports_server


def set_evidence(event_id, verified=None, verifier_class=None, recheck=None, status="checked"):
    with session() as conn:
        conn.execute("UPDATE events SET verified_confidence = ?, verifier_class = ?, recheck_confidence = ?, "
                     "status = ? WHERE id = ?", (verified, verifier_class, recheck, status, event_id))


def test_suggested_verdicts():
    base = {"class_code": "D40", "confidence": 0.7, "frames_seen": 6, "verified_confidence": None,
            "verifier_class": None, "recheck_confidence": None}
    assert reports.suggested_verdict({**base, "verified_confidence": 0.8, "verifier_class": "D40"})[0] == "confirmed"
    assert reports.suggested_verdict({**base, "verified_confidence": 0.8, "verifier_class": "D20"})[0] == "disputed"
    assert reports.suggested_verdict(base)[0] == "recheck"
    assert reports.suggested_verdict({**base, "confidence": 0.3})[0] == "rejected"


def test_verdict_needs_verifier_evidence(db):
    add_event("ev-a", 44.64, -63.58, status="checked")
    with session() as conn, pytest.raises(ValueError, match="verifier evidence"):
        reports.record_verdict(conn, "ev-a", "confirmed", "looks like a pothole to me", "agent:vision")
    set_evidence("ev-a", verified=0.7, verifier_class="D40")
    with session() as conn:
        with pytest.raises(ValueError, match="different damage class"):
            reports.record_verdict(conn, "ev-a", "disputed", "x", "agent:vision")
        assert reports.record_verdict(conn, "ev-a", "confirmed", "verifier agrees", "agent:vision")["status"] == \
            "verified"


def test_disputed_keeps_edge_label_and_flags_report(db):
    add_event("ev-d", 44.64, -63.58, code="D00", status="checked")
    set_evidence("ev-d", verified=0.86, verifier_class="D20")
    with session() as conn:
        reports.record_verdict(conn, "ev-d", "disputed", "models disagree", "agent:vision")
        r = reports.create_or_merge(conn, "ev-d", "low", "x", "Halifax Regional Municipality", 15)["report"]
    assert r["class_code"] == "D00" and r["class_disputed"] == 1


def test_jurisdiction_routing(db):
    with session() as conn:
        highway = geo.jurisdiction_candidates(geo.reverse_geocode(conn, 44.6800, -63.6797))  # on Highway 102
        numbered = geo.jurisdiction_candidates(geo.reverse_geocode(conn, 44.6800, -63.6451))  # Bedford Highway
        street = geo.jurisdiction_candidates(geo.reverse_geocode(conn, 44.6430, -63.5800))
    assert highway[0]["authority"] == geo.PROVINCIAL and highway[0]["confidence"] == "high"
    assert {c["confidence"] for c in numbered} == {"medium"} and len(numbered) == 2  # ambiguous: agent decides
    assert street[0]["authority"] == "Halifax Regional Municipality" and len(street) == 1
    assert open311.service_info(geo.PROVINCIAL)["channel"] == "referral"


def test_camera_projects_detection_ahead_of_the_car():
    cam = Camera(height_m=1.3, pitch_deg=3.0, hfov_deg=110)
    near = cam.ground([600, 600, 680, 650], 1280, 720)
    far = cam.ground([620, 420, 660, 440], 1280, 720)
    assert 1 < near["forward_m"] < far["forward_m"] <= 40
    assert cam.ground([600, 100, 680, 150], 1280, 720) is None  # above the horizon
    lat, lon = offset_position(44.64, -63.58, 90.0, near["forward_m"], 0.0)  # heading east
    assert haversine_m(44.64, -63.58, lat, lon) == pytest.approx(near["forward_m"], rel=0.01) and lon > -63.58


def test_width_drives_hrm_priority_1():
    assert reports.estimate_severity("D40", 0.01, 0.8, 5, width_m=0.30)["p1_candidate"] is True
    assert reports.estimate_severity("D40", 0.01, 0.8, 5, width_m=0.15)["severity"] == "medium"


def approved_report(event_id="ev-p"):
    add_event(event_id, 44.643, -63.58)
    with session() as conn:
        r = reports.create_or_merge(conn, event_id, "high", "x", "Halifax Regional Municipality", 15,
                                    jurisdiction="Halifax Regional Municipality")["report"]
        digest = open311.payload_hash(open311.build_payload(r))
        reports.set_status(conn, r["id"], "approved", "driver", approved_payload_hash=digest)
    return r["id"]


def test_unapproved_reports_cannot_be_sent(db):
    add_event("ev-u", 44.643, -63.58)
    with session() as conn:
        rid = reports.create_or_merge(conn, "ev-u", "high", "x", "Halifax Regional Municipality", 15)["report"]["id"]
    with pytest.raises(ToolError, match="only reviewer-approved"):
        municipality_server.submit_request(rid)


def test_payload_is_locked_after_approval(db):
    rid = approved_report()
    with session() as conn:  # something changes the description after the driver approved
        conn.execute("UPDATE reports SET draft_description = 'different text that was never approved' WHERE id = ?",
                     (rid,))
    with pytest.raises(ToolError, match="changed after the reviewer approved"):
        municipality_server.submit_request(rid)


def test_model_text_is_sanitised(db):
    add_event("ev-s", 44.643, -63.58)
    with session() as conn:
        rid = reports.create_or_merge(conn, "ev-s", "high", "x", "Halifax Regional Municipality", 15)["report"]["id"]
    out = reports_server.save_draft(rid, "Pothole on Spring Garden Rd <script>x</script> see http://evil.example now "
                                    "about 30 cm wide.")
    assert "http" not in out["description"] and "<" not in out["description"]


def test_audit_log_is_append_only(db):
    with session() as conn:
        audit(conn, "test", "something", None, None)
    with session() as conn, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM audit")


def test_agent_output_contract():
    ok, err = validate(VisionResult, 'Done. ```json\n{"events": [{"event_id": "e1", "verdict": "confirmed", '
                                      '"severity": "high", "rationale": "verifier agrees"}]}\n```')
    assert ok is not None and err is None
    bad, err = validate(VisionResult, '{"events": [{"event_id": "e1", "verdict": "probably", "rationale": "x"}]}')
    assert bad is None and "verdict" in err
