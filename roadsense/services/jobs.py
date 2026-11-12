"""Durable job queue and scheduler for the agent API.

Jobs live in the `jobs` table, so a restart loses nothing: jobs that were running when the process died are queued
again on start (every job is idempotent: the MCP tools and the fallback pipeline are). One worker task owns the MCP
toolbox and runs jobs one at a time, because the GPU and the LLM rate limit are shared.

The scheduler (one tick a minute) queues the work nobody clicks for:
    retry_deliveries   approved reports whose delivery failed and whose backoff has passed
    push_updates       new confirmations on reports already filed with the authority
    follow_up          status checks at the authority (every ROADSENSE_FOLLOW_UP_MINUTES)
    sync_city          the city's own service requests from its open-data layer (ROADSENSE_EXTERNAL_SYNC_MINUTES)
    purge              the retention policy (hourly)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from ..common.config import settings
from ..common.db import now, session
from ..common.metrics import metrics

log = logging.getLogger("roadsense.jobs")
SCHEDULED = ("retry_deliveries", "push_updates", "follow_up", "sync_city", "purge")


def _decode(r) -> dict:
    d = dict(r)
    for k in ("args", "result"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


class Worker:
    def __init__(self):
        self.wake = asyncio.Event()
        self.tools: list[str] = []
        self.ready = asyncio.Event()
        self.last_run: dict[str, float] = {}
        self.toolbox = None

    # ---- queue ----
    def submit(self, kind: str, actor: str | None = None, **kwargs) -> str:
        job_id = uuid.uuid4().hex[:12]
        with session() as conn:
            conn.execute("INSERT INTO jobs (id, kind, args, status, actor, created) VALUES (?, ?, ?, 'queued', ?, ?)",
                         (job_id, kind, json.dumps(kwargs), actor, now()))
        metrics.inc("roadsense_jobs_submitted_total", kind=kind)
        try:
            self.wake.set()
        except RuntimeError:
            pass
        return job_id

    def get(self, job_id: str) -> dict | None:
        with session() as conn:
            r = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _decode(r) if r else None

    def recent(self, limit: int = 50) -> list[dict]:
        with session() as conn:
            return [_decode(r) for r in conn.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,))]

    def pending_kind(self, kind: str) -> bool:
        with session() as conn:
            return conn.execute("SELECT 1 FROM jobs WHERE kind = ? AND status IN ('queued', 'running')",
                                (kind,)).fetchone() is not None

    async def wait(self, job_id: str, timeout: float) -> dict:
        end = time.monotonic() + timeout
        job = self.get(job_id)
        while job and job["status"] in ("queued", "running") and time.monotonic() < end:
            await asyncio.sleep(0.25)
            job = self.get(job_id)
        return job or {"id": job_id, "status": "unknown"}

    def _next(self) -> dict | None:
        with session() as conn:
            r = conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created LIMIT 1").fetchone()
            if r is None:
                return None
            conn.execute("UPDATE jobs SET status = 'running', started = ?, attempts = attempts + 1 WHERE id = ?",
                         (now(), r["id"]))
        return _decode(r)

    def _finish(self, job_id: str, status: str, result=None, error: str | None = None) -> None:
        with session() as conn:
            conn.execute("UPDATE jobs SET status = ?, result = ?, error = ?, finished = ? WHERE id = ?",
                         (status, json.dumps(result, default=str) if result is not None else None, error, now(),
                          job_id))

    # ---- scheduler ----
    def schedule(self, now_s: float | None = None) -> list[str]:
        """Queue the periodic jobs that are due. Returns the kinds queued (testable without the event loop)."""
        now_s = now_s or time.time()
        due = []
        with session() as conn:
            if conn.execute("SELECT 1 FROM reports WHERE status = 'approved' AND (next_attempt_at IS NULL OR "
                            "next_attempt_at <= ?) AND delivery_attempts > 0", (now(),)).fetchone():
                due.append("retry_deliveries")
            if conn.execute("SELECT 1 FROM reports WHERE status = 'submitted' AND pending_update = 1").fetchone():
                due.append("push_updates")
        periods = {"follow_up": settings.follow_up_minutes * 60, "purge": 3600}
        if settings.city_sr_layer_url:
            periods["sync_city"] = settings.external_sync_minutes * 60
        for kind, period in periods.items():
            if period > 0 and now_s - self.last_run.get(kind, 0) >= period:
                due.append(kind)
        queued = []
        for kind in due:
            if not self.pending_kind(kind):
                self.submit(kind, actor="scheduler")
                queued.append(kind)
            self.last_run[kind] = now_s
        return queued

    # ---- execution ----
    async def execute(self, job: dict):
        from ..agents import orchestrator
        from ..core import external, privacy
        from ..mcp_servers import municipality_server

        kind, args, use_llm = job["kind"], job["args"] or {}, settings.llm_enabled
        if kind == "process_trip":
            return await orchestrator.process_trip(self.toolbox, args["trip_id"], use_llm)
        if kind == "file_report":
            return await orchestrator.file_report(self.toolbox, args["report_id"], use_llm)
        if kind == "follow_up":
            return await orchestrator.follow_up(self.toolbox, use_llm)
        if kind == "retry_deliveries":
            with session() as conn:
                ids = [r["id"] for r in conn.execute(
                    "SELECT id FROM reports WHERE status = 'approved' AND delivery_attempts > 0 AND "
                    "(next_attempt_at IS NULL OR next_attempt_at <= ?)", (now(),))]
            out = {}
            for rid in ids:
                try:
                    out[rid] = municipality_server.deliver(rid, actor="scheduler")
                except Exception as e:  # ToolError carries the reason; the next tick retries per backoff
                    out[rid] = {"ok": False, "error": str(e)[:300]}
            return out
        if kind == "push_updates":
            with session() as conn:
                ids = [r["id"] for r in conn.execute(
                    "SELECT id FROM reports WHERE status = 'submitted' AND pending_update = 1")]
            return {rid: municipality_server.push_update(rid, actor="scheduler") for rid in ids}
        if kind == "sync_city":
            with session() as conn:
                return external.sync_city_requests(conn)
        if kind == "purge":
            with session() as conn:
                return privacy.purge(conn)
        raise ValueError(f"unknown job kind {kind!r}")

    def recover(self) -> int:
        """Jobs left 'running' by a crash or restart go back to the queue."""
        with session() as conn:
            return conn.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'").rowcount

    async def run(self):
        from ..agents.mcp_client import Toolbox

        recovered = self.recover()
        if recovered:
            log.warning("re-queued %d interrupted job(s)", recovered)
        async with Toolbox() as toolbox:
            self.toolbox = toolbox
            self.tools = sorted(toolbox.tools)
            self.ready.set()
            last_tick = 0.0
            while True:
                if settings.scheduler_enabled and time.monotonic() - last_tick >= 60:
                    last_tick = time.monotonic()
                    try:
                        self.schedule()
                    except Exception:
                        log.exception("scheduler tick failed")
                job = self._next()
                if job is None:
                    self.wake.clear()
                    try:
                        await asyncio.wait_for(self.wake.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        pass
                    continue
                started = time.monotonic()
                try:
                    result = await self.execute(job)
                    self._finish(job["id"], "done", result)
                    metrics.inc("roadsense_jobs_total", kind=job["kind"], status="done")
                except Exception as e:
                    log.exception("job %s (%s) failed", job["id"], job["kind"])
                    self._finish(job["id"], "failed", error=f"{type(e).__name__}: {e}"[:1000])
                    metrics.inc("roadsense_jobs_total", kind=job["kind"], status="failed")
                metrics.observe("roadsense_job_seconds", time.monotonic() - started, kind=job["kind"])
