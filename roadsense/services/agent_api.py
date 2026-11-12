"""Agent service API: receives edge events, runs the agents, and takes the reviewers' decisions.

    python -m roadsense.services.agent_api            # http://127.0.0.1:8000, docs at /docs

Every endpoint except /health needs the service token. The web app (the only client a person uses) forwards the
signed-in user as X-RoadSense-User / X-RoadSense-Role; those headers are trusted only together with the token. The
evidence photo is the one exception: a road authority fetches it with a signed, expiring link (core.media).

Jobs are durable (services.jobs): a restart re-queues interrupted work, and a scheduler retries failed deliveries,
pushes updates, runs follow-up, syncs the city's own requests and applies the retention policy.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import ValidationError

from ..agents.llm import key_status
from ..common.config import settings
from ..common.db import REPORT_STATUSES, audit, now, row, session
from ..common.metrics import install as install_metrics
from ..common.metrics import metrics
from ..common.schemas import DamageEvent
from ..core import condition, external, geo, media, open311, privacy, reports
from .jobs import Worker

log = logging.getLogger("roadsense.api")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
REVIEW_ROLES = ("reviewer", "admin")

worker = Worker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(worker.run())
    yield
    task.cancel()


app = FastAPI(title="RoadSense agent API", lifespan=lifespan)
install_metrics(app, "agent_api")

_hits: dict[str, deque] = defaultdict(deque)
RATE_LIMIT = 240  # authenticated requests per minute per client


def require_token(request: Request, authorization: str = Header("")) -> None:
    if not secrets.compare_digest(authorization, f"Bearer {settings.api_token}"):
        raise HTTPException(401, "invalid or missing token")
    window, now_s = _hits[request.client.host if request.client else "?"], time.monotonic()
    while window and now_s - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "30"})
    window.append(now_s)


AUTH = [Depends(require_token)]


class Actor:
    def __init__(self, user: str | None, role: str | None):
        self.user, self.role = user, role

    @property
    def name(self) -> str:
        return self.user or "service"

    def need(self, roles: tuple[str, ...]) -> None:
        # a request without a user is a trusted service call (edge device, scripts); a person must hold the role
        if self.user is not None and self.role not in roles:
            raise HTTPException(403, f"needs one of the roles: {', '.join(roles)}")


def actor(x_roadsense_user: str | None = Header(None), x_roadsense_role: str | None = Header(None)) -> Actor:
    return Actor((x_roadsense_user or "")[:120] or None, (x_roadsense_role or "")[:20] or None)


@app.get("/health")
def health():
    return {"ok": True, "tools_ready": worker.ready.is_set(), "mcp_tools": worker.tools,
            "llm": {"enabled": settings.llm_enabled, "mode": settings.llm_mode, "models": settings.llm_models},
            "agents_enabled": settings.agents_enabled}


@app.get("/llm/status", dependencies=AUTH)
def llm_status():
    """OpenRouter quota for the configured key (free tier: 50 requests/day, 1,000/day after $10 of credit)."""
    return key_status()


@app.get("/system", dependencies=AUTH)
def system():
    """Configuration that matters for a deployment review: residency, retention, channels, warnings, jobs."""
    with session() as conn:
        jobs_by = dict(conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
        ext = conn.execute("SELECT COUNT(*), MAX(synced_at) FROM external_requests WHERE source = 'city_sr'").fetchone()
    return {
        "warnings": settings.production_warnings,
        "residency": {"mode": settings.data_residency, "llm_hosts": settings.residency_llm_hosts,
                      "llm_base_url": settings.openrouter_base_url, "images_to_llm": False},
        "retention": {"keep_raw_video": settings.keep_raw_video, "raw_retention_hours": settings.raw_retention_hours,
                      "rejected_media_days": settings.rejected_media_days,
                      "car_position_days": settings.car_position_days},
        "privacy": {"edge_redaction": True, "server_redaction": settings.server_redaction,
                    "face_plate_model": bool(settings.egoblur_weights), "signed_media_links": True,
                    "media_link_days": settings.media_link_days},
        "channels": {name: info.get("channel") for name, info in open311.directory().items()},
        "city_requests": {"configured": bool(settings.city_sr_layer_url), "count": ext[0], "last_sync": ext[1]},
        "scheduler": {"enabled": settings.scheduler_enabled, "follow_up_minutes": settings.follow_up_minutes,
                      "last_run": {k: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(v))
                                   for k, v in worker.last_run.items()}},
        "jobs": jobs_by,
    }


@app.get("/metrics", dependencies=AUTH, response_class=PlainTextResponse)
def prometheus():
    with session() as conn:
        reports_by = conn.execute("SELECT status, COUNT(*) FROM reports GROUP BY status").fetchall()
        events_by = conn.execute("SELECT status, COUNT(*) FROM events GROUP BY status").fetchall()
        jobs_by = conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
        failed = conn.execute("SELECT COUNT(*) FROM deliveries WHERE ok = 0").fetchone()[0]
    return metrics.render({
        "roadsense_reports": [({"status": s}, n) for s, n in reports_by],
        "roadsense_events": [({"status": s}, n) for s, n in events_by],
        "roadsense_jobs": [({"status": s}, n) for s, n in jobs_by],
        "roadsense_delivery_failures": [({}, failed)],
    })


@app.post("/events", dependencies=AUTH)
async def receive_event(event: str = Form(...), image: UploadFile = File(...)):
    try:
        e = DamageEvent.model_validate_json(event)
    except ValidationError as err:
        raise HTTPException(422, json.loads(err.json())) from err
    data = await image.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES or not data.startswith(b"\xff\xd8"):
        raise HTTPException(415, "image must be a JPEG under 5 MB")
    with session() as conn:  # check for a re-upload BEFORE touching the stored evidence
        if conn.execute("SELECT 1 FROM events WHERE id = ?", (e.id,)).fetchone():
            return {"accepted": e.id, "duplicate": True}
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    path = settings.media_dir / f"{e.id}.jpg"
    path.write_bytes(data)
    redaction = privacy.server_redact(path, e.box) if settings.server_redaction else {"checked": False}
    with session() as conn:
        snap = geo.snap_to_road(conn, e.lat, e.lon)  # the defect is on the road, not beside it
        e.lat, e.lon = snap["lat"], snap["lon"]
        conn.execute(
            "INSERT INTO events (id, trip_id, track_id, class_code, class_name, confidence, frames_seen, box_area_ratio,"
            " box, lat, lon, heading, captured_at, image_path, created_at, car_lat, car_lon, distance_m, width_m,"
            " position_uncertainty_m, jolt_g, server_redacted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.id, e.trip_id, e.track_id, e.class_code, e.class_name, e.confidence, e.frames_seen, e.box_area_ratio,
             json.dumps(e.box), e.lat, e.lon, e.heading, e.captured_at.isoformat(), str(path), now(), e.car_lat,
             e.car_lon, e.distance_m, e.width_m, e.position_uncertainty_m, e.jolt_g,
             int(bool(redaction.get("reapplied") or redaction.get("faces_or_plates")))))
        if snap["snapped"]:
            conn.execute("UPDATE events SET snap_m = ? WHERE id = ?", (snap["distance_m"], e.id))
        audit(conn, "edge", "event_received", f"event:{e.id}", {"class": e.class_code, "trip": e.trip_id,
                                                                  "redaction": redaction})
    metrics.inc("roadsense_events_received_total", class_code=e.class_code)
    return {"accepted": e.id}


@app.post("/trips/{trip_id}/process", dependencies=AUTH)
async def process_trip(trip_id: str, wait: bool = True, timeout: float = 600, who: Actor = Depends(actor)):
    job_id = worker.submit("process_trip", actor=who.name, trip_id=trip_id)
    return await worker.wait(job_id, timeout) if wait else worker.get(job_id)


@app.get("/jobs", dependencies=AUTH)
def jobs(limit: int = 50):
    return worker.recent(min(limit, 200))


@app.get("/jobs/{job_id}", dependencies=AUTH)
def job(job_id: str):
    j = worker.get(job_id)
    if j is None:
        raise HTTPException(404, "unknown job")
    return j


def _public_event(e) -> dict:
    return {k: v for k, v in dict(e).items() if k != "image_path"}


@app.get("/trips/{trip_id}/events", dependencies=AUTH)
def trip_events(trip_id: str):
    with session() as conn:
        rows = conn.execute("SELECT * FROM events WHERE trip_id = ? ORDER BY captured_at", (trip_id,)).fetchall()
    return [_public_event(r) for r in rows]


@app.get("/events/{event_id}", dependencies=AUTH)
def event(event_id: str):
    with session() as conn:
        e = row(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    if e is None:
        raise HTTPException(404, "unknown event")
    return _public_event(e)


@app.get("/stats", dependencies=AUTH)
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
        linked = one("SELECT COUNT(*) FROM events WHERE report_id IS NOT NULL AND suppressed_by IS NULL")
        n_reports = one("SELECT COUNT(*) FROM reports")
        return {
            "detections": sum(events.values()), "events": events, "reports": reports_by, "authorities": authorities,
            "false_alarms_removed": events.get("rejected", 0),
            "duplicates_merged": max(linked - n_reports, 0),
            "suppressed_after_rejection": one("SELECT COUNT(*) FROM events WHERE suppressed_by IS NOT NULL"),
            "multi_driver_reports": one("SELECT COUNT(*) FROM reports WHERE confirmations > 1"),
            "priority1_candidates": one("SELECT COUNT(*) FROM reports WHERE p1_candidate = 1"),
            "class_disputed": one("SELECT COUNT(*) FROM reports WHERE class_disputed = 1"),
            "known_to_city": one("SELECT COUNT(*) FROM reports WHERE external_ref IS NOT NULL"),
            "delivery_failed": one("SELECT COUNT(*) FROM reports WHERE status = 'delivery_failed' OR "
                                   "(status = 'approved' AND delivery_attempts > 0)"),
            "trips": len(trips),
            "llm_calls": sum((t.get("llm") or {}).get("calls", 0) for t in trips),
            "llm_tokens": sum((t.get("llm") or {}).get("prompt_tokens", 0) + (t.get("llm") or {}).get(
                "completion_tokens", 0) for t in trips),
            "agent_trips": sum(str(t.get("mode", "")).startswith("agents") for t in trips),
            "fallback_rate": round(sum(t.get("fallback_events", 0) for t in trips) /
                                   max(sum(sum((t.get("events") or {}).values()) for t in trips), 1), 3),
        }


@app.get("/trips", dependencies=AUTH)
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


@app.get("/reports/{report_id}", dependencies=AUTH)
def report_detail(report_id: int):
    """A report with its sightings, the agents' decision trail, deliveries, city matches and the payload."""
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if r is None:
            raise HTTPException(404, "unknown report")
        events = [_public_event(e) for e in conn.execute(
            "SELECT * FROM events WHERE report_id = ? ORDER BY created_at", (report_id,))]
        subjects = [f"report:{report_id}"] + [f"event:{e['id']}" for e in events]
        trail = [dict(a) for a in conn.execute(
            f"SELECT ts, actor, action, subject, detail FROM audit WHERE subject IN ({','.join('?' * len(subjects))}) "
            "ORDER BY id", subjects)]
        deliveries = [dict(d) for d in conn.execute("SELECT * FROM deliveries WHERE report_id = ? ORDER BY id",
                                                    (report_id,))]
        matches = [{k: x[k] for k in ("id", "source", "kind", "status", "reported_at", "description")}
                   for x in conn.execute("SELECT * FROM external_requests WHERE report_id = ?", (report_id,))]
        trend = condition.deterioration(conn, report_id)
    r.pop("approved_payload", None)
    p = open311.build_payload(r)
    return {"report": r, "events": events, "trail": trail, "payload": p, "payload_hash": open311.payload_hash(p),
            "deliveries": deliveries, "external": matches, "deterioration": trend}


