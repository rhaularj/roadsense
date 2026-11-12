"""MCP server (Vision): second-opinion verification with the most accurate model, close-up re-check, severity,
and the guarded verdict that decides whether a detection may become a report."""
from __future__ import annotations

import json
from functools import lru_cache

import cv2
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..common.config import settings
from ..common.db import audit, row, session
from ..common.detectors import Detector
from ..core import reports
from ..core import verify as checks

mcp = FastMCP("roadsense-detector")
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@lru_cache(maxsize=1)
def verifier() -> Detector:
    try:
        return Detector(settings.weights_dir / settings.verify_weights, settings.device)
    except FileNotFoundError:  # fall back to the edge model so the pipeline still runs
        return Detector(settings.weights_dir / settings.edge_weights, settings.device)


def _event(conn, event_id: str) -> dict:
    event = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    if event is None:
        raise ToolError(f"unknown event {event_id}")
    return event


def _frame(event: dict):
    frame = cv2.imread(event["image_path"])
    if frame is None:
        raise ToolError("event image missing")
    return frame


@mcp.tool(name="detector_verify", annotations=WRITE)
def verify(event_id: str) -> dict:
    """Re-run the most accurate detector (RT-DETR-L) on the event frame. Records the evidence (not the verdict) and
    returns whether the verifier sees damage at the same place, its class, and the rule-based suggested verdict."""
    with session() as conn:
        event = _event(conn, event_id)
        det = verifier()
        best = checks.verify(det, _frame(event), json.loads(event["box"]))
        conn.execute("UPDATE events SET status = CASE WHEN status = 'received' THEN 'checked' ELSE status END, "
                     "verified_confidence = ?, verifier_class = ? WHERE id = ?",
                     (best[0]["confidence"] if best else None, best[0]["code"] if best else None, event_id))
        event = _event(conn, event_id)
        verdict, reason = reports.suggested_verdict(event)
        result = {"event_id": event_id, "verifier": det.label, "edge_class": event["class_code"],
                  "edge_confidence": event["confidence"], "frames_seen": event["frames_seen"],
                  "verifier_sees_damage": best is not None, "suggested_verdict": verdict, "reason": reason}
        if best:
            d, iou = best
            result.update(verifier_class=d["code"], verifier_confidence=d["confidence"], iou=round(iou, 2),
                          class_agrees=d["code"] == event["class_code"])
        audit(conn, "mcp:detector", "verify", f"event:{event_id}", result)
    return result


@mcp.tool(name="detector_recheck", annotations=WRITE)
def recheck(event_id: str) -> dict:
    """Zoom in: run the verifier on an enlarged crop around the detection, which helps with small or distant damage
    the full-frame check missed. Use when detector_verify found nothing but the edge evidence is strong."""
    with session() as conn:
        event = _event(conn, event_id)
        best = checks.recheck(verifier(), _frame(event), json.loads(event["box"]))
        conn.execute("UPDATE events SET recheck_confidence = ?, verifier_class = COALESCE(verifier_class, ?) "
                     "WHERE id = ?", (best["confidence"] if best else None, best["code"] if best else None, event_id))
        verdict, reason = reports.suggested_verdict(_event(conn, event_id))
        if verdict == "recheck":
            verdict, reason = "rejected", "close-up re-check found no damage either"
        result = {"event_id": event_id, "found": best is not None, "class": best["code"] if best else None,
                  "confidence": best["confidence"] if best else None, "suggested_verdict": verdict, "reason": reason}
        audit(conn, "mcp:detector", "recheck", f"event:{event_id}", result)
    return result


@mcp.tool(name="detector_severity", annotations=READ)
def severity(event_id: str) -> dict:
    """Severity (low / medium / high) from damage type, estimated width (HRM Priority 1 is >= 25 cm wide),
    confidence and frames seen. Depth cannot be measured from video and is never claimed."""
    with session() as conn:
        event = _event(conn, event_id)
    conf = event["verified_confidence"] or event["recheck_confidence"] or event["confidence"]
    sev = reports.estimate_severity(event["class_code"], event["box_area_ratio"], conf, event["frames_seen"],
                                    event["width_m"], event.get("jolt_g"))
    sev.pop("band", None)  # the band is applied by reports_create_or_merge; the agent reasons on the level
    return {"event_id": event_id, **sev}


@mcp.tool(name="detector_record_verdict", annotations=WRITE)
def record_verdict(event_id: str, verdict: str, rationale: str) -> dict:
    """Decide an event: 'confirmed' (real damage), 'disputed' (real damage, but the two models disagree on the class;
    the edge label is kept and a human is asked) or 'rejected' (false alarm). Confirmed/disputed need verifier
    evidence. rationale: one sentence citing the evidence."""
    with session() as conn:
        try:
            return reports.record_verdict(conn, event_id, verdict, rationale, "agent:vision")
        except ValueError as e:
            raise ToolError(str(e)) from e


if __name__ == "__main__":
    mcp.run()
