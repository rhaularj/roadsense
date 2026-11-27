"""Independent repair verification: is a pothole marked repaired really gone?

The crew's claim (reports.status = 'repaired') and RoadSense's own verdict are kept apart; the verdict is
reports.verification_status:

    awaiting   marked repaired; no conclusive re-observation yet
    verified   enough clean passes from different trips show the spot without the defect
    reopened   a later trip detected the same defect again

Two kinds of observation feed it, both from trips captured after the repair (reports.closed_at = repaired_at):

    re-detection  a damage event of a compatible class within the match radius, on the same road
                  -> confident: not_verified (report reopened); weak: inconclusive
    clean pass    a frame the edge kept where it passed a watched spot, with no matching detection in that trip
                  -> only counted when the frame is sharp, lit, and shows that spot (distance and angle ahead);
                     verified once ``repair_min_clean_passes`` different trips agree, inconclusive until then

Every attempt is one row in repair_verifications (unique per report and observation, so re-processing a trip never
duplicates it) with a SHA-256 hash of its evidence, and the important steps are written to the audit log.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from ..common.config import settings
from ..common.db import audit, now, row
from ..edge.gps import bearing_deg, haversine_m
from . import service_standards, workflow

RESULTS = ("verified", "not_verified", "inconclusive")
ELIGIBLE = ("awaiting",)  # verified is final: damage seen later is a new defect and a new report
ACTOR = "verify:repair"


def lifecycle(report: dict) -> str:
    """The status label people see (core.workflow), e.g. "Repaired (verified)" or "Closed (Repair not needed)"."""
    return workflow.label(report)


def _report(conn, report_id: int) -> dict:
    return row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())


def original_observation(conn: sqlite3.Connection, report: dict) -> dict | None:
    """The detection the report was created from (its best event): photo, position, time, confidence."""
    e = row(conn.execute("SELECT id, trip_id, class_code, confidence, verified_confidence, lat, lon, captured_at "
                         "FROM events WHERE id = ?", (report.get("best_event_id"),)).fetchone())
    if e is None:
        return None
    return {"event_id": e["id"], "trip_id": e["trip_id"], "class_code": e["class_code"],
            "confidence": e["verified_confidence"] if e["verified_confidence"] is not None else e["confidence"],
            "lat": e["lat"], "lon": e["lon"], "captured_at": e["captured_at"], "image": f"event:{e['id']}"}


def _eligible(conn: sqlite3.Connection, lat: float, lon: float, radius_m: float, classes: set | None = None,
              states: tuple = ELIGIBLE) -> list[dict]:
    from .reports import find_nearby

    return [r for r in find_nearby(conn, lat, lon, classes, radius_m, statuses=("repaired",))
            if r.get("verification_status") in states]


def _same_road(report: dict, road_name: str | None) -> bool:
    """Same road segment, when both sides know the road: an intersecting street 10 m away is another surface."""
    a, b = (report.get("road_name") or "").strip().casefold(), (road_name or "").strip().casefold()
    return not (a and b and a != b)


def _after_closure(report: dict, observed_at: str | None) -> bool:
    return bool(observed_at) and (not report.get("closed_at") or str(observed_at) >= report["closed_at"])


def _record(conn: sqlite3.Connection, report: dict, kind: str, obs_id: str, trip_id: str | None,
            observed_at: str | None, distance_m: float | None, observed_class: str | None, confidence: float | None,
            result: str, reason: str, followup_image: str | None, quality: dict | None = None,
            clean: bool = False) -> dict | None:
    """Append one verification attempt. Returns it, or None when this observation was already recorded."""
    if result not in RESULTS:
        raise ValueError(f"result must be one of {RESULTS}")
    orig = original_observation(conn, report) or {}
    rec = {"report_id": report["id"], "original_event_id": orig.get("event_id"), "observation_kind": kind,
           "observation_id": obs_id, "trip_id": trip_id, "observed_at": observed_at, "verified_at": now(),
           "distance_m": None if distance_m is None else round(distance_m, 1),
           "original_class": report["class_code"], "observed_class": observed_class,
           "confidence": None if confidence is None else round(confidence, 3),
           "quality": json.dumps(quality, sort_keys=True) if quality else None, "clean": int(clean),
           "result": result, "reason": reason[:500], "original_image": orig.get("image"),
           "followup_image": followup_image}
    rec["evidence_hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()
    cols = list(rec)
    cur = conn.execute(f"INSERT OR IGNORE INTO repair_verifications ({', '.join(cols)}) "
                       f"VALUES ({', '.join('?' * len(cols))})", [rec[c] for c in cols])
    if not cur.rowcount:
        return None
    audit(conn, ACTOR, "repair_verification_started", f"report:{report['id']}",
          {"observation": obs_id, "kind": kind, "trip": trip_id})
    audit(conn, ACTOR, "repair_verification_completed", f"report:{report['id']}",
          {"observation": obs_id, "result": result, "reason": rec["reason"], "distance_m": rec["distance_m"],
           "hash": rec["evidence_hash"]})
    return rec


def _event_classes(event: dict) -> set[str]:
    return {event["class_code"], *([event["verifier_class"]] if event.get("verifier_class") else [])}


def check_redetection(conn: sqlite3.Connection, event: dict, road_name: str | None = None,
                      actor: str = ACTOR) -> dict | None:
    """Called for each real (verified) damage event before triage. When it is the defect of a repaired report, record
    the attempt, link the sighting to that report (no new duplicate report) and reopen it (core.workflow, as RoadSense
    itself, never as the agent that triaged the event) when the evidence is confident.
    Returns {"action": "reopened" | "reobserved", "report": ...}, or None to triage normally."""
    candidates = [r for r in _eligible(conn, event["lat"], event["lon"], settings.repair_match_radius_m,
                                       _event_classes(event))
                  if _same_road(r, road_name) and _after_closure(r, event.get("captured_at"))]
    if not candidates:
        return None
    r = candidates[0]  # nearest: one sighting is evidence about one defect
    conf = next((c for c in (event.get("verified_confidence"), event.get("recheck_confidence"),
                             event.get("confidence")) if c is not None), 0.0)
    threshold = settings.repair_redetect_confidence
    if conf >= threshold:
        result = "not_verified"
        reason = (f"{event['class_code']} detected again {r['distance_m']:.0f} m from the repaired spot at confidence "
                  f"{conf:.2f} (threshold {threshold:.2f}): the defect is still there")
    else:
        result = "inconclusive"
        reason = (f"a possible {event['class_code']} {r['distance_m']:.0f} m away at confidence {conf:.2f}, below "
                  f"the {threshold:.2f} needed to reopen: neither repaired nor confirmed")
    _record(conn, r, "detection", event["id"], event["trip_id"], event.get("captured_at"), r["distance_m"],
            event["class_code"], conf, result, reason, f"event:{event['id']}")
    conn.execute("UPDATE events SET report_id = ?, status = 'processed', road_name = COALESCE(?, road_name) "
                 "WHERE id = ?", (r["id"], road_name, event["id"]))
    action = "reobserved"
    if result == "not_verified":
        action = "reopened"
        audit(conn, ACTOR, "repair_not_verified", f"report:{r['id']}", {"event": event["id"], "reason": reason})
        service_standards.note_repair_check(conn, r["id"], "repair_not_verified", ACTOR, reason,
                                            f"event:{event['id']}")
        workflow.transition(conn, r["id"], "reopen", ACTOR, workflow.SYSTEM, reason=reason, event_id=event["id"])
    return {"action": action, "report": _report(conn, r["id"])}


def _view(report: dict, p: dict) -> tuple[float, float]:
    """Distance from the car to the defect and the angle between the car's heading and the defect."""
    d = haversine_m(p["lat"], p["lon"], report["lat"], report["lon"])
    if p.get("heading") is None:
        return d, 180.0
    off = abs((bearing_deg(p["lat"], p["lon"], report["lat"], report["lon"]) - p["heading"] + 180) % 360 - 180)
    return d, off