@app.get("/trips/{trip_id}/reports", dependencies=AUTH)
def trip_reports(trip_id: str):
    with session() as conn:
        rows = conn.execute("SELECT DISTINCT r.* FROM reports r JOIN events e ON e.report_id = r.id "
                            "WHERE e.trip_id = ? ORDER BY r.priority DESC", (trip_id,)).fetchall()
    return [{k: v for k, v in dict(r).items() if k != "approved_payload"} for r in rows]


@app.get("/reports", dependencies=AUTH)
def list_reports(status: str | None = None):
    if status and status not in REPORT_STATUSES:
        raise HTTPException(400, f"status must be one of {REPORT_STATUSES}")
    with session() as conn:
        sql = "SELECT * FROM reports" + (" WHERE status = ?" if status else "") + " ORDER BY priority DESC"
        return [{k: v for k, v in dict(r).items() if k != "approved_payload"}
                for r in conn.execute(sql, (status,) if status else ())]


def _pending(conn, report_id: int) -> dict:
    r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    if r is None:
        raise HTTPException(404, "unknown report")
    if r["status"] != "pending_approval":
        raise HTTPException(409, f"report is {r['status']}")
    return r


@app.get("/reports/{report_id}/payload", dependencies=AUTH)
def payload(report_id: int):
    """Exactly what the road authority will receive if the reviewer approves, and its hash."""
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
    if r is None:
        raise HTTPException(404, "unknown report")
    p = json.loads(r["approved_payload"]) if r.get("approved_payload") else open311.build_payload(r)
    return {"payload": p, "payload_hash": open311.payload_hash(p), "status": r["status"]}


