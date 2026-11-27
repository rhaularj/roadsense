"""The municipal repair workflow: one state machine, its role rules, required fields and the old-status migration."""
from datetime import date, timedelta

import pytest
from conftest import add_event

from roadsense.common.db import now, row, session
from roadsense.core import ledger, reports, workflow
from roadsense.core.workflow import WorkflowError

HRM = "Halifax Regional Municipality"
_n = {"i": 0}
TODAY = workflow.today()
SOON = (TODAY + timedelta(days=7)).isoformat()
LATER = (TODAY + timedelta(days=14)).isoformat()


def user(email, role):
    with session() as conn:
        conn.execute("INSERT INTO users (email, role, created_at) VALUES (?, ?, ?)", (email, role, now()))
        return conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]


def new_report() -> int:
    _n["i"] += 1
    eid = f"ev-wf{_n['i']}"
    add_event(eid, 44.60 + _n["i"] * 0.003, -63.58)
    with session() as conn:
        return reports.create_or_merge(conn, eid, "high", "x", HRM, 15, jurisdiction=HRM)["report"]["id"]


def get(rid):
    with session() as conn:
        return row(conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone())


def act(rid, action, actor="rev@x.test", role="reviewer", user_id=None, **fields):
    with session() as conn:
        return workflow.transition(conn, rid, action, actor, role, user_id=user_id, **fields)


def walk_to(status, inspector=None) -> int:
    """A fresh report moved along the happy path until it reaches `status`."""
    rid = new_report()
    steps = {
        "awaiting_inspection": [("approve", {})],
        "inspection_assigned": [("approve", {}), ("assign", {"inspector_id": inspector})],
        "repair_needed": [("approve", {}), ("assign", {"inspector_id": inspector}),
                          ("repair_needed", {"repair_eta": SOON})],
        "repaired": [("approve", {}), ("assign", {"inspector_id": inspector}),
                     ("repair_needed", {"repair_eta": SOON}), ("repaired", {})],
        "reopened": [("approve", {}), ("assign", {"inspector_id": inspector}),
                     ("repair_needed", {"repair_eta": SOON}), ("repaired", {}), ("reopen", {"reason": "still there"})],
        "closed": [("reject", {})],
    }.get(status, [])
    for action, fields in steps:
        act(rid, action, **fields)
    return rid


@pytest.fixture
def insp(db):
    return user("insp@x.test", "inspector")


# ---------------- legal transitions ----------------
LEGAL = [
    ("pending_approval", "approve", {}, "awaiting_inspection", None),
    ("pending_approval", "reject", {"reason": "not damage"}, "closed", "rejected"),
    ("awaiting_inspection", "assign", {"inspector_id": "INSP"}, "inspection_assigned", None),
    ("inspection_assigned", "assign", {"inspector_id": "INSP"}, "inspection_assigned", None),
    ("inspection_assigned", "repair_needed", {"repair_eta": SOON}, "repair_needed", None),
    ("inspection_assigned", "no_repair_needed", {"notes": "surface only"}, "closed", "no_repair_needed"),
    ("repair_needed", "repaired", {"notes": "patched"}, "repaired", None),
    ("repair_needed", "reschedule", {"repair_eta": LATER}, "repair_needed", None),
    ("repaired", "reopen", {"reason": "came back"}, "reopened", None),
    ("reopened", "repair_needed", {"repair_eta": SOON}, "repair_needed", None),
]


@pytest.mark.parametrize("start,action,fields,to,reason", LEGAL, ids=[f"{s}-{a}" for s, a, *_ in LEGAL])
def test_every_legal_transition(insp, start, action, fields, to, reason):
    rid = walk_to(start, insp)
    fields = {k: insp if v == "INSP" else v for k, v in fields.items()}
    r = act(rid, action, **fields)
    assert r["status"] == to and r["closed_reason"] == reason
    with session() as conn:
        last = [e for e in ledger.entries(conn, rid) if e["event_type"].startswith("workflow_")][-1]
        assert ledger.verify(conn, rid)["ok"]
    assert last["event_type"] == f"workflow_{action}" and last["actor"] == "rev@x.test"
    assert last["data"]["from"] == start and last["data"]["to"] == to


