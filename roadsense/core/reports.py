"""Report rules the agents call through MCP: verdicts, severity, priority and duplicate merging.

These are plain functions on purpose. The LLM decides *when* to call them and explains the result, but thresholds,
deduplication and state changes are deterministic and testable.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta, timezone

from ..common.db import audit, now, row
from ..edge.gps import haversine_m
from .verify import RECHECK_EDGE_CONF

SEVERITY_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 3.0}
CLASS_WEIGHT = {"D40": 1.5, "D20": 1.2, "D00": 1.0, "D10": 1.0}  # potholes damage cars; alligator cracks become potholes
CLASS_NAMES = {"D00": "Longitudinal crack", "D10": "Transverse crack", "D20": "Alligator crack", "D40": "Pothole"}
OPEN_STATUSES = ("pending_approval", "approved", "submitted", "delivery_failed")
VERDICTS = ("confirmed", "disputed", "rejected")
HRM_P1_WIDTH_M = 0.25  # HRM Priority 1: at least 25 cm wide and 8 cm deep (depth is not measurable from video)
JOLT_P1_G = 0.6        # a vertical jolt this strong from the phone/dashcam IMU corroborates a deep pothole


def _rules() -> dict:
    from .open311 import rules  # late import: open311 imports media, which imports settings only

    return rules()


def suggested_verdict(event: dict) -> tuple[str, str]:
    """The rule the deterministic fallback applies, and the agent's baseline: (verdict, reason)."""
    v, r = event.get("verified_confidence"), event.get("recheck_confidence")
    if v is not None:
        if event.get("verifier_class") and event["verifier_class"] != event["class_code"]:
            return "disputed", (f"RT-DETR-L sees {event['verifier_class']} where YOLOv8m saw {event['class_code']}; "
                                "damage is real, class needs a human look")
        return "confirmed", f"RT-DETR-L confirms {event['class_code']} at confidence {v:.2f}"
    if r is not None:
        return "confirmed", f"close-up re-check found damage at confidence {r:.2f}"
    if event["confidence"] >= RECHECK_EDGE_CONF:
        return "recheck", "confident edge detection but no full-frame verifier support: re-check the close-up"
    return "rejected", (f"no verifier support and weak edge evidence (confidence {event['confidence']:.2f}, "
                        f"{event['frames_seen']} frames)")


def record_verdict(conn: sqlite3.Connection, event_id: str, verdict: str, rationale: str, actor: str) -> dict:
    """Guarded state change: damage can only be confirmed or disputed with evidence from the verifier model."""
    event = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    if event is None:
        raise ValueError(f"unknown event {event_id}")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    if event["status"] not in ("received", "checked"):
        raise ValueError(f"event already decided ({event['status']})")
    evidence = event["verified_confidence"] is not None or event["recheck_confidence"] is not None
    if verdict in ("confirmed", "disputed") and not evidence:
        raise ValueError("cannot confirm without verifier evidence: call detector_verify or detector_recheck first")
    if verdict == "disputed" and not (event["verifier_class"] and event["verifier_class"] != event["class_code"]):
        raise ValueError("disputed requires the verifier to report a different damage class")
    conn.execute("UPDATE events SET status = ?, class_disputed = ?, rationale = ? WHERE id = ?",
                 ("rejected" if verdict == "rejected" else "verified", int(verdict == "disputed"), rationale[:500],
                  event_id))
    audit(conn, actor, f"verdict_{verdict}", f"event:{event_id}", rationale[:500])
    return {"event_id": event_id, "verdict": verdict, "status": "rejected" if verdict == "rejected" else "verified"}


def severity_band(class_code: str, width_m: float | None, box_area_ratio: float, jolt_g: float | None = None) -> str:
    """S1 (minor) .. S4 (urgent). A band, not a measurement: width comes from an uncalibrated flat-road model and depth
    is never measured, so an IMU jolt can raise a pothole one band but nothing lowers a band below the width rule."""
    bands = _rules().get("severity_bands", {})
    if class_code == "D40" and width_m is not None:
        table, value = bands.get("D40", [[0.10, "S1"], [0.25, "S2"], [0.50, "S3"], [99, "S4"]]), width_m
    else:
        table, value = bands.get("area", [[0.01, "S1"], [0.03, "S2"], [0.06, "S3"], [1, "S4"]]), box_area_ratio
    band = next((b for limit, b in table if value < limit), table[-1][1])
    if class_code == "D40" and jolt_g is not None and jolt_g >= JOLT_P1_G and band != "S4":
        band = f"S{int(band[1]) + 1}"
    if class_code in ("D00", "D10") and band in ("S3", "S4"):
        band = "S2"  # a line crack is a maintenance item, never urgent on its own
    return band


