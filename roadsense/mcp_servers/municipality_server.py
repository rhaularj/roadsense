"""MCP server (Filing / Follow-up): deliver approved reports to the road authority and track their status.

Guardrails in code, whatever an agent asks for: only driver-approved reports are sent, the payload is rebuilt from
the database and must hash to exactly what the driver approved, and the tool takes no free text from the model.
"""
from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..common.db import audit, row, session
from ..core import open311, reports

mcp = FastMCP("roadsense-municipality")
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
SEND = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)


@mcp.tool(name="city_service_info", annotations=READ)
def service_info(authority: str) -> dict:
    """How a road authority can be reached (open311 API, referral package) and its contact details."""
    return open311.service_info(authority) or {"authority": authority, "channel": "none"}


@mcp.tool(name="city_submit_request", annotations=SEND)
def submit_request(report_id: int) -> dict:
    """Send an APPROVED report to its road authority: Open311 service request, or a referral package for authorities
    without an API. Returns the authority's request id."""
    with session() as conn:
        report = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if report is None:
            raise ToolError(f"unknown report {report_id}")
        if report["status"] == "submitted":
            return {"ok": True, "already_submitted": True, "service_request_id": report["service_request_id"]}
        if report["status"] != "approved":
            raise ToolError(f"report status is {report['status']!r}; only driver-approved reports can be sent")
        payload = open311.build_payload(report)
        digest = open311.payload_hash(payload)
        if report["approved_payload_hash"] and digest != report["approved_payload_hash"]:
            audit(conn, "mcp:municipality", "payload_mismatch", f"report:{report_id}",
                  {"approved": report["approved_payload_hash"], "now": digest})
            raise ToolError("payload changed after the driver approved it; ask the driver to review again")
        try:
            ack = open311.submit(payload)
        except (httpx.HTTPError, ValueError) as e:
            raise ToolError(f"delivery failed: {e}") from e
        updated = reports.set_status(conn, report_id, "submitted", "mcp:municipality",
                                     service_request_id=ack["service_request_id"], channel=ack["channel"],
                                     description=payload["description"], submitted_payload_hash=digest)
    return {"ok": True, **ack, "authority": payload["authority"], "report_status": updated["status"]}


@mcp.tool(name="city_request_status", annotations=READ)
def request_status(report_id: int) -> dict:
    """Status of a submitted report at the authority (open / closed). Marks the report fixed when closed."""
    with session() as conn:
        report = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if report is None or not report["service_request_id"]:
            raise ToolError("report not submitted")
        try:
            city = open311.request_status(report["jurisdiction"], report["service_request_id"])
        except httpx.HTTPError as e:
            raise ToolError(f"status check failed: {e}") from e
        fixed = city.get("status") == "closed"
        newly = fixed and report["status"] != "fixed"
        if newly:
            reports.set_status(conn, report_id, "fixed", "mcp:municipality")
    return {"report_id": report_id, "channel": report["channel"], "city_status": city.get("status"),
            "status_notes": city.get("status_notes"), "fixed": fixed, "newly_fixed": newly}


if __name__ == "__main__":
    mcp.run()