def test_every_illegal_transition_is_refused(insp):
    legal = {(s, a) for s, a, *_ in LEGAL}
    for start in workflow.STATUSES:
        rid = walk_to(start, insp)
        for action in workflow.ACTIONS:
            if (start, action) in legal or action == "refer":
                continue
            with pytest.raises(WorkflowError) as e:
                act(rid, action, inspector_id=insp, repair_eta=SOON, reason="x")
            assert e.value.status == 409, (start, action)
        assert get(rid)["status"] == start


def test_unknown_action_and_report():
    with pytest.raises(WorkflowError) as e:
        act(new_report(), "teleport")
    assert e.value.status == 422
    with pytest.raises(WorkflowError) as e:
        act(99999, "approve")
    assert e.value.status == 404


# ---------------- roles ----------------
@pytest.mark.parametrize("role", ["driver", "viewer", "inspector", None])
def test_only_reviewers_review(insp, role):
    rid = new_report()
    for action in ("approve", "reject"):
        with pytest.raises(WorkflowError) as e:
            act(rid, action, role=role, user_id=insp)
        assert e.value.status == 403
    with pytest.raises(WorkflowError):
        act(walk_to("awaiting_inspection"), "assign", role="inspector", user_id=insp, inspector_id=insp)


def test_inspector_acts_only_on_reports_assigned_to_them(insp):
    other = user("other@x.test", "inspector")
    rid = walk_to("inspection_assigned", insp)
    with pytest.raises(WorkflowError) as e:
        act(rid, "repair_needed", actor="other@x.test", role="inspector", user_id=other, repair_eta=SOON)
    assert e.value.status == 403 and "assigned" in e.value.message
    r = act(rid, "repair_needed", actor="insp@x.test", role="inspector", user_id=insp, repair_eta=SOON)
    assert r["status"] == "repair_needed"
    assert workflow.allowed_actions(get(rid), "inspector", other) == []
    assert set(workflow.allowed_actions(get(rid), "inspector", insp)) == {"repaired", "reschedule"}


def test_agents_can_never_move_a_report(insp):
    rid = new_report()
    for role in ("admin", "reviewer", "system"):
        with pytest.raises(WorkflowError) as e:
            act(rid, "approve", actor="agent:triage", role=role)
        assert e.value.status == 403


def test_system_only_for_reopen_and_refer(insp):
    with pytest.raises(WorkflowError):
        act(new_report(), "approve", actor="verify:repair", role="system")
    r = act(walk_to("repaired", insp), "reopen", actor="verify:repair", role="system", reason="seen again")
    assert r["status"] == "reopened"
    with pytest.raises(WorkflowError):
        act(walk_to("awaiting_inspection"), "refer", role="reviewer", service_request_id="1", channel="referral")
    r = act(walk_to("awaiting_inspection"), "refer", actor="mcp:municipality", role="system",
            service_request_id="REF-1", channel="referral")
    assert r["status"] == "closed" and r["closed_reason"] == "referred" and r["service_request_id"] == "REF-1"


def test_assign_needs_an_active_user_who_can_inspect(insp):
    viewer = user("v@x.test", "viewer")
    rid = walk_to("awaiting_inspection")
    for bad in (None, 12345, viewer, "abc"):
        with pytest.raises(WorkflowError) as e:
            act(rid, "assign", inspector_id=bad)
        assert e.value.status == 422
    r = act(rid, "assign", inspector_id=insp)
    assert r["inspector_id"] == insp and r["inspection_assigned_at"]
    reviewer = user("rev2@x.test", "reviewer")
    assert act(rid, "assign", inspector_id=reviewer)["inspector_id"] == reviewer  # re-assigning is allowed