def repair_target_days(band: str, road_class: str | None) -> int | None:
    """Repair target by band and road class from the regional rules (O. Reg. 239/02-style table)."""
    table = _rules().get("repair_target_days", {}).get(band)
    if not table:
        return None
    return table.get(road_class or "", table.get("default"))


def estimate_severity(class_code: str, box_area_ratio: float, confidence: float, frames_seen: int,
                      width_m: float | None = None, jolt_g: float | None = None) -> dict:
    """Severity from what the camera saw. Potholes use estimated width against HRM's Priority 1 threshold when the
    camera geometry gave one; otherwise the box area at the best frame is the size proxy."""
    p1_width = _rules().get("p1_width_m", HRM_P1_WIDTH_M)
    p1 = False
    if class_code == "D40" and width_m is not None:
        p1 = width_m >= p1_width
        level = "high" if p1 else ("medium" if width_m >= 0.10 else "low")
        size = f"about {width_m * 100:.0f} cm wide"
    elif class_code == "D40":
        level = "high" if box_area_ratio >= 0.02 else "medium"
        size = f"covering {box_area_ratio:.1%} of the frame"
    elif class_code == "D20":
        level = "medium" if box_area_ratio >= 0.03 else "low"
        size = f"covering {box_area_ratio:.1%} of the frame"
    else:
        level = "medium" if box_area_ratio >= 0.06 else "low"
        size = f"covering {box_area_ratio:.1%} of the frame"
    if class_code == "D40" and jolt_g is not None and jolt_g >= JOLT_P1_G and level != "high":
        level = "high"
        size += f", {jolt_g:.1f} g jolt"
    if confidence < 0.35 and level == "high":
        level = "medium"
    band = severity_band(class_code, width_m, box_area_ratio, jolt_g)
    reason = (f"{class_code} {size}, confidence {confidence:.2f}, seen in {frames_seen} frames"
              + ("; meets HRM Priority 1 width (depth unverified)" if p1 else ""))
    return {"severity": level, "p1_candidate": p1, "width_m": width_m, "band": band, "reason": reason}


def priority(severity: str, class_code: str, confirmations: int) -> float:
    return round(SEVERITY_WEIGHT[severity] * CLASS_WEIGHT.get(class_code, 1.0) * (1 + math.log(max(confirmations, 1))), 2)


def find_nearby(conn: sqlite3.Connection, lat: float, lon: float, class_code: str | set | list | None, radius_m: float,
                statuses: tuple = OPEN_STATUSES) -> list[dict]:
    # coarse bounding box in SQL, exact distance in Python
    dlat = radius_m / 111_000
    dlon = radius_m / (111_000 * max(math.cos(math.radians(lat)), 0.01))
    sql = (f"SELECT * FROM reports WHERE status IN ({','.join('?' * len(statuses))}) "
           "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?")
    args = [*statuses, lat - dlat, lat + dlat, lon - dlon, lon + dlon]
    if class_code:
        codes = [class_code] if isinstance(class_code, str) else sorted(set(class_code))
        sql += f" AND class_code IN ({','.join('?' * len(codes))})"
        args.extend(codes)
    out = []
    for r in conn.execute(sql, args):
        d = haversine_m(lat, lon, r["lat"], r["lon"])
        if d <= radius_m:
            out.append({**dict(r), "distance_m": round(d, 1)})
    return sorted(out, key=lambda r: r["distance_m"])


def _event_classes(event: dict) -> set[str]:
    """Classes this sighting may legitimately match: what the edge saw and, when the verifier disagrees, what the
    verifier saw. One pothole seen as D40 by one model and D20 by the other is still one defect."""
    return {event["class_code"], *([event["verifier_class"]] if event.get("verifier_class") else [])}


def _recently_rejected(conn: sqlite3.Connection, event: dict, radius_m: float, days: int) -> dict | None:
    if days <= 0:
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    for r in find_nearby(conn, event["lat"], event["lon"], _event_classes(event), radius_m, statuses=("rejected",)):
        if r["updated_at"] >= cutoff:
            return r
    return None


