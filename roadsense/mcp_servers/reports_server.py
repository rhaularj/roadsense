"""MCP server (Triage / Filing drafts / Follow-up): the shared report database."""
from __future__ import annotations

import re

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..common.config import settings
from ..common.db import REPORT_STATUSES, audit, now, row, session
from ..core import geo, open311, reports

mcp = FastMCP("roadsense-reports")
# What the agents see of a row: a fixed allow-list. Delivery bookkeeping (approved payload, attempts, errors) and
# privacy-relevant columns never reach the model, and tool results stay stable for the recorded keyless demo.
INTERNAL = {"image_path", "jolt_g", "server_redacted", "suppressed_by", "road_class", "road_name", "approved_payload",
            "approved_by", "approved_at", "rejected_by", "delivery_attempts", "last_error", "next_attempt_at",
            "external_ref", "corroborations", "severity_band", "repair_target_days", "pending_update"}


def _for_agent(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in INTERNAL}
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def _clean_text(text: str, limit: int) -> str:
    """Model-written text goes to city staff and drivers: plain text only, no links, bounded length."""
    text = re.sub(r"https?://\S+|www\.\S+", "[link removed]", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f<>]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


@mcp.tool(name="reports_get_event", annotations=READ)
def get_event(event_id: str) -> dict:
    """Metadata of an edge event: class, confidences, frames seen, projected position, width, verdict and status."""
    with session() as conn:
        event = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    if event is None:
        raise ToolError(f"unknown event {event_id}")
    return _for_agent(event)


@mcp.tool(name="reports_find_nearby", annotations=READ)
def find_nearby(lat: float, lon: float, class_code: str | None = None, radius_m: float | None = None) -> dict:
    """Open reports within radius_m metres (default: the dedupe radius), nearest first. Use it to explain a merge."""
    radius = min(radius_m or settings.dedupe_radius_m, 200.0)
    with session() as conn:
        found = reports.find_nearby(conn, lat, lon, class_code, radius)
    return {"radius_m": radius, "count": len(found),
            "reports": [{k: r[k] for k in ("id", "class_code", "severity", "confirmations", "status", "distance_m")}
                        for r in found[:10]]}


@mcp.tool(name="reports_create_or_merge", annotations=WRITE)
def create_or_merge(event_id: str, severity: str, jurisdiction: str, rationale: str) -> dict:
    """Attach a verified event to the matching open report within the dedupe radius (adds a driver confirmation), or
    create a new report awaiting driver approval. severity: low|medium|high (use detector_severity). jurisdiction:
    the road authority you chose from geo_find_jurisdiction. rationale: one sentence on the jurisdiction choice."""
    if severity not in reports.SEVERITY_WEIGHT:
        raise ToolError("severity must be low, medium or high")
    with session() as conn:
        event = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
        if event is None:
            raise ToolError(f"unknown event {event_id}")
        place = geo.reverse_geocode(conn, event["lat"], event["lon"])  # address comes from the map, not the model
        conf = event["verified_confidence"] or event["recheck_confidence"] or event["confidence"]
        sev = reports.estimate_severity(event["class_code"], event["box_area_ratio"], conf,
                                        event["frames_seen"], event["width_m"], event.get("jolt_g"))
        # the rule decides severity; the agent's opinion is kept in the audit log when it differs
        if severity != sev["severity"]:
            audit(conn, "agent:triage", "severity_disagreement", f"event:{event_id}",
                  {"agent": severity, "rule": sev["severity"], "reason": sev["reason"]})
        # the agent may only choose among the authorities the map evidence supports
        candidates = [c for c in geo.jurisdiction_candidates(place) if c.get("authority")]
        allowed = {open311.service_info(c["authority"])["authority"] if open311.service_info(c["authority"])
                   else c["authority"] for c in candidates}
        info = open311.service_info(jurisdiction)
        chosen = info["authority"] if info else jurisdiction
        if allowed and chosen not in allowed:
            fallback = candidates[0]["authority"] if candidates else jurisdiction
            audit(conn, "agent:triage", "jurisdiction_overridden", f"event:{event_id}",
                  {"agent": jurisdiction, "used": fallback, "allowed": sorted(allowed)})
            info = open311.service_info(fallback)
            chosen = info["authority"] if info else fallback
        if open311.service_info(chosen) is None:
            raise ToolError(f"{chosen!r} has no delivery channel in the authority directory; choose one of "
                            f"{sorted(allowed)}")
        try:
            result = reports.create_or_merge(
                conn, event_id, sev["severity"], place.get("address"), place.get("municipality"),
                settings.dedupe_radius_m, actor="agent:triage", jurisdiction=chosen,
                rationale=_clean_text(rationale, 300), p1_candidate=sev["p1_candidate"], band=sev["band"],
                road_class=place.get("road_class"), road_name=place.get("road"))
        except ValueError as e:
            raise ToolError(str(e)) from e
    r = result["report"]
    return {"action": result["action"], "report_id": r["id"], "confirmations": r["confirmations"],
            "priority": r["priority"], "jurisdiction": r["jurisdiction"], "status": r["status"]}