# ---------------- required fields ----------------
def test_repair_needed_requires_a_valid_future_eta(insp):
    rid = walk_to("inspection_assigned", insp)
    for bad in ({}, {"repair_eta": ""}, {"repair_eta": "next week"}, {"repair_eta": "2026-02-30"},
                {"repair_eta": (TODAY - timedelta(days=1)).isoformat()}):
        with pytest.raises(WorkflowError) as e:
            act(rid, "repair_needed", **bad)
        assert e.value.status == 422
    r = act(rid, "repair_needed", repair_eta=TODAY.isoformat(), severity_band="S2", notes="  deep edge  ",
            photo="inspection:abc")
    assert r["repair_eta"] == TODAY.isoformat() and r["severity_band"] == "S2" and r["severity"] == "medium"
    assert r["inspection_notes"] == "deep edge" and r["inspection_photo"] == "inspection:abc" and r["inspected_at"]
    with pytest.raises(WorkflowError):
        act(walk_to("inspection_assigned", insp), "repair_needed", repair_eta=SOON, severity_band="S9")


def test_reopen_needs_a_reason_counts_and_clears_the_eta(insp):
    rid = walk_to("repaired", insp)
    with pytest.raises(WorkflowError) as e:
        act(rid, "reopen", reason="  ")
    assert e.value.status == 422
    r = act(rid, "reopen", reason="the patch failed", event_id="ev-x")
    assert r["reopen_count"] == 1 and r["repair_eta"] is None and r["reopen_reason"] == "the patch failed"
    assert r["reopen_event_id"] == "ev-x" and r["verification_status"] == "reopened"
    act(rid, "repair_needed", repair_eta=SOON)
    act(rid, "repaired")
    r = act(rid, "reopen", reason="again")
    assert r["reopen_count"] == 2


def test_verified_repair_cannot_be_reopened(insp):
    rid = walk_to("repaired", insp)
    with session() as conn:
        conn.execute("UPDATE reports SET verification_status = 'verified' WHERE id = ?", (rid,))
    with pytest.raises(WorkflowError) as e:
        act(rid, "reopen", reason="x")
    assert e.value.status == 409
    assert "reopen" not in workflow.allowed_actions(get(rid), "reviewer", None)


def test_reschedule_records_old_and_new_date(insp):
    rid = walk_to("repair_needed", insp)
    later = (TODAY + timedelta(days=30)).isoformat()
    assert act(rid, "reschedule", repair_eta=later)["repair_eta"] == later
    with session() as conn:
        data = ledger.entries(conn, rid)[-1]["data"]  # reschedule moves no clock: the workflow entry is the last
    assert data["repair_eta"] == {"from": SOON, "to": later}


def test_repaired_starts_a_fresh_verification(insp):
    rid = walk_to("repaired", insp)
    r = get(rid)
    assert r["verification_status"] == "awaiting" and r["repaired_at"] and r["repaired_by"] == "rev@x.test"
    assert r["closed_at"] == r["repaired_at"]


def test_approve_snapshots_the_payload_and_labels(insp):
    rid = new_report()
    r = act(rid, "approve")
    assert r["approved_payload"] and r["approved_payload_hash"] and r["approved_by"] == "rev@x.test"
    with session() as conn:
        assert conn.execute("SELECT label FROM labels WHERE report_id = ?", (rid,)).fetchone()[0] == "approved"


# ---------------- overdue and allowed actions ----------------
def test_overdue_is_computed_from_the_eta():
    r = {"status": "repair_needed", "repair_eta": "2026-11-20"}
    assert workflow.overdue(r, date(2026, 11, 21)) and not workflow.overdue(r, date(2026, 11, 20))
    assert not workflow.overdue({**r, "status": "repaired"}, date(2026, 12, 1))
    assert workflow.overdue({**r, "status": "reopened"}, date(2026, 12, 1))
    assert not workflow.overdue({"status": "reopened", "repair_eta": None}, date(2026, 12, 1))


