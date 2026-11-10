"""Level 2: the orchestrator agent and the agent loop.

The orchestrator handles a whole trip at once and sees the specialists as tools (delegate_to_vision, ...). It writes
a short plan first, then delegates. Each specialist runs its own tool-calling loop against its MCP allow-list and must
return a typed result. Batching per trip keeps LLM calls few, which matters on free OpenRouter models. After the run,
the outcome is checked against the database and any step the agents skipped is completed by the deterministic
fallback (a circuit breaker whose use is counted and reported), so a flaky model never loses a report.
"""
from __future__ import annotations

import json
import logging
import time

from ..common.db import audit, session
from . import fallback
from .contracts import validate
from .llm import LLM, LLMUnavailable
from .mcp_client import Toolbox
from .specialists import ALL, FILING, FOLLOW_UP, Specialist

log = logging.getLogger("roadsense.agents")

ORCHESTRATOR_PROMPT = (
    "You are the RoadSense orchestrator. RoadSense turns dashcam detections of road damage into verified reports for "
    "the road authority responsible. You coordinate specialist agents; you have no other tools. First write a short "
    "numbered plan for this trip in your message text, then delegate. The usual flow: 1) vision agent with all event "
    "ids; 2) location agent with the confirmed or disputed events (id, lat, lon); 3) triage agent with each of those "
    "events' id, severity and chosen jurisdiction with its reason; 4) filing agent to draft descriptions for the "
    "report ids triage created. Rejected events are false alarms: drop them. Never send reports to an authority: the "
    "driver approves first. If a specialist reports an error or low confidence, adapt the plan. Pass specialists "
    "complete instructions with every id and value they need. Finish with 2-3 plain sentences for the driver: what "
    "was confirmed or rejected and why, what was merged with existing reports, which authority each goes to, and what "
    "awaits their approval.")


def _audit(actor: str, action: str, subject: str | None, detail) -> None:
    with session() as conn:
        audit(conn, actor, action, subject, detail)


def _parse_args(raw: str | None) -> dict:
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {}
    except json.JSONDecodeError:
        return {}