def _pass_quality(report: dict, p: dict) -> tuple[bool, str, dict]:
    d, angle = _view(report, p)
    q = {"distance_m": round(d, 1), "view_angle_deg": round(angle, 1), "sharpness": p.get("sharpness"),
         "brightness": p.get("brightness")}
    s = settings
    if d < s.repair_min_view_m:
        return False, f"the spot was {d:.0f} m away, too close to be in the frame", q
    if angle > s.repair_max_view_angle_deg:
        return False, f"the camera faced {angle:.0f}° away from the spot (limit {s.repair_max_view_angle_deg:.0f}°)", q
    if p.get("sharpness") is None or p["sharpness"] < s.repair_min_sharpness:
        return False, f"the road surface is blurred (sharpness {p.get('sharpness') or 0:.0f}, " \
                      f"need {s.repair_min_sharpness:.0f})", q
    if p.get("brightness") is None or not s.repair_min_brightness <= p["brightness"] <= s.repair_max_brightness:
        return False, f"the frame is too dark or washed out (brightness {p.get('brightness') or 0:.0f})", q
    return True, "", q


def check_passes(conn: sqlite3.Connection, trip_id: str, actor: str = ACTOR) -> dict:
    """Evaluate the clean passes a trip uploaded against every closed report they could show. Run after the trip's
    detections were triaged, so a re-detection in the same trip has already reopened its report."""
    out = {"attempts": 0, "verified": [], "inconclusive": 0}
    passes = [dict(p) for p in conn.execute("SELECT * FROM road_passes WHERE trip_id = ? AND lat IS NOT NULL "
                                            "ORDER BY captured_at", (trip_id,))]
    for p in passes:
        for r in _eligible(conn, p["lat"], p["lon"], settings.repair_max_view_m, states=("awaiting",)):
            if not _after_closure(r, p["captured_at"]):
                continue
            ok, why, q = _pass_quality(r, p)
            seen = [e for e in conn.execute("SELECT id, class_code, verifier_class, confidence, lat, lon FROM events "
                                            "WHERE trip_id = ?", (trip_id,))
                    if r["class_code"] in _event_classes(dict(e))
                    and haversine_m(e["lat"], e["lon"], r["lat"], r["lon"]) <= settings.repair_match_radius_m]
            if ok and seen:
                ok, why = False, (f"this trip also detected a possible {seen[0]['class_code']} here "
                                  f"(confidence {seen[0]['confidence']:.2f}): not a clean pass")
            image = f"pass:{p['id']}"
            if not ok:
                if _record(conn, r, "pass", p["id"], trip_id, p["captured_at"], q["distance_m"], None, None,
                           "inconclusive", why, image, q):
                    out["attempts"] += 1
                    out["inconclusive"] += 1
                continue
            # only passes after the current closure count: a reopened and re-closed request needs fresh evidence
            prior = {t for (t,) in conn.execute("SELECT DISTINCT trip_id FROM repair_verifications "
                                                "WHERE report_id = ? AND clean = 1 AND observed_at >= ?",
                                                (r["id"], r["closed_at"] or ""))}
            trips = prior | {trip_id}
            need = settings.repair_min_clean_passes
            verified = len(trips) >= need
            reason = (f"the spot was in view {q['distance_m']:.0f} m ahead with a sharp, lit frame and no "
                      f"{r['class_code']} detected; {len(trips)} of {need} independent clean passes")
            rec = _record(conn, r, "pass", p["id"], trip_id, p["captured_at"], q["distance_m"], None, None,
                          "verified" if verified else "inconclusive",
                          reason + (": repair verified" if verified else ": one miss is not proof yet"), image, q,
                          clean=True)
            if rec is None:
                continue
            out["attempts"] += 1
            if verified:
                conn.execute("UPDATE reports SET verification_status = 'verified', verification_updated_at = ? "
                             "WHERE id = ?", (now(), r["id"]))
                audit(conn, actor, "repair_verified", f"report:{r['id']}",
                      {"trips": sorted(trips), "reason": rec["reason"], "hash": rec["evidence_hash"]})
                service_standards.note_repair_check(conn, r["id"], "repair_verified", actor, rec["reason"],
                                                    f"sha256:{rec['evidence_hash']}")
                # verified is final: the clock closes (the crew's repair_completed date stays the measured one)
                service_standards.record_event(conn, r["id"], "report_closed", actor, "roadsense:repair_verification",
                                               note="repair independently verified")
                out["verified"].append(r["id"])
            else:
                out["inconclusive"] += 1
    return out