def test_allowed_actions_by_role(insp):
    rid = new_report()
    assert workflow.allowed_actions(get(rid), "reviewer", None) == ["approve", "reject"]
    assert workflow.allowed_actions(get(rid), "viewer", None) == []
    assert workflow.allowed_actions(get(rid), "inspector", insp) == []
    d = workflow.decorate(get(rid), "admin", None)
    assert d["status_label"] == "Awaiting review" and d["overdue"] is False and d["allowed_actions"]


def test_backdated_transition_uses_the_given_time(insp):
    rid = new_report()
    r = act(rid, "approve", at="2026-11-01T12:00:00+00:00")
    assert r["approved_at"] == "2026-11-01T12:00:00+00:00"
    with session() as conn:
        entry = next(e for e in ledger.entries(conn, rid) if e["event_type"] == "workflow_approve")
        clock = conn.execute("SELECT submitted_at FROM service_clocks WHERE report_id = ?", (rid,)).fetchone()[0]
    assert entry["ts"] == clock == "2026-11-01T12:00:00+00:00"


def test_labels_cover_closed_reasons():
    assert workflow.label({"status": "closed", "closed_reason": "rejected"}) == "Closed (Rejected)"
    assert workflow.label({"status": "closed", "closed_reason": "no_repair_needed"}) == "Closed (Repair not needed)"
    assert workflow.label({"status": "repaired", "verification_status": "verified"}) == "Repaired (verified)"


# ---------------- migration of old statuses ----------------
OLD = [("approved", None, "awaiting_inspection", None), ("submitted", None, "awaiting_inspection", None),
       ("delivery_failed", None, "awaiting_inspection", None), ("fixed", "awaiting", "repaired", None),
       ("fixed", "verified", "repaired", None), ("fixed", "reopened", "reopened", None),
       ("rejected", None, "closed", "rejected"), ("pending_approval", None, "pending_approval", None)]


def test_old_statuses_migrate_once(db):
    ids = []
    for old, verification, *_ in OLD:
        rid = new_report()
        with session() as conn:  # an old database: the raw values a previous version wrote
            conn.execute("UPDATE reports SET status = ?, verification_status = ?, closed_at = ?, "
                         "service_request_id = 'sr-1' WHERE id = ?",
                         (old, verification, "2026-10-01T00:00:00+00:00" if old == "fixed" else None, rid))
            conn.commit()
        ids.append(rid)
    with session() as conn:
        workflow.migrate(conn)
    for rid, (old, verification, new, reason) in zip(ids, OLD):
        r = get(rid)
        assert (r["status"], r["closed_reason"]) == (new, reason), old
        assert r["service_request_id"] == "sr-1" and r["verification_status"] == verification
        if old == "fixed":
            assert r["closed_at"] == "2026-10-01T00:00:00+00:00" and r["repaired_at"] == r["closed_at"]
    with session() as conn:
        n = conn.execute("SELECT COUNT(*) FROM audit WHERE action = 'status_migrated'").fetchone()[0]
    assert n == len(OLD) - 1
    for _ in range(2):  # running it again (every connect does) changes nothing
        with session() as conn:
            assert workflow.migrate(conn) == 0
            assert conn.execute("SELECT COUNT(*) FROM audit WHERE action = 'status_migrated'").fetchone()[0] == n
    assert get(ids[5])["reopen_count"] == 1


def test_no_code_outside_the_workflow_writes_report_status():
    """core.workflow is the only writer of reports.status (string literals joined across lines before matching)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "roadsense"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "workflow.py" and path.parent.name == "core":
            continue
        text = re.sub(r"\"\s*\n\s*f?\"", "", path.read_text(encoding="utf-8"))
        for m in re.finditer(r"UPDATE reports SET(.*?)(WHERE|\"\"\"|$)", text, re.S | re.M):
            if re.search(r"(?<![\w.])status\s*=", m.group(1)):
                offenders.append(f"{path.relative_to(root)}: {m.group(0)[:80]}")
        if "set_status(" in text and path.name != "mock_open311.py":
            offenders.append(f"{path.relative_to(root)}: set_status")
    assert offenders == []