@app.post("/reports/{report_id}/approve", dependencies=AUTH)
async def approve(report_id: int, payload_hash: str = Body(..., embed=True), wait: bool = True,
                  who: Actor = Depends(actor)):
    """The reviewer approves the payload they were shown; it is rejected if it changed in between. The approved
    payload is stored and is exactly what delivery sends."""
    who.need(REVIEW_ROLES)
    with session() as conn:
        r = _pending(conn, report_id)
        p = open311.build_payload(r)
        current = open311.payload_hash(p)
        if not secrets.compare_digest(current, payload_hash):
            raise HTTPException(409, "the report changed since you reviewed it; reload and review again")
        reports.set_status(conn, report_id, "approved", who.name, approved_payload_hash=current,
                           approved_payload=json.dumps(p, sort_keys=True), approved_by=who.name, approved_at=now())
        reports.record_label(conn, report_id, "approved", who.name, r["class_code"])
    job_id = worker.submit("file_report", actor=who.name, report_id=report_id)
    return await worker.wait(job_id, 300) if wait else worker.get(job_id)


@app.post("/reports/{report_id}/reject", dependencies=AUTH)
def reject(report_id: int, who: Actor = Depends(actor)):
    who.need(REVIEW_ROLES)
    with session() as conn:
        _pending(conn, report_id)
        reports.record_label(conn, report_id, "rejected", who.name)
        return reports.set_status(conn, report_id, "rejected", who.name, rejected_by=who.name)