def link_external(conn: sqlite3.Connection, report: dict, radius_m: float) -> dict | None:
    """Match a report to an open request the city (or a third-party feed) already has at that spot."""
    dlat = radius_m / 111_000
    dlon = radius_m / (111_000 * max(math.cos(math.radians(report["lat"])), 0.01))
    best = None
    for x in conn.execute("SELECT * FROM external_requests WHERE (status IS NULL OR status != 'closed') AND "
                          "lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                          (report["lat"] - dlat, report["lat"] + dlat, report["lon"] - dlon, report["lon"] + dlon)):
        d = haversine_m(report["lat"], report["lon"], x["lat"], x["lon"])
        if d <= radius_m and (best is None or d < best[0]):
            best = (d, dict(x))
    if best is None:
        return None
    x = best[1]
    n = conn.execute("SELECT COUNT(*) FROM external_requests WHERE report_id = ?", (report["id"],)).fetchone()[0]
    conn.execute("UPDATE external_requests SET report_id = ? WHERE id = ?", (report["id"], x["id"]))
    ref = x["id"] if x["source"].startswith("city") else report.get("external_ref")
    conn.execute("UPDATE reports SET external_ref = COALESCE(?, external_ref), corroborations = ? WHERE id = ?",
                 (ref, n + 1, report["id"]))
    audit(conn, "dedupe", "external_match", f"report:{report['id']}",
          {"external": x["id"], "source": x["source"], "distance_m": round(best[0], 1)})
    return x


def create_or_merge(conn: sqlite3.Connection, event_id: str, severity: str, address: str | None,
                    municipality: str | None, radius_m: float, actor: str = "triage", jurisdiction: str | None = None,
                    rationale: str | None = None, p1_candidate: bool = False, band: str | None = None,
                    road_class: str | None = None, road_name: str | None = None,
                    suppress_days: int | None = None) -> dict:
    from ..common.config import settings

    event = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    if event is None:
        raise ValueError(f"unknown event {event_id}")
    if event["status"] == "rejected":
        raise ValueError(f"event {event_id} was rejected by verification and cannot become a report")
    if event["status"] not in ("verified", "processed"):
        raise ValueError(f"event {event_id} has no verdict yet (status {event['status']})")
    if event["report_id"]:
        existing = row(conn.execute("SELECT * FROM reports WHERE id = ?", (event["report_id"],)).fetchone())
        return {"action": "suppressed" if event.get("suppressed_by") else "already_linked", "report": existing}
    if severity not in SEVERITY_WEIGHT:
        raise ValueError("severity must be low, medium or high")
    ts = now()

    # a defect a reviewer rejected is not proposed again on every trip: the sighting is recorded against it
    rejected = _recently_rejected(conn, event, radius_m,
                                  settings.rejected_suppress_days if suppress_days is None else suppress_days)
    if rejected:
        conn.execute("UPDATE events SET report_id = ?, suppressed_by = ?, status = 'processed' WHERE id = ?",
                     (rejected["id"], rejected["id"], event_id))
        audit(conn, actor, "report_suppressed", f"report:{rejected['id']}",
              {"event": event_id, "distance_m": rejected["distance_m"], "reason": "near a report a reviewer rejected"})
        return {"action": "suppressed", "report": row(conn.execute("SELECT * FROM reports WHERE id = ?",
                                                                   (rejected["id"],)).fetchone())}

    nearby = find_nearby(conn, event["lat"], event["lon"], _event_classes(event), radius_m)
    if nearby:
        r = nearby[0]
        # a confirmation is an independent pass: several sightings in the same trip count once
        trips = {t for (t,) in conn.execute("SELECT DISTINCT trip_id FROM events WHERE report_id = ?", (r["id"],))}
        confirmations = len(trips | {event["trip_id"]})
        sev = max(r["severity"], severity, key=SEVERITY_WEIGHT.get)
        new_band = max(filter(None, [r.get("severity_band"), band]), default=None)
        # after approval the payload is frozen; new evidence is pushed as an update once the request is filed
        needs_update = r["status"] in ("approved", "submitted", "delivery_failed") and (
            confirmations != r["confirmations"] or sev != r["severity"])
        conn.execute("UPDATE reports SET confirmations = ?, severity = ?, priority = ?, updated_at = ?, "
                     "p1_candidate = MAX(p1_candidate, ?), class_disputed = MAX(class_disputed, ?), "
                     "severity_band = COALESCE(?, severity_band), "
                     "repair_target_days = COALESCE(?, repair_target_days), "
                     "pending_update = MAX(pending_update, ?) WHERE id = ?",
                     (confirmations, sev, priority(sev, r["class_code"], confirmations), ts, int(p1_candidate),
                      event["class_disputed"], new_band,
                      repair_target_days(new_band, r.get("road_class")) if new_band else None, int(needs_update),
                      r["id"]))
        report_id, action = r["id"], "merged"
    else:
        cur = conn.execute(
            "INSERT INTO reports (trip_id, class_code, class_name, lat, lon, address, municipality, jurisdiction,"
            " severity, priority, best_event_id, width_m, p1_candidate, class_disputed, rationale, severity_band,"
            " repair_target_days, road_class, road_name, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event["trip_id"], event["class_code"], event["class_name"], event["lat"], event["lon"], address,
             municipality, jurisdiction or municipality, severity, priority(severity, event["class_code"], 1),
             event_id, event["width_m"], int(p1_candidate), event["class_disputed"], (rationale or "")[:500], band,
             repair_target_days(band, road_class) if band else None, road_class, road_name, ts, ts))
        report_id, action = cur.lastrowid, "created"
    conn.execute("UPDATE events SET report_id = ?, status = 'processed', road_class = COALESCE(?, road_class), "
                 "road_name = COALESCE(?, road_name) WHERE id = ?", (report_id, road_class, road_name, event_id))
    audit(conn, actor, f"report_{action}", f"report:{report_id}",
          {"event": event_id, "distance_m": nearby[0]["distance_m"] if nearby else None, "rationale": rationale})
    report = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    if action == "created":
        link_external(conn, report, radius_m)
        report = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    return {"action": action, "report": report}