@mcp.tool(name="reports_save_draft", annotations=WRITE)
def save_draft(report_id: int, description: str) -> dict:
    """Save the 2-3 sentence description that will be sent to the road authority. Only for reports still awaiting
    driver approval: the driver approves the exact text."""
    with session() as conn:
        r = row(conn.execute("SELECT status FROM reports WHERE id = ?", (report_id,)).fetchone())
        if r is None:
            raise ToolError(f"unknown report {report_id}")
        if r["status"] != "pending_approval":
            raise ToolError("the description is locked once the driver has decided")
        text = _clean_text(description, 600)
        if len(text) < 30:
            raise ToolError("description too short")
        conn.execute("UPDATE reports SET draft_description = ?, updated_at = ? WHERE id = ?", (text, now(), report_id))
    return {"ok": True, "report_id": report_id, "description": text}


@mcp.tool(name="reports_get", annotations=READ)
def get_report(report_id: int) -> dict:
    """One report with its status, confirmations, priority, jurisdiction, flags and linked events."""
    with session() as conn:
        report = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if report is None:
            raise ToolError(f"unknown report {report_id}")
        report["events"] = [r["id"] for r in conn.execute(
            "SELECT id FROM events WHERE report_id = ? AND suppressed_by IS NULL", (report_id,))]
    return _for_agent(report)


@mcp.tool(name="reports_list", annotations=READ)
def list_reports(status: str | None = None, trip_id: str | None = None, limit: int = 20) -> dict:
    """Reports, highest priority first, optionally filtered by status and/or the trip that created them."""
    if status and status not in REPORT_STATUSES:
        raise ToolError(f"status must be one of {REPORT_STATUSES}")
    sql, args = "SELECT * FROM reports WHERE 1=1", []
    if status:
        sql, args = sql + " AND status = ?", [*args, status]
    if trip_id:
        sql, args = sql + " AND trip_id = ?", [*args, trip_id]
    with session() as conn:
        rows = conn.execute(sql + " ORDER BY priority DESC LIMIT ?", [*args, min(limit, 100)]).fetchall()
    keys = ("id", "class_name", "severity", "confirmations", "priority", "address", "jurisdiction", "status",
            "p1_candidate", "class_disputed", "width_m", "draft_description")
    return {"reports": [{k: r[k] for k in keys} for r in rows]}


@mcp.tool(name="reports_notify_driver", annotations=WRITE)
def notify_driver(report_id: int, message: str) -> dict:
    """Send a short notification to the drivers who reported this damage (shown in the RoadSense app)."""
    with session() as conn:
        if conn.execute("SELECT 1 FROM reports WHERE id = ?", (report_id,)).fetchone() is None:
            raise ToolError(f"unknown report {report_id}")
        if conn.execute("SELECT 1 FROM notifications WHERE report_id = ?", (report_id,)).fetchone():
            return {"ok": True, "duplicate": True}
        conn.execute("INSERT INTO notifications (ts, report_id, message) VALUES (?, ?, ?)",
                     (now(), report_id, _clean_text(message, 300)))
    return {"ok": True}


if __name__ == "__main__":
    mcp.run()