def history(conn: sqlite3.Connection, report_id: int) -> list[dict]:
    return [dict(v) for v in conn.execute("SELECT * FROM repair_verifications WHERE report_id = ? ORDER BY id",
                                          (report_id,))]


def _image_ref_details(conn: sqlite3.Connection, ref: str | None) -> dict | None:
    if not ref:
        return None
    kind, _, oid = ref.partition(":")
    if kind == "event":
        e = conn.execute("SELECT lat, lon, captured_at FROM events WHERE id = ?", (oid,)).fetchone()
    else:
        e = conn.execute("SELECT lat, lon, captured_at FROM road_passes WHERE id = ?", (oid,)).fetchone()
    return {"image": ref, **(dict(e) if e else {})}


def summary(conn: sqlite3.Connection, report: dict) -> dict | None:
    """What the report page shows: original vs latest follow-up, the current result, why, and the history."""
    if not report.get("verification_status"):
        return None
    hist = history(conn, report["id"])
    latest = hist[-1] if hist else None
    follow = _image_ref_details(conn, latest["followup_image"]) if latest else None
    reason = report.get("reopen_reason") if report["verification_status"] == "reopened" else (
        latest["reason"] if latest else "marked repaired; no trip has passed the spot since")
    return {"state": report["verification_status"], "lifecycle": lifecycle(report),
            "report_status": report["status"], "closed_at": report.get("closed_at"),
            "reopened_at": report.get("reopened_at"), "reason": reason,
            "original": original_observation(conn, report), "latest": latest and {
                **{k: latest[k] for k in ("observation_kind", "observation_id", "observed_at", "distance_m",
                                          "observed_class", "confidence", "result", "reason")},
                "image": latest["followup_image"], "lat": (follow or {}).get("lat"), "lon": (follow or {}).get("lon")},
            "history": hist}


