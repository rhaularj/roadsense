"""MCP server (Filing / Follow-up): deliver approved reports to the road authority and track their status.

Guardrails in code, whatever an agent asks for: only reviewer-approved reports are sent; what is sent is the payload
snapshot the reviewer approved, re-hashed against the stored hash; and the tools take no free text from the model.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..common.config import settings
from ..common.db import audit, now, row, session
from ..core import delivery, open311, reports

mcp = FastMCP("roadsense-municipality")
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
SEND = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
DELIVERABLE = ("approved", "delivery_failed")


def _approved_payload(conn, report: dict) -> dict:
    """The payload the reviewer approved. Reports approved before snapshots existed are rebuilt and must hash the
    same; a snapshot must still hash to the stored hash (tampering in the database is refused)."""
    if report.get("approved_payload"):
        payload = json.loads(report["approved_payload"])
    else:
        payload = open311.build_payload(report)
    digest = open311.payload_hash(payload)
    if report["approved_payload_hash"] and digest != report["approved_payload_hash"]:
        audit(conn, "mcp:municipality", "payload_mismatch", f"report:{report['id']}",
              {"approved": report["approved_payload_hash"], "now": digest})
        conn.commit()
        raise ToolError("payload changed after the reviewer approved it; ask the reviewer to review again")
    return payload


def deliver(report_id: int, actor: str = "mcp:municipality") -> dict:
    with session() as conn:
        report = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if report is None:
            raise ToolError(f"unknown report {report_id}")
        if report["status"] in ("submitted", "fixed"):
            return {"ok": True, "already_submitted": True, "service_request_id": report["service_request_id"]}
        if report["status"] not in DELIVERABLE:
            raise ToolError(f"report status is {report['status']!r}; only reviewer-approved reports can be sent")
        payload = _approved_payload(conn, report)
        digest = open311.payload_hash(payload)
        attempt = (report["delivery_attempts"] or 0) + 1
        try:
            ack = delivery.submit(payload, report)
        except delivery.DeliveryError as e:
            final = attempt >= settings.max_delivery_attempts
            nxt = None if final else (datetime.now(timezone.utc) + timedelta(
                seconds=delivery.backoff_seconds(attempt))).isoformat(timespec="seconds")
            conn.execute("INSERT INTO deliveries (report_id, kind, channel, ok, detail, ts) VALUES (?,?,?,?,?,?)",
                         (report_id, "submit", payload.get("channel"), 0, str(e)[:500], now()))
            reports.set_status(conn, report_id, "delivery_failed" if final else "approved", actor,
                               delivery_attempts=attempt, last_error=str(e)[:500], next_attempt_at=nxt)
            conn.commit()  # keep the failure record: the ToolError below skips the session's commit
            raise ToolError(f"delivery failed (attempt {attempt}/{settings.max_delivery_attempts}"
                            + (", giving up: resend from the report page" if final else f", retry at {nxt}")
                            + f"): {e}") from e
        conn.execute("INSERT INTO deliveries (report_id, kind, channel, ok, detail, ts) VALUES (?,?,?,?,?,?)",
                     (report_id, "submit", ack["channel"], 1, ack.get("notice"), now()))
        updated = reports.set_status(conn, report_id, "submitted", actor, service_request_id=ack["service_request_id"],
                                     channel=ack["channel"], description=payload["description"],
                                     submitted_payload_hash=digest, delivery_attempts=attempt, last_error=None,
                                     next_attempt_at=None)
    return {"ok": True, **ack, "authority": payload["authority"], "report_status": updated["status"]}


def push_update(report_id: int, actor: str = "mcp:municipality") -> dict:
    """New evidence on a filed request (more drivers, higher severity) is sent to the authority's system."""
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if r is None or r["status"] != "submitted" or not r["pending_update"]:
            return {"ok": True, "skipped": True}
        message = (f"RoadSense update: now confirmed by {r['confirmations']} independent drivers, severity "
                   f"{r['severity']}" + (f" (band {r['severity_band']})" if r.get("severity_band") else "") + ".")
        try:
            res = delivery.update(r["jurisdiction"], r["service_request_id"], r["channel"], message, r)
        except delivery.DeliveryError as e:
            conn.execute("INSERT INTO deliveries (report_id, kind, channel, ok, detail, ts) VALUES (?,?,?,?,?,?)",
                         (report_id, "update", r["channel"], 0, str(e)[:500], now()))
            return {"ok": False, "error": str(e)}
        conn.execute("INSERT INTO deliveries (report_id, kind, channel, ok, detail, ts) VALUES (?,?,?,?,?,?)",
                     (report_id, "update", r["channel"], int(bool(res.get("ok"))), res.get("detail") or message, now()))
        conn.execute("UPDATE reports SET pending_update = 0 WHERE id = ?", (report_id,))
        audit(conn, actor, "update_pushed" if res.get("ok") else "update_unsupported", f"report:{report_id}", res)
    return res


@mcp.tool(name="city_service_info", annotations=READ)
def service_info(authority: str) -> dict:
    """How a road authority can be reached (open311, cityworks, arcgis API, referral package) and its contacts."""
    return open311.service_info(authority) or {"authority": authority, "channel": "none"}


@mcp.tool(name="city_submit_request", annotations=SEND)
def submit_request(report_id: int) -> dict:
    """Send an APPROVED report to its road authority (the exact payload the reviewer approved). Returns the
    authority's request id. A failed delivery is retried automatically with backoff."""
    return deliver(report_id)


@mcp.tool(name="city_request_status", annotations=READ)
def request_status(report_id: int) -> dict:
    """Status of a submitted report at the authority (open / closed). Marks the report fixed when closed."""
    with session() as conn:
        report = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if report is None or not report["service_request_id"]:
            raise ToolError("report not submitted")
        try:
            city = delivery.status(report["jurisdiction"], report["service_request_id"], report["channel"])
        except delivery.DeliveryError as e:
            raise ToolError(str(e)) from e
        fixed = city.get("status") == "closed"
        newly = fixed and report["status"] != "fixed"
        if newly:
            reports.set_status(conn, report_id, "fixed", "mcp:municipality")
    return {"report_id": report_id, "channel": report["channel"], "city_status": city.get("status"),
            "status_notes": city.get("status_notes"), "fixed": fixed, "newly_fixed": newly}


if __name__ == "__main__":
    mcp.run()
