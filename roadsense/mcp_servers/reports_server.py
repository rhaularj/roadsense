"""MCP server (Triage / Filing drafts / Follow-up): the shared report database."""
from __future__ import annotations

import re

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..common.config import settings
from ..common.db import REPORT_STATUSES, now, row, session
from ..core import geo, open311, reports

mcp = FastMCP("roadsense-reports")
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
    event.pop("image_path", None)
    return event


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
    info = open311.service_info(jurisdiction)
    with session() as conn:
        event = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
        if event is None:
            raise ToolError(f"unknown event {event_id}")
        place = geo.reverse_geocode(conn, event["lat"], event["lon"])  # address comes from the map, not the model
        sev = reports.estimate_severity(event["class_code"], event["box_area_ratio"], event["confidence"],
                                        event["frames_seen"], event["width_m"])
        try:
            result = reports.create_or_merge(
                conn, event_id, severity, place.get("address"), place.get("municipality"), settings.dedupe_radius_m,
                actor="agent:triage", jurisdiction=info["authority"] if info else jurisdiction,
                rationale=_clean_text(rationale, 300), p1_candidate=sev["p1_candidate"])
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
        report["events"] = [r["id"] for r in conn.execute("SELECT id FROM events WHERE report_id = ?", (report_id,))]
    return report


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
