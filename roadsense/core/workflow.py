"""The municipal repair workflow: one state machine, and the only code that writes reports.status.

    pending_approval ──reject──▶ closed (rejected)
          │ approve
          ▼
    awaiting_inspection ──assign──▶ inspection_assigned ──no_repair_needed──▶ closed (no_repair_needed)
          │ refer (system: forwarding on, road not ours)   │ repair_needed (+ repair_eta)
          ▼                                               ▼
    closed (referred)          repair_needed ──repaired──▶ repaired ──reopen──▶ reopened ──repair_needed──▶ ...

"Repaired (verified)" is status repaired with verification_status = 'verified': the crew's claim and RoadSense's
independent check (core.repair) stay separate.

transition() checks the table, the role, the assignee and the fields, writes the columns, writes one hash-chained
ledger entry (core.ledger) and moves the service-standards clock. Anything else that wants a report to change status
calls it; an illegal move raises WorkflowError (the API answers 409, or 403 / 422 / 404).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

from ..common.db import audit, now, row

STATUSES = ("pending_approval", "awaiting_inspection", "inspection_assigned", "repair_needed", "repaired", "reopened",
            "closed")
LABELS = {"pending_approval": "Awaiting review", "awaiting_inspection": "Awaiting inspection",
          "inspection_assigned": "Inspection assigned", "repair_needed": "Repair needed", "repaired": "Repaired",
          "reopened": "Reopened", "closed": "Closed"}
CLOSED_REASONS = {"rejected": "Rejected", "no_repair_needed": "Repair not needed", "referred": "Referred"}
OPEN = ("pending_approval", "awaiting_inspection", "inspection_assigned", "repair_needed", "reopened")
DUE = ("repair_needed", "reopened")  # statuses with a repair date that can pass
INITIAL = "pending_approval"
BANDS = ("S1", "S2", "S3", "S4")
SYSTEM = "system"  # plain RoadSense code: the repair check and the referral path, never an agent

REVIEW = ("admin", "reviewer")
INSPECT = ("admin", "reviewer", "inspector")
INSPECT_ROLES = INSPECT  # who can be assigned an inspection


@dataclass(frozen=True)
class Action:
    sources: tuple[str, ...]
    target: str
    roles: tuple[str, ...]
    label: str


ACTIONS: dict[str, Action] = {
    "approve": Action(("pending_approval",), "awaiting_inspection", REVIEW, "Approve"),
    "reject": Action(("pending_approval",), "closed", REVIEW, "Reject"),
    "assign": Action(("awaiting_inspection", "inspection_assigned"), "inspection_assigned", REVIEW, "Assign inspector"),
    "repair_needed": Action(("inspection_assigned", "reopened"), "repair_needed", INSPECT, "Repair needed"),
    "no_repair_needed": Action(("inspection_assigned",), "closed", INSPECT, "No repair needed"),
    "repaired": Action(("repair_needed",), "repaired", INSPECT, "Mark repaired"),
    "reopen": Action(("repaired",), "reopened", (*INSPECT, SYSTEM), "Reopen"),
    "reschedule": Action(("repair_needed",), "repair_needed", INSPECT, "Reschedule"),
    "refer": Action(("awaiting_inspection",), "closed", (SYSTEM,), "Referred"),
}


class WorkflowError(ValueError):
    """An illegal move. status is the HTTP code the API answers with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.message, self.status = message, status


def today(at: str | None = None) -> date:
    """The municipality's local calendar day (ETAs and overdue are plain dates in Halifax time)."""
    from .business_days import Calendar
    from .service_standards import config

    return Calendar(config()["timezone"]).local_date(at or now())


def label(report: dict) -> str:
    s = report.get("status")
    if s == "closed" and report.get("closed_reason") in CLOSED_REASONS:
        return f"Closed ({CLOSED_REASONS[report['closed_reason']]})"
    if s == "repaired" and report.get("verification_status") == "verified":
        return "Repaired (verified)"
    return LABELS.get(s, s or "")


def overdue(report: dict, on: date | None = None) -> bool:
    eta = report.get("repair_eta")
    return bool(report.get("status") in DUE and eta and eta < (on or today()).isoformat())


