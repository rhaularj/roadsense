"""Agent service API: receives edge events, runs the agents, and takes the driver's approvals.

    python -m roadsense.services.agent_api            # http://127.0.0.1:8000, docs at /docs

One worker task owns the MCP toolbox and runs jobs one at a time (the GPU and free LLM rate limits are shared), so
the API stays responsive while long agent runs are queued.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from ..agents import orchestrator
from ..agents.llm import key_status
from ..agents.mcp_client import Toolbox
from ..common.config import settings
from ..common.db import REPORT_STATUSES, audit, now, row, session
from ..common.schemas import DamageEvent
from ..core import geo, open311, reports

log = logging.getLogger("roadsense.api")
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class Worker:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.jobs: dict[str, dict] = {}
        self.tools: list[str] = []
        self.ready = asyncio.Event()

    def submit(self, kind: str, **kwargs) -> str:
        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = {"id": job_id, "kind": kind, "args": kwargs, "status": "queued", "created": now()}
        self.queue.put_nowait(job_id)
        return job_id

    async def wait(self, job_id: str, timeout: float) -> dict:
        end = asyncio.get_running_loop().time() + timeout
        while self.jobs[job_id]["status"] in ("queued", "running"):
            if asyncio.get_running_loop().time() > end:
                break
            await asyncio.sleep(0.25)
        return self.jobs[job_id]

    async def run(self):
        async with Toolbox() as toolbox:
            self.tools = sorted(toolbox.tools)
            self.ready.set()
            while True:
                job = self.jobs[await self.queue.get()]
                job["status"] = "running"
                try:
                    use_llm = settings.llm_enabled
                    if job["kind"] == "process_trip":
                        job["result"] = await orchestrator.process_trip(toolbox, job["args"]["trip_id"], use_llm)
                    elif job["kind"] == "file_report":
                        job["result"] = await orchestrator.file_report(toolbox, job["args"]["report_id"], use_llm)
                    elif job["kind"] == "follow_up":
                        job["result"] = await orchestrator.follow_up(toolbox, use_llm)
                    job["status"] = "done"
                except Exception as e:
                    log.exception("job %s failed", job["id"])
                    job.update(status="failed", error=f"{type(e).__name__}: {e}")
                job["finished"] = now()


worker = Worker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(worker.run())
    yield
    task.cancel()


app = FastAPI(title="RoadSense agent API", lifespan=lifespan)


_hits: dict[str, deque] = defaultdict(deque)
RATE_LIMIT = 120  # authenticated requests per minute per client


def require_token(request: Request, authorization: str = Header("")) -> None:
    if not secrets.compare_digest(authorization, f"Bearer {settings.api_token}"):
        raise HTTPException(401, "invalid or missing token")
    window, now_s = _hits[request.client.host if request.client else "?"], time.monotonic()
    while window and now_s - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "30"})
    window.append(now_s)


@app.get("/health")
def health():
    return {"ok": True, "tools_ready": worker.ready.is_set(), "mcp_tools": worker.tools,
            "llm": {"enabled": settings.llm_enabled, "mode": settings.llm_mode, "models": settings.llm_models},
            "agents_enabled": settings.agents_enabled}


@app.get("/llm/status", dependencies=[Depends(require_token)])
def llm_status():
    """OpenRouter quota for the configured key (free tier: 50 requests/day, 1,000/day after $10 of credit)."""
    return key_status()


@app.post("/events", dependencies=[Depends(require_token)])
async def receive_event(event: str = Form(...), image: UploadFile = File(...)):
    try:
        e = DamageEvent.model_validate_json(event)
    except ValidationError as err:
        raise HTTPException(422, json.loads(err.json())) from err
    data = await image.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES or not data.startswith(b"\xff\xd8"):
        raise HTTPException(415, "image must be a JPEG under 5 MB")
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    path = settings.media_dir / f"{e.id}.jpg"
    path.write_bytes(data)
    with session() as conn:
        if conn.execute("SELECT 1 FROM events WHERE id = ?", (e.id,)).fetchone():
            return {"accepted": e.id, "duplicate": True}
        snap = geo.snap_to_road(conn, e.lat, e.lon)  # the defect is on the road, not beside it
        e.lat, e.lon = snap["lat"], snap["lon"]
        conn.execute(
            "INSERT INTO events (id, trip_id, track_id, class_code, class_name, confidence, frames_seen, box_area_ratio,"
            " box, lat, lon, heading, captured_at, image_path, created_at, car_lat, car_lon, distance_m, width_m,"
            " position_uncertainty_m) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.id, e.trip_id, e.track_id, e.class_code, e.class_name, e.confidence, e.frames_seen, e.box_area_ratio,
             json.dumps(e.box), e.lat, e.lon, e.heading, e.captured_at.isoformat(), str(path), now(), e.car_lat,
             e.car_lon, e.distance_m, e.width_m, e.position_uncertainty_m))
        if snap["snapped"]:
            conn.execute("UPDATE events SET snap_m = ? WHERE id = ?", (snap["distance_m"], e.id))
        audit(conn, "edge", "event_received", f"event:{e.id}", {"class": e.class_code, "trip": e.trip_id})
    return {"accepted": e.id}


@app.post("/trips/{trip_id}/process", dependencies=[Depends(require_token)])
async def process_trip(trip_id: str, wait: bool = True, timeout: float = 600):
    job_id = worker.submit("process_trip", trip_id=trip_id)
    return await worker.wait(job_id, timeout) if wait else worker.jobs[job_id]


@app.get("/jobs/{job_id}")
def job(job_id: str):
    if job_id not in worker.jobs:
        raise HTTPException(404, "unknown job")
    return worker.jobs[job_id]


@app.get("/trips/{trip_id}/events")
def trip_events(trip_id: str):
    with session() as conn:
        rows = conn.execute("SELECT * FROM events WHERE trip_id = ? ORDER BY captured_at", (trip_id,)).fetchall()
    return [{k: v for k, v in dict(r).items() if k != "image_path"} for r in rows]


@app.get("/events/{event_id}")
def event(event_id: str):
    with session() as conn:
        e = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    if e is None:
        raise HTTPException(404, "unknown event")
    e.pop("image_path", None)
    return e


@app.get("/stats")
def stats():
    """Outcome metrics for the overview: what the agents decided and what reached the road authorities."""
    with session() as conn:
        one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        events = dict(conn.execute("SELECT status, COUNT(*) FROM events GROUP BY status").fetchall())
        reports_by = dict(conn.execute("SELECT status, COUNT(*) FROM reports GROUP BY status").fetchall())
        authorities = dict(conn.execute("SELECT COALESCE(jurisdiction, 'unknown'), COUNT(*) FROM reports "
                                        "GROUP BY 1").fetchall())
        trips = [json.loads(r["detail"]) for r in conn.execute(
            "SELECT detail FROM audit WHERE action = 'trip_done' ORDER BY id")]
        linked = one("SELECT COUNT(*) FROM events WHERE report_id IS NOT NULL")
        n_reports = one("SELECT COUNT(*) FROM reports")
        return {
            "detections": sum(events.values()), "events": events, "reports": reports_by, "authorities": authorities,
            "false_alarms_removed": events.get("rejected", 0),
            "duplicates_merged": max(linked - n_reports, 0),
            "multi_driver_reports": one("SELECT COUNT(*) FROM reports WHERE confirmations > 1"),
            "priority1_candidates": one("SELECT COUNT(*) FROM reports WHERE p1_candidate = 1"),
            "class_disputed": one("SELECT COUNT(*) FROM reports WHERE class_disputed = 1"),
            "trips": len(trips),
            "llm_calls": sum((t.get("llm") or {}).get("calls", 0) for t in trips),
            "llm_tokens": sum((t.get("llm") or {}).get("prompt_tokens", 0) + (t.get("llm") or {}).get(
                "completion_tokens", 0) for t in trips),
            "agent_trips": sum(str(t.get("mode", "")).startswith("agents") for t in trips),
            "fallback_rate": round(sum(t.get("fallback_events", 0) for t in trips) /
                                   max(sum(sum((t.get("events") or {}).values()) for t in trips), 1), 3),
        }


@app.get("/trips")
def list_trips():
    """Trips newest first, with the orchestrator's run summary when it has finished."""
    with session() as conn:
        rows = conn.execute("SELECT trip_id, COUNT(*) AS events, MIN(captured_at) AS started, "
                            "SUM(status = 'rejected') AS rejected, SUM(status = 'processed') AS processed "
                            "FROM events GROUP BY trip_id ORDER BY MAX(created_at) DESC").fetchall()
        done = {}
        for r in conn.execute("SELECT subject, detail FROM audit WHERE action = 'trip_done' ORDER BY id"):
            done[r["subject"].removeprefix("trip:")] = json.loads(r["detail"])
    return [{**dict(r), "run": done.get(r["trip_id"])} for r in rows]


