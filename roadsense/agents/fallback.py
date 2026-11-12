"""Deterministic pipeline over the same MCP tools: the circuit breaker. Runs alone when no LLM is available, and
after every agent run to complete any step the agents skipped. Every call is idempotent, so after a complete agent
run it touches nothing, and the number of events it had to finish is reported as the fallback rate."""
from __future__ import annotations

from ..common.db import audit, row, session
from .mcp_client import Toolbox


def _audit(action: str, subject: str, detail=None) -> None:
    with session() as conn:
        audit(conn, "fallback", action, subject, detail)


def _status(event_id: str) -> str:
    with session() as conn:
        return conn.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()["status"]


async def decide_event(toolbox: Toolbox, event_id: str) -> str:
    """verify → (re-check) → verdict by the rule in core.reports.suggested_verdict. Returns the final status."""
    v = await toolbox.call("detector_verify", {"event_id": event_id})
    verdict, reason = v.get("suggested_verdict"), v.get("reason", "")
    if verdict == "recheck":
        r = await toolbox.call("detector_recheck", {"event_id": event_id})
        verdict, reason = r.get("suggested_verdict", "rejected"), r.get("reason", "")
    await toolbox.call("detector_record_verdict", {"event_id": event_id, "verdict": verdict or "rejected",
                                                   "rationale": f"rule: {reason}"})
    return _status(event_id)


async def triage_event(toolbox: Toolbox, event: dict) -> dict:
    sev = await toolbox.call("detector_severity", {"event_id": event["id"]})
    place = await toolbox.call("geo_find_jurisdiction", {"lat": event["lat"], "lon": event["lon"]})
    best = (place.get("candidates") or [{"authority": place.get("municipality"), "evidence": "no candidates"}])[0]
    return await toolbox.call("reports_create_or_merge", {
        "event_id": event["id"], "severity": sev.get("severity", "medium"),
        "jurisdiction": best["authority"] or "unknown", "rationale": f"rule: top candidate ({best['evidence']})"})


async def complete_trip(toolbox: Toolbox, trip_id: str) -> int:
    """Finish every event of the trip that the agents left undecided or unreported. Returns how many it touched."""
    with session() as conn:
        pending = [dict(r) for r in conn.execute(
            "SELECT id, lat, lon, status FROM events WHERE trip_id = ? AND status IN ('received', 'checked', "
            "'verified')", (trip_id,))]
    for e in pending:
        status = e["status"]
        if status in ("received", "checked"):
            status = await decide_event(toolbox, e["id"])
        if status == "verified":
            result = await triage_event(toolbox, e)
            _audit("completed_event", f"event:{e['id']}", {"result": result.get("action", result.get("error"))})
    return len(pending)


def trip_summary(trip_id: str) -> str:
    with session() as conn:
        n = dict(conn.execute("SELECT status, COUNT(*) FROM events WHERE trip_id = ? GROUP BY status",
                              (trip_id,)).fetchall())
        disputed = conn.execute("SELECT COUNT(*) FROM events WHERE trip_id = ? AND class_disputed = 1",
                                (trip_id,)).fetchone()[0]
        new = conn.execute("SELECT COUNT(*) FROM reports WHERE trip_id = ? AND status = 'pending_approval'",
                           (trip_id,)).fetchone()[0]
        merged = conn.execute("SELECT COUNT(*) FROM events e JOIN reports r ON e.report_id = r.id "
                              "WHERE e.trip_id = ? AND r.trip_id != ?", (trip_id, trip_id)).fetchone()[0]
        provincial = conn.execute("SELECT COUNT(*) FROM reports WHERE trip_id = ? AND jurisdiction LIKE 'Nova Scotia%'",
                                  (trip_id,)).fetchone()[0]
    return (f"{n.get('processed', 0)} defect(s) confirmed ({disputed} with a class the two models disagree on) and "
            f"{n.get('rejected', 0)} false alarm(s) dropped. {merged} matched damage other drivers already reported. "
            f"{new} new report(s) await your approval" + (f", {provincial} of them for the province." if provincial
                                                          else "."))


async def file_report(toolbox: Toolbox, report_id: int) -> dict:
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    if r is None:
        return {"error": f"unknown report {report_id}"}
    if r["status"] == "submitted":
        return {"ok": True, "service_request_id": r["service_request_id"], "channel": r["channel"], "by": "agent"}
    result = await toolbox.call("city_submit_request", {"report_id": report_id})
    _audit("filed" if result.get("ok") else "file_failed", f"report:{report_id}", result)
    return {**result, "by": "fallback"}


async def follow_up(toolbox: Toolbox) -> dict:
    with session() as conn:
        submitted = [r["id"] for r in conn.execute(
            "SELECT id FROM reports WHERE status = 'submitted' AND channel IN ('open311', 'cityworks', 'arcgis')")]
        fixed_unnotified = [dict(r) for r in conn.execute(
            "SELECT * FROM reports r WHERE status = 'fixed' AND NOT EXISTS "
            "(SELECT 1 FROM notifications n WHERE n.report_id = r.id)")]
    fixed = []
    for rid in submitted:
        s = await toolbox.call("city_request_status", {"report_id": rid})
        if s.get("fixed"):
            fixed.append(rid)
    with session() as conn:
        to_notify = [dict(r) for r in conn.execute(
            "SELECT * FROM reports r WHERE status = 'fixed' AND NOT EXISTS "
            "(SELECT 1 FROM notifications n WHERE n.report_id = r.id)")]
    for r in to_notify:
        await toolbox.call("reports_notify_driver", {"report_id": r["id"], "message":
                           f"Good news: the {r['class_name'].lower()} you reported at {r['address']} has been "
                           "repaired. Thanks for helping keep the roads safe!"})
    return {"checked": len(submitted), "fixed": sorted(set(fixed) | {r["id"] for r in fixed_unnotified})}