def _may(action: str, spec: Action, report: dict, role: str | None, user_id) -> str | None:
    """Why this person may not take the action (None when they may)."""
    if role not in spec.roles:
        return f"your role ({role or 'none'}) cannot {spec.label.lower()}"
    if role == "inspector" and report.get("inspector_id") != user_id:
        return "this report is assigned to another inspector"
    return None


def allowed_actions(report: dict, role: str | None, user_id=None) -> list[str]:
    out = []
    for name, spec in ACTIONS.items():
        if SYSTEM in spec.roles and len(spec.roles) == 1:
            continue
        if report.get("status") not in spec.sources or _may(name, spec, report, role, user_id):
            continue
        if name == "reopen" and report.get("verification_status") == "verified":
            continue
        out.append(name)
    return out


def decorate(report: dict, role: str | None, user_id=None) -> dict:
    """What every API response adds to a report: its label, overdue flag and the next actions for this person."""
    return {**report, "status_label": label(report), "lifecycle": label(report), "overdue": overdue(report),
            "allowed_actions": allowed_actions(report, role, user_id)}


# ---------------- field validation ----------------
def _text(value, limit: int, name: str, required: bool = False) -> str | None:
    text = " ".join(str(value or "").split())[:limit]
    if required and not text:
        raise WorkflowError(f"{name} is required", 422)
    return text or None


def _eta(value, on: date) -> str:
    try:
        d = date.fromisoformat(str(value or "").strip()[:10])
    except ValueError as e:
        raise WorkflowError("repair_eta must be a date (YYYY-MM-DD)", 422) from e
    if d < on:
        raise WorkflowError("repair_eta cannot be in the past", 422)
    return d.isoformat()


def _photo(value) -> str | None:
    if value in (None, ""):
        return None
    kind, _, pid = str(value).partition(":")
    if kind not in ("inspection", "repair") or not pid.replace("-", "").isalnum():
        raise WorkflowError("photo must be an uploaded photo reference", 422)
    return f"{kind}:{pid}"


def _inspector(conn: sqlite3.Connection, value) -> dict:
    try:
        uid = int(value)
    except (TypeError, ValueError) as e:
        raise WorkflowError("inspector_id must be a user id", 422) from e
    u = row(conn.execute("SELECT id, email, name, role, active FROM users WHERE id = ?", (uid,)).fetchone())
    if u is None or not u["active"] or u["role"] not in INSPECT_ROLES:
        raise WorkflowError("inspector_id must be an active inspector, reviewer or admin", 422)
    return u


# ---------------- what each action writes ----------------
def _approve(conn, r, f, actor, ts, on):
    from . import open311, reports

    payload = open311.build_payload(r)
    digest = open311.payload_hash(payload)
    reports.record_label(conn, r["id"], "approved", actor, r["class_code"])
    return ({"approved_payload": json.dumps(payload, sort_keys=True), "approved_payload_hash": digest,
             "approved_by": actor, "approved_at": ts}, {"payload_hash": digest})


def _reject(conn, r, f, actor, ts, on):
    from . import reports

    reports.record_label(conn, r["id"], "rejected", actor)
    return ({"rejected_by": actor, "closed_reason": "rejected", "closed_at": ts},
            {"reason": _text(f.get("reason"), 500, "reason")})


def _assign(conn, r, f, actor, ts, on):
    u = _inspector(conn, f.get("inspector_id"))
    return ({"inspector_id": u["id"], "inspection_assigned_at": ts},
            {"inspector_id": u["id"], "inspector": u["email"], "inspector_name": u["name"],
             "previous_inspector_id": r.get("inspector_id")})