def metrics(conn: sqlite3.Connection) -> dict:
    """Repair Verification Rate = verified / reports with a conclusive re-observation (verified + reopened) × 100.
    Closed reports nobody has re-observed, and those with only inconclusive passes, are counted separately and
    never in the denominator: not having driven past a repair is not a failed repair."""
    by = dict(conn.execute("SELECT verification_status, COUNT(*) FROM reports WHERE verification_status IS NOT NULL "
                           "GROUP BY 1").fetchall())
    observed = {r for (r,) in conn.execute("SELECT DISTINCT report_id FROM repair_verifications")}
    awaiting_ids = [r for (r,) in conn.execute("SELECT id FROM reports WHERE verification_status = 'awaiting'")]
    attempts = dict(conn.execute("SELECT result, COUNT(*) FROM repair_verifications GROUP BY 1").fetchall())
    verified, reopened = by.get("verified", 0), by.get("reopened", 0)
    decided = verified + reopened
    return {
        "marked_repaired": sum(by.values()),
        "awaiting_verification": by.get("awaiting", 0),
        "not_yet_reobserved": sum(r not in observed for r in awaiting_ids),
        "awaiting_inconclusive": sum(r in observed for r in awaiting_ids),
        "verified": verified, "not_verified": reopened, "reopened": reopened,
        "eligible": decided,
        "verification_rate": round(100 * verified / decided, 1) if decided else None,
        "attempts": {k: attempts.get(k, 0) for k in RESULTS},
        "inconclusive_verifications": attempts.get("inconclusive", 0),
    }


def watchlist(conn: sqlite3.Connection) -> list[dict]:
    """Repaired reports the edge should look at when it passes them: position and class only."""
    return [dict(r) for r in conn.execute("SELECT id AS report_id, lat, lon, class_code FROM reports "
                                          "WHERE status = 'repaired' AND verification_status = 'awaiting'")]