STATUS_FIELDS = {"service_request_id", "description", "channel", "approved_payload_hash", "submitted_payload_hash",
                 "draft_description", "approved_payload", "approved_by", "approved_at", "rejected_by",
                 "delivery_attempts", "last_error", "next_attempt_at", "pending_update", "external_ref"}
AUDIT_SKIP = {"approved_payload"}  # stored on the report; the hash is enough in the audit line


def set_status(conn: sqlite3.Connection, report_id: int, status: str, actor: str, **fields) -> dict:
    sets = ["status = ?", "updated_at = ?"] + [f"{k} = ?" for k in fields if k in STATUS_FIELDS]
    conn.execute(f"UPDATE reports SET {', '.join(sets)} WHERE id = ?",
                 [status, now(), *[v for k, v in fields.items() if k in STATUS_FIELDS], report_id])
    audit(conn, actor, f"status_{status}", f"report:{report_id}",
          {k: v for k, v in fields.items() if k in STATUS_FIELDS and k not in AUDIT_SKIP} or None)
    return row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())


def record_label(conn: sqlite3.Connection, report_id: int, label: str, actor: str, class_code: str | None = None):
    """Ground truth from reviewer decisions: every approve / reject / class correction labels the report's events."""
    ts = now()
    for (event_id,) in conn.execute("SELECT id FROM events WHERE report_id = ? AND suppressed_by IS NULL",
                                    (report_id,)).fetchall():
        conn.execute("INSERT INTO labels (event_id, report_id, label, class_code, actor, ts) VALUES (?,?,?,?,?,?)",
                     (event_id, report_id, label, class_code, actor, ts))


def reclassify(conn: sqlite3.Connection, report_id: int, class_code: str, actor: str) -> dict:
    """A reviewer settles a class dispute before approving. Only while the report awaits approval."""
    r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    if r is None:
        raise ValueError(f"unknown report {report_id}")
    if r["status"] != "pending_approval":
        raise ValueError("the class can only change before the report is approved")
    if class_code not in CLASS_NAMES:
        raise ValueError(f"class must be one of {sorted(CLASS_NAMES)}")
    conn.execute("UPDATE reports SET class_code = ?, class_name = ?, class_disputed = 0, draft_description = NULL, "
                 "priority = ?, updated_at = ? WHERE id = ?",
                 (class_code, CLASS_NAMES[class_code], priority(r["severity"], class_code, r["confirmations"]), now(),
                  report_id))
    record_label(conn, report_id, "reclassified", actor, class_code)
    audit(conn, actor, "report_reclassified", f"report:{report_id}", {"from": r["class_code"], "to": class_code})
    return row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