def _repair_needed(conn, r, f, actor, ts, on):
    from . import reports

    sets = {"repair_eta": _eta(f.get("repair_eta"), on)}
    notes, photo = _text(f.get("notes"), 1000, "notes"), _photo(f.get("photo"))
    if r["status"] == "inspection_assigned":  # the inspection's own record; a re-plan after a reopen is in the ledger
        sets.update(inspected_at=ts, inspection_notes=notes, inspection_photo=photo)
    band = f.get("severity_band")
    if band not in (None, ""):
        if band not in BANDS:
            raise WorkflowError(f"severity_band must be one of {BANDS}", 422)
        sev = reports.level(band)
        sets.update(severity_band=band, severity=sev, priority=reports.priority(sev, r["class_code"],
                                                                                r["confirmations"]))
    detail = {"repair_eta": sets["repair_eta"], "notes": notes, "photo": photo}
    if band and band != r.get("severity_band"):
        detail["severity_band"] = {"from": r.get("severity_band"), "to": band}
    return sets, detail


def _no_repair(conn, r, f, actor, ts, on):
    notes, photo = _text(f.get("notes"), 1000, "notes"), _photo(f.get("photo"))
    return ({"inspected_at": ts, "inspection_notes": notes, "inspection_photo": photo,
             "closed_reason": "no_repair_needed", "closed_at": ts}, {"notes": notes, "photo": photo})


def _repaired(conn, r, f, actor, ts, on):
    notes, photo = _text(f.get("notes"), 1000, "notes"), _photo(f.get("photo"))
    # a fresh independent check: only passes after this repair count (core.repair)
    return ({"repaired_at": ts, "repaired_by": actor, "repair_notes": notes, "repair_photo": photo, "closed_at": ts,
             "verification_status": "awaiting", "verification_updated_at": ts}, {"notes": notes, "photo": photo})


def _reopen(conn, r, f, actor, ts, on):
    reason = _text(f.get("reason"), 500, "reason", required=True)
    event_id = _text(f.get("event_id"), 80, "event_id")
    return ({"reopen_count": (r.get("reopen_count") or 0) + 1, "reopened_at": ts, "reopen_reason": reason,
             "reopen_event_id": event_id, "repair_eta": None, "verification_status": "reopened",
             "verification_updated_at": ts},
            {"reason": reason, "event_id": event_id, "previous_eta": r.get("repair_eta"),
             "reopen_count": (r.get("reopen_count") or 0) + 1})


def _reschedule(conn, r, f, actor, ts, on):
    eta = _eta(f.get("repair_eta"), on)
    if eta == r.get("repair_eta"):
        raise WorkflowError("that is already the repair date", 422)
    return {"repair_eta": eta}, {"repair_eta": {"from": r.get("repair_eta"), "to": eta},
                                 "reason": _text(f.get("reason"), 500, "reason")}


REFER_FIELDS = ("service_request_id", "channel", "description", "submitted_payload_hash", "delivery_attempts")


def _refer(conn, r, f, actor, ts, on):
    if not f.get("service_request_id"):
        raise WorkflowError("service_request_id is required", 422)
    sets = {k: f[k] for k in REFER_FIELDS if k in f}
    sets.update(closed_reason="referred", closed_at=ts, last_error=None, next_attempt_at=None)
    return sets, {k: f.get(k) for k in ("service_request_id", "channel", "submitted_payload_hash")}


HANDLERS = {"approve": _approve, "reject": _reject, "assign": _assign, "repair_needed": _repair_needed,
            "no_repair_needed": _no_repair, "repaired": _repaired, "reopen": _reopen, "reschedule": _reschedule,
            "refer": _refer}