@app.post("/reports/{report_id}/class", dependencies=AUTH)
def reclassify(report_id: int, class_code: str = Body(..., embed=True), who: Actor = Depends(actor)):
    """Settle a class dispute (or correct the class) before approving. Resets the drafted description."""
    who.need(REVIEW_ROLES)
    with session() as conn:
        try:
            return reports.reclassify(conn, report_id, class_code, who.name)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e


@app.post("/reports/{report_id}/resend", dependencies=AUTH)
async def resend(report_id: int, wait: bool = True, who: Actor = Depends(actor)):
    """Retry delivery of an approved report now (after a failure, or once the authority's system is back)."""
    who.need(REVIEW_ROLES)
    with session() as conn:
        r = row(conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone())
        if r is None:
            raise HTTPException(404, "unknown report")
        if r["status"] not in ("approved", "delivery_failed"):
            raise HTTPException(409, f"report is {r['status']}; only approved reports can be (re)sent")
        reports.set_status(conn, report_id, "approved", who.name, next_attempt_at=None,
                           delivery_attempts=0 if r["status"] == "delivery_failed" else r["delivery_attempts"])
    job_id = worker.submit("file_report", actor=who.name, report_id=report_id)
    return await worker.wait(job_id, 300) if wait else worker.get(job_id)