@app.get("/reports/{report_id}")
def report_detail(report_id: int):
    """A report with its sightings, the agents' decision trail and the payload the authority would receive."""
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if r is None:
            raise HTTPException(404, "unknown report")
        events = [{k: v for k, v in dict(e).items() if k != "image_path"}
                  for e in conn.execute("SELECT * FROM events WHERE report_id = ? ORDER BY created_at", (report_id,))]
        subjects = [f"report:{report_id}"] + [f"event:{e['id']}" for e in events]
        trail = [dict(a) for a in conn.execute(
            f"SELECT ts, actor, action, subject, detail FROM audit WHERE subject IN ({','.join('?' * len(subjects))}) "
            "ORDER BY id", subjects)]
    p = open311.build_payload(r)
    return {"report": r, "events": events, "trail": trail, "payload": p, "payload_hash": open311.payload_hash(p)}


@app.get("/trips/{trip_id}/reports")
def trip_reports(trip_id: str):
    with session() as conn:
        rows = conn.execute("SELECT DISTINCT r.* FROM reports r JOIN events e ON e.report_id = r.id "
                            "WHERE e.trip_id = ? ORDER BY r.priority DESC", (trip_id,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/reports")
def list_reports(status: str | None = None):
    if status and status not in REPORT_STATUSES:
        raise HTTPException(400, f"status must be one of {REPORT_STATUSES}")
    with session() as conn:
        sql = "SELECT * FROM reports" + (" WHERE status = ?" if status else "") + " ORDER BY priority DESC"
        return [dict(r) for r in conn.execute(sql, (status,) if status else ())]


def _pending(conn, report_id: int) -> dict:
    r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    if r is None:
        raise HTTPException(404, "unknown report")
    if r["status"] != "pending_approval":
        raise HTTPException(409, f"report is {r['status']}")
    return r


@app.get("/reports/{report_id}/payload")
def payload(report_id: int):
    """Exactly what the road authority will receive if the driver approves, and its hash."""
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    if r is None:
        raise HTTPException(404, "unknown report")
    p = open311.build_payload(r)
    return {"payload": p, "payload_hash": open311.payload_hash(p), "status": r["status"]}


@app.post("/reports/{report_id}/approve", dependencies=[Depends(require_token)])
async def approve(report_id: int, payload_hash: str = Body(..., embed=True), wait: bool = True):
    """The driver approves the payload they were shown; it is rejected if it changed in between."""
    with session() as conn:
        r = _pending(conn, report_id)
        current = open311.payload_hash(open311.build_payload(r))
        if not secrets.compare_digest(current, payload_hash):
            raise HTTPException(409, "the report changed since you reviewed it; reload and review again")
        reports.set_status(conn, report_id, "approved", "driver", approved_payload_hash=current)
    job_id = worker.submit("file_report", report_id=report_id)
    return await worker.wait(job_id, 300) if wait else worker.jobs[job_id]


@app.post("/reports/{report_id}/reject", dependencies=[Depends(require_token)])
def reject(report_id: int):
    with session() as conn:
        _pending(conn, report_id)
        return reports.set_status(conn, report_id, "rejected", "driver")


@app.post("/follow-up", dependencies=[Depends(require_token)])
async def run_follow_up(wait: bool = True):
    job_id = worker.submit("follow_up")
    return await worker.wait(job_id, 300) if wait else worker.jobs[job_id]


@app.get("/audit", dependencies=[Depends(require_token)])
def audit_log(limit: int = 200):
    with session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(limit, 2000),))]


@app.get("/notifications")
def notifications():
    with session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 50")]


@app.get("/media/{event_id}.jpg")
def media(event_id: str):
    # Event ids carry a random suffix and images are privacy-redacted on the device; the city's 311 system links here.
    if not event_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "bad id")
    path = settings.media_dir / f"{event_id}.jpg"
    if not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="image/jpeg")


def main():
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