async def run_agent(llm: LLM, system: str, task: str, tools: list[dict], call, actor: str, max_steps: int = 8,
                    output=None) -> str:
    """Generic tool-calling loop. `call(name, args)` executes a tool. With `output` (a pydantic model) the final
    answer is validated and the model gets one chance to fix it."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    allowed = {t["function"]["name"] for t in tools}
    corrected = False
    for _ in range(max_steps):
        msg = await llm.chat(messages, tools)
        calls = msg.tool_calls or []
        messages.append({"role": "assistant", "content": msg.content or "",
                         **({"tool_calls": [c.model_dump() for c in calls]} if calls else {})})
        if calls and (msg.content or "").strip():
            _audit(actor, "plan", None, msg.content.strip()[:1500])  # reasoning shown alongside tool calls
        if not calls:
            answer = msg.content or ""
            if output is not None:
                parsed, error = validate(output, answer)
                if parsed is None and not corrected:
                    corrected = True
                    _audit(actor, "invalid_output", None, error)
                    messages.append({"role": "user", "content": f"Your answer did not match the required JSON "
                                     f"schema: {error}. Reply with only the corrected JSON object."})
                    continue
                if parsed is not None:
                    answer = parsed.model_dump_json()
            _audit(actor, "answer", None, {"model": llm.last_model, "content": answer[:2000]})
            return answer
        for c in calls:
            args = _parse_args(c.function.arguments)
            if c.function.name not in allowed:
                result = {"error": f"tool {c.function.name} is not available to the {actor} agent"}
            else:
                try:
                    result = await call(c.function.name, args)
                except Exception as e:  # a failing tool is reported back to the model, not raised
                    result = {"error": f"{type(e).__name__}: {e}"}
            _audit(actor, f"tool:{c.function.name}", None, {"args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, default=str)[:6000]})
    _audit(actor, "stopped", None, f"reached {max_steps} steps")
    return json.dumps({"error": f"stopped after {max_steps} steps"})


async def run_specialist(llm: LLM, toolbox: Toolbox, spec: Specialist, task: str, max_steps: int = 10) -> str:
    _audit(f"agent:{spec.name}", "task", None, task[:1500])
    return await run_agent(llm, spec.system, task, toolbox.schemas(list(spec.tools)), toolbox.call,
                           f"agent:{spec.name}", max_steps=max_steps, output=spec.output)


def _delegate_tools() -> list[dict]:
    return [{"type": "function", "function": {
        "name": f"delegate_to_{s.name}", "description": f"{s.name.title()} agent: {s.purpose}",
        "parameters": {"type": "object", "required": ["instructions"],
                       "properties": {"instructions": {"type": "string",
                                                       "description": "Task with every id and value needed"}}}}}
        for s in ALL.values() if s.name != "follow_up"]


async def process_trip(toolbox: Toolbox, trip_id: str, use_llm: bool = True) -> dict:
    """Verify, locate, triage and draft every new event of a trip. Returns a summary and run metrics."""
    started = time.perf_counter()
    with session() as conn:
        events = [dict(r) for r in conn.execute(
            "SELECT id, class_code, class_name, confidence, frames_seen, lat, lon, width_m FROM events "
            "WHERE trip_id = ? AND status = 'received'", (trip_id,))]
    if not events:
        return {"trip_id": trip_id, "summary": "No new events.", "mode": "none"}

    summary, mode, stats, llm = None, "deterministic", {}, None
    if use_llm:
        try:
            llm = LLM()
            task = (f"Trip {trip_id} produced {len(events)} damage events:\n" +
                    "\n".join(json.dumps(e) for e in events))

            async def delegate(name: str, args: dict):
                spec = ALL[name.removeprefix("delegate_to_")]
                if spec.name == "filing":  # during a trip the filing agent may only draft, never send
                    spec = Specialist(spec.name, spec.purpose, ("reports_list", "reports_get", "reports_save_draft"),
                                      spec.prompt, spec.output)
                return await run_specialist(llm, toolbox, spec, args.get("instructions", ""))

            _audit("agent:orchestrator", "task", f"trip:{trip_id}", task[:1500])
            summary = await run_agent(llm, ORCHESTRATOR_PROMPT, task, _delegate_tools(), delegate,
                                      "agent:orchestrator", max_steps=8)
            stats = llm.stats()
            mode = "agents"
        except LLMUnavailable as e:
            _audit("agent:orchestrator", "llm_unavailable", f"trip:{trip_id}", str(e))
            log.warning("LLM unavailable, using deterministic pipeline: %s", e)
            if llm is not None and llm.calls > 1:  # the agents worked until the model became unavailable
                mode, stats = "agents (interrupted)", llm.stats()

    repaired = await fallback.complete_trip(toolbox, trip_id)  # circuit breaker: finish anything the agents skipped
    with session() as conn:
        counts = dict(conn.execute("SELECT status, COUNT(*) FROM events WHERE trip_id = ? GROUP BY status",
                                   (trip_id,)).fetchall())
    if not summary or summary.lstrip().startswith("{"):
        summary = fallback.trip_summary(trip_id)
    result = {"trip_id": trip_id, "summary": summary, "mode": mode, "events": counts,
              "fallback_events": repaired, "fallback_rate": round(repaired / len(events), 2),
              "seconds": round(time.perf_counter() - started, 1), "llm": stats}
    _audit("agent:orchestrator", "trip_done", f"trip:{trip_id}", result)
    return result


async def file_report(toolbox: Toolbox, report_id: int, use_llm: bool = True) -> dict:
    """Filing agent, triggered only by the driver's approval. The MCP tool re-checks approval and the payload hash."""
    if use_llm:
        try:
            await run_specialist(LLM(max_calls=6), toolbox, FILING, f"Report {report_id} was approved by the driver. "
                                 "Send it with city_submit_request.", max_steps=4)
        except LLMUnavailable as e:
            _audit("agent:filing", "llm_unavailable", f"report:{report_id}", str(e))
    return await fallback.file_report(toolbox, report_id)


async def follow_up(toolbox: Toolbox, use_llm: bool = True) -> dict:
    if use_llm:
        try:
            await run_specialist(LLM(max_calls=12), toolbox, FOLLOW_UP, "Check all submitted reports now.")
        except LLMUnavailable as e:
            _audit("agent:follow_up", "llm_unavailable", None, str(e))
    return await fallback.follow_up(toolbox)