def transition(conn: sqlite3.Connection, report_id: int, action: str, actor: str, role: str | None,
               user_id=None, at: str | None = None, **fields) -> dict:
    """Move one report. `role` is the person's role, or "system" for RoadSense's own code; `at` back-dates the move
    (demo data and tests). Returns the updated report row."""
    from . import ledger

    spec = ACTIONS.get(action)
    if spec is None:
        raise WorkflowError(f"unknown action {action!r}; one of {', '.join(ACTIONS)}", 422)
    r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    if r is None:
        raise WorkflowError(f"unknown report {report_id}", 404)
    if str(actor or "").startswith("agent:"):
        raise WorkflowError("agents may draft and recommend, but only people move a report", 403)
    why = _may(action, spec, r, role, user_id)
    if why:
        raise WorkflowError(why, 403)
    if r["status"] not in spec.sources:
        raise WorkflowError(f"cannot {spec.label.lower()} a report that is {label(r).lower()}", 409)
    if action == "reopen" and r.get("verification_status") == "verified":
        raise WorkflowError("the repair was independently verified; new damage here is a new report", 409)
    ts = at or now()
    sets, detail = HANDLERS[action](conn, r, fields, actor, ts, today(ts))
    sets.update(status=spec.target, updated_at=ts)
    conn.execute(f"UPDATE reports SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                 [*sets.values(), report_id])
    entry = ledger.append(conn, report_id, f"workflow_{action}", actor,
                          {"report_id": report_id, "action": action, "from": r["status"], "to": spec.target,
                           "closed_reason": sets.get("closed_reason"), "role": role, "user_id": user_id,
                           **{k: v for k, v in detail.items() if v is not None}}, ts=ts)
    # the clock remembers the chain head (ledger.verify): every entry of the report's chain moves it
    conn.execute("UPDATE service_clocks SET ledger_head = ? WHERE report_id = ?", (entry["hash"], report_id))
    updated = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    _clock(conn, action, r, updated, actor, ts)
    return updated


# the service-standards clock measures the municipality from approval: these are the steps it records
CLOCK_EVENTS = {"assign": ("acknowledged",), "no_repair_needed": ("inspection_started", "report_closed"),
                "repaired": ("repair_completed",), "reopen": ("report_reopened",)}


def will_refer(report: dict) -> bool:
    """Forwarding is on and another authority owns the road: after approval the report is referred to it, and that
    authority's clock starts when the referral is sent (ROADSENSE_FORWARD_MODE, off by default)."""
    from ..common.config import settings
    from .ownership import owned_here

    return settings.forwarding and not owned_here(report.get("jurisdiction"))


def _clock(conn, action, before, report, actor, ts) -> None:
    """Feed the service-standards clock (core.service_standards) the steps it measures. A tracking problem is audited
    and never blocks the person's step (the sweep backfills a missing clock)."""
    from . import service_standards as ss

    events = CLOCK_EVENTS.get(action, ())
    if action == "repair_needed" and before["status"] == "inspection_assigned":
        events = ("inspection_started",)
    try:
        if action == "approve" and not will_refer(report):
            ss.start_clock(conn, report, actor, submitted_at=ts, source="workflow")
        for ev in events:
            ss.record_event(conn, report["id"], ev, actor, "workflow", at=ts,
                            note=f"{ACTIONS[action].label}: {label(report).lower()}")
    except Exception as e:  # noqa: BLE001
        audit(conn, actor, "service_clock_failed", f"report:{report['id']}", f"{action}: {e}"[:500])


# ---------------- migration from the go-between statuses ----------------
_OLD = {"approved": "awaiting_inspection", "submitted": "awaiting_inspection", "delivery_failed": "awaiting_inspection",
        "fixed": "repaired", "rejected": "closed"}


def migrate(conn: sqlite3.Connection) -> int:
    """Old databases: approved/submitted/delivery_failed → awaiting_inspection, fixed → repaired (or reopened when
    RoadSense's check had reopened it), rejected → closed (rejected). Idempotent; one audit row per report."""
    rows = conn.execute(f"SELECT id, status, verification_status, closed_at, updated_at FROM reports "
                        f"WHERE status IN ({','.join('?' * len(_OLD))})", list(_OLD)).fetchall()
    for r in rows:
        new = _OLD[r["status"]]
        sql, args = ["status = ?"], [new]
        if r["status"] == "fixed":
            sql.append("repaired_at = COALESCE(repaired_at, closed_at)")
            if r["verification_status"] == "reopened":
                new, args[0] = "reopened", "reopened"
                sql.append("reopen_count = MAX(reopen_count, 1)")
        if r["status"] == "rejected":
            sql += ["closed_reason = 'rejected'", "closed_at = COALESCE(closed_at, updated_at)"]
        conn.execute(f"UPDATE reports SET {', '.join(sql)} WHERE id = ?", [*args, r["id"]])
        audit(conn, "migration", "status_migrated", f"report:{r['id']}", {"from": r["status"], "to": new})
    if rows:
        conn.commit()
    return len(rows)
