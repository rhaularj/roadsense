"""Report rules the agents call through MCP: verdicts, severity, priority and duplicate merging.

These are plain functions on purpose. The LLM decides *when* to call them and explains the result, but thresholds,
deduplication and state changes are deterministic and testable.
"""
from __future__ import annotations

import math
import sqlite3

from ..common.db import audit, now, row
from ..edge.gps import haversine_m
from .verify import RECHECK_EDGE_CONF

SEVERITY_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 3.0}
CLASS_WEIGHT = {"D40": 1.5, "D20": 1.2, "D00": 1.0, "D10": 1.0}  # potholes damage cars; alligator cracks become potholes
OPEN_STATUSES = ("pending_approval", "approved", "submitted")
VERDICTS = ("confirmed", "disputed", "rejected")
HRM_P1_WIDTH_M = 0.25  # HRM Priority 1: at least 25 cm wide and 8 cm deep (depth is not measurable from video)


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


def estimate_severity(class_code: str, box_area_ratio: float, confidence: float, frames_seen: int,
                      width_m: float | None = None) -> dict:
    """Severity from what the camera saw. Potholes use estimated width against HRM's Priority 1 threshold when the
    camera geometry gave one; otherwise the box area at the best frame is the size proxy."""
    p1 = False
    if class_code == "D40" and width_m is not None:
        p1 = width_m >= HRM_P1_WIDTH_M
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
    if confidence < 0.35 and level == "high":
        level = "medium"
    reason = (f"{class_code} {size}, confidence {confidence:.2f}, seen in {frames_seen} frames"
              + ("; meets HRM Priority 1 width (depth unverified)" if p1 else ""))
    return {"severity": level, "p1_candidate": p1, "width_m": width_m, "reason": reason}


def priority(severity: str, class_code: str, confirmations: int) -> float:
    return round(SEVERITY_WEIGHT[severity] * CLASS_WEIGHT.get(class_code, 1.0) * (1 + math.log(max(confirmations, 1))), 2)


def find_nearby(conn: sqlite3.Connection, lat: float, lon: float, class_code: str | None, radius_m: float) -> list[dict]:
    # coarse bounding box in SQL, exact distance in Python
    dlat = radius_m / 111_000
    dlon = radius_m / (111_000 * max(math.cos(math.radians(lat)), 0.01))
    sql = (f"SELECT * FROM reports WHERE status IN ({','.join('?' * len(OPEN_STATUSES))}) "
           "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?")
    args = [*OPEN_STATUSES, lat - dlat, lat + dlat, lon - dlon, lon + dlon]
    if class_code:
        sql += " AND class_code = ?"
        args.append(class_code)
    out = []
    for r in conn.execute(sql, args):
        d = haversine_m(lat, lon, r["lat"], r["lon"])
        if d <= radius_m:
            out.append({**dict(r), "distance_m": round(d, 1)})
    return sorted(out, key=lambda r: r["distance_m"])


def create_or_merge(conn: sqlite3.Connection, event_id: str, severity: str, address: str | None,
                    municipality: str | None, radius_m: float, actor: str = "triage", jurisdiction: str | None = None,
                    rationale: str | None = None, p1_candidate: bool = False) -> dict:
    event = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    if event is None:
        raise ValueError(f"unknown event {event_id}")
    if event["status"] == "rejected":
        raise ValueError(f"event {event_id} was rejected by verification and cannot become a report")
    if event["status"] not in ("verified", "processed"):
        raise ValueError(f"event {event_id} has no verdict yet (status {event['status']})")
    if event["report_id"]:
        existing = row(conn.execute("SELECT * FROM reports WHERE id = ?", (event["report_id"],)).fetchone())
        return {"action": "already_linked", "report": existing}
    if severity not in SEVERITY_WEIGHT:
        raise ValueError("severity must be low, medium or high")

    nearby = find_nearby(conn, event["lat"], event["lon"], event["class_code"], radius_m)
    ts = now()
    if nearby:
        r = nearby[0]
        # a confirmation is an independent pass: several sightings in the same trip count once
        trips = {t for (t,) in conn.execute("SELECT DISTINCT trip_id FROM events WHERE report_id = ?", (r["id"],))}
        confirmations = len(trips | {event["trip_id"]})
        sev = max(r["severity"], severity, key=SEVERITY_WEIGHT.get)
        conn.execute("UPDATE reports SET confirmations = ?, severity = ?, priority = ?, updated_at = ?, "
                     "p1_candidate = MAX(p1_candidate, ?), class_disputed = MAX(class_disputed, ?) WHERE id = ?",
                     (confirmations, sev, priority(sev, r["class_code"], confirmations), ts, int(p1_candidate),
                      event["class_disputed"], r["id"]))
        report_id, action = r["id"], "merged"
    else:
        cur = conn.execute(
            "INSERT INTO reports (trip_id, class_code, class_name, lat, lon, address, municipality, jurisdiction,"
            " severity, priority, best_event_id, width_m, p1_candidate, class_disputed, rationale, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event["trip_id"], event["class_code"], event["class_name"], event["lat"], event["lon"], address,
             municipality, jurisdiction or municipality, severity, priority(severity, event["class_code"], 1),
             event_id, event["width_m"], int(p1_candidate), event["class_disputed"], (rationale or "")[:500], ts, ts))
        report_id, action = cur.lastrowid, "created"
    conn.execute("UPDATE events SET report_id = ?, status = 'processed' WHERE id = ?", (report_id, event_id))
    audit(conn, actor, f"report_{action}", f"report:{report_id}",
          {"event": event_id, "distance_m": nearby[0]["distance_m"] if nearby else None, "rationale": rationale})
    report = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    return {"action": action, "report": report}


def set_status(conn: sqlite3.Connection, report_id: int, status: str, actor: str, **fields) -> dict:
    allowed = {"service_request_id", "description", "channel", "approved_payload_hash", "submitted_payload_hash",
               "draft_description"}
    sets = ["status = ?", "updated_at = ?"] + [f"{k} = ?" for k in fields if k in allowed]
    conn.execute(f"UPDATE reports SET {', '.join(sets)} WHERE id = ?",
                 [status, now(), *[v for k, v in fields.items() if k in allowed], report_id])
    audit(conn, actor, f"status_{status}", f"report:{report_id}", {k: v for k, v in fields.items() if k in allowed}
          or None)
    return row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