@app.post("/follow-up", dependencies=AUTH)
async def run_follow_up(wait: bool = True, who: Actor = Depends(actor)):
    job_id = worker.submit("follow_up", actor=who.name)
    return await worker.wait(job_id, 300) if wait else worker.get(job_id)


@app.get("/audit", dependencies=AUTH)
def audit_log(limit: int = 200):
    with session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(limit, 2000),))]


@app.get("/notifications", dependencies=AUTH)
def notifications():
    with session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 50")]


# ---------- condition and deterioration ----------
@app.get("/conditions", dependencies=AUTH)
def conditions():
    """Segment-level condition ESTIMATE (0-100, PCI/PQI-style deducts) from open defects, worst first."""
    with session() as conn:
        return {"segments": condition.segments(conn), "estimate": True,
                "method": "100 minus capped, density-scaled deducts per open defect by class and severity band"}


@app.get("/reports/{report_id}/deterioration", dependencies=AUTH)
def deterioration(report_id: int):
    with session() as conn:
        return condition.deterioration(conn, report_id)


# ---------- city requests and third-party feeds ----------
@app.get("/external", dependencies=AUTH)
def external_list(source: str | None = None, limit: int = 200):
    with session() as conn:
        sql = "SELECT id, source, kind, status, lat, lon, description, reported_at, closed_at, report_id, synced_at " \
              "FROM external_requests" + (" WHERE source = ?" if source else "") + " ORDER BY synced_at DESC LIMIT ?"
        return [dict(r) for r in conn.execute(sql, (source, min(limit, 2000)) if source else (min(limit, 2000),))]


@app.post("/external/sync", dependencies=AUTH)
async def external_sync(wait: bool = True, who: Actor = Depends(actor)):
    job_id = worker.submit("sync_city", actor=who.name)
    return await worker.wait(job_id, 120) if wait else worker.get(job_id)


@app.post("/external/detections", dependencies=AUTH)
def external_detections(body: dict = Body(...)):
    """Aggregator ingest: {"source": "samsara", "items": [{"id", "lat", "lon", "kind"?, "reported_at"?}]}."""
    source = str(body.get("source") or "")
    if not source.replace("_", "").replace("-", "").isalnum() or len(source) > 40:
        raise HTTPException(400, "source must be a short alphanumeric name")
    items = body.get("items") or []
    if not isinstance(items, list) or len(items) > 5000:
        raise HTTPException(400, "items must be a list of at most 5000 sightings")
    try:
        clean = [{"id": str(i["id"])[:80], "lat": float(i["lat"]), "lon": float(i["lon"]),
                  **{k: str(i[k])[:300] for k in ("kind", "reported_at", "description", "status") if i.get(k)}}
                 for i in items]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"each item needs id, lat and lon: {e}") from e
    with session() as conn:
        return external.ingest_detections(conn, source, clean)


@app.post("/external/waze", dependencies=AUTH)
def external_waze(feed: dict = Body(...)):
    """A Waze for Cities alerts feed (JSON as downloaded from the Partner Hub)."""
    with session() as conn:
        return external.ingest_detections(conn, "waze", external.parse_waze_alerts(feed))


# ---------- ground truth ----------
@app.get("/labels", dependencies=AUTH)
def labels():
    with session() as conn:
        by = dict(conn.execute("SELECT label, COUNT(*) FROM labels GROUP BY label").fetchall())
        return {"counts": by, "total": sum(by.values())}


@app.get("/media/{event_id}.jpg")
def media_file(event_id: str, exp: int | None = None, sig: str | None = None, authorization: str = Header("")):
    """Evidence photo: with the service token, or with a signed, expiring link (what the road authority receives)."""
    if not event_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "bad id")
    if not (media.verify(event_id, exp, sig) or secrets.compare_digest(authorization, f"Bearer {settings.api_token}")):
        raise HTTPException(403, "link expired or invalid")
    path = settings.media_dir / f"{event_id}.jpg"
    if not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


def main():
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
