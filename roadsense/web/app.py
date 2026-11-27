"""RoadSense web app: the product UI (single-page app) and its backend-for-frontend.

    python -m roadsense.web.app            # http://127.0.0.1:7860 (agent API and mock 311 must be running)

People sign in here (web.auth); the browser never sees the agent API token: this server holds it, checks the user's
role, and forwards a fixed set of calls with the user's identity. It also runs the edge pipeline for uploaded dashcam
videos (the server plays the role of the in-car device), reports progress, and deletes the raw video afterwards.
"""
from __future__ import annotations

import argparse
import json
import logging
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import cv2
import httpx
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from ..common.config import settings
from ..common.detectors import CLASSES, Detector
from ..common.metrics import install as install_metrics
from ..common.metrics import metrics
from ..core.privacy import delete_trip_raw
from ..edge.gps import haversine_m, simulate_route, write_gpx
from ..edge.outbox import upload as upload_outbox
from ..edge.process_video import process_video
from ..edge.redact import annotate
from ..edge.simulate_gps import HALIFAX_ROUTE
from . import auth

STATIC = Path(__file__).with_name("static")
COLOR_BY_CODE = {code: color for code, _, color in CLASSES.values()}
MAX_VIDEO_BYTES = 500 * 1024 * 1024
log = logging.getLogger("roadsense.web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auth_enabled:
        auth.bootstrap_admin()
    auth.seed_inspectors()
    yield


app = FastAPI(title="RoadSense", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(auth.router)
install_metrics(app, "web")
jobs: dict[str, dict] = {}
_gpu = threading.Lock()  # one edge job at a time on the 4 GB GPU


@app.middleware("http")
async def security(request: Request, call_next):
    """Sign-in for every API call, CSRF token for every change, and security headers on every response."""
    path = request.url.path
    if path.startswith("/api/") and not (path == "/api/me" or path.startswith("/api/auth/")):
        user = auth.current_user(request)
        if user is None:
            return JSONResponse({"detail": "sign in required"}, status_code=401)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), user["csrf"]):
            return JSONResponse({"detail": "missing or invalid CSRF token; reload the page"}, status_code=403)
        request.state.user = user
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https://server.arcgisonline.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
    if settings.cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def need(request: Request, perm: str) -> dict:
    user = request.state.user
    if not auth.allowed(user, perm):
        raise HTTPException(403, f"your role ({user['role']}) cannot do this")
    return user


_http_lock = threading.Lock()
_http: httpx.Client | None = None


def http() -> httpx.Client:
    """One pooled client for the whole process. Building an httpx.Client loads the TLS trust store (about 1.5 s on
    Windows), so a client per call made every page wait several seconds for four local requests."""
    global _http
    with _http_lock:
        if _http is None or _http.is_closed:
            _http = httpx.Client(timeout=60, limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
        return _http


def agent(method: str, path: str, user: dict | None = None, **kw):
    headers = {"Authorization": f"Bearer {settings.api_token}"}
    if user:
        headers.update({"X-RoadSense-User": user["email"], "X-RoadSense-Role": user["role"],
                        "X-RoadSense-User-Id": str(user["id"])})
    try:
        r = http().request(method, settings.agent_api_url.rstrip("/") + path, headers=headers,
                           timeout=kw.pop("timeout", 60), **kw)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"agent service unavailable: {e}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.json().get("detail", r.text) if r.headers.get(
            "content-type", "").startswith("application/json") else r.text)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text


@lru_cache(maxsize=1)
def edge_detector() -> Detector:
    return Detector(settings.weights_dir / settings.edge_weights, settings.device)


# ---------- read APIs (forwarded) ----------
@app.get("/api/overview")
def overview():
    stats = agent("GET", "/stats")
    reports = agent("GET", "/reports")
    trips = agent("GET", "/trips")[:6]
    reports = [{k: r.get(k) for k in ("id", "class_name", "address", "jurisdiction", "status", "status_label",
                                      "confirmations", "lat", "lon", "overdue", "repair_eta", "closed_reason",
                                      "verification_status")} for r in reports]
    activity = [a for a in agent("GET", "/audit", params={"limit": 400})
                if a["action"].startswith(("verdict_", "report_", "ledger_workflow_", "trip_done"))][:12]
    return {"stats": stats, "reports": reports, "trips": trips, "activity": activity}


@app.get("/api/reports")
def reports(request: Request, status: str | None = None, inspector_id: str | None = None, overdue: bool = False):
    """Every report, with what the signed-in person may do next. inspector_id=me: my inspections."""
    params = {k: v for k, v in (("status", status), ("inspector_id", inspector_id),
                                ("overdue", "true" if overdue else None)) if v}
    return agent("GET", "/reports", request.state.user, params=params or None)


@app.get("/api/reports/{report_id}")
def report(report_id: int, request: Request):
    return agent("GET", f"/reports/{report_id}", request.state.user)


@app.get("/api/trips")
def trips():
    return agent("GET", "/trips")


@app.get("/api/trips/{trip_id}")
def trip(trip_id: str, request: Request):
    return {"events": agent("GET", f"/trips/{trip_id}/events"),
            "reports": agent("GET", f"/trips/{trip_id}/reports", request.state.user)}


@app.get("/api/activity")
def activity(limit: int = 300):
    return agent("GET", "/audit", params={"limit": min(limit, 1000)})


@app.get("/api/conditions")
def conditions():
    return agent("GET", "/conditions")


@app.get("/api/forecast")
def forecast():
    return agent("GET", "/forecast")


@app.get("/api/forecast/segments/{segment_id}")
def forecast_segment(segment_id: str):
    return agent("GET", f"/forecast/segments/{segment_id}")


@app.get("/api/forecast/evaluation")
def forecast_evaluation(kind: str | None = None):
    return agent("GET", "/forecast/evaluation", params={"kind": kind} if kind else None)


@app.get("/api/forecast/history")
def forecast_history():
    return agent("GET", "/forecast/history")


@app.get("/api/risk")
def risk(request: Request):
    return agent("GET", "/risk", params=dict(request.query_params))


@app.get("/api/external")
def external(source: str | None = None):
    return agent("GET", "/external", params={"source": source} if source else None)


@app.get("/api/authorities")
def authorities():
    try:
        city = http().get(f"{settings.open311_url}/requests.json", timeout=10).json()
    except (httpx.HTTPError, ValueError):
        city = []
    referrals = []
    for f in sorted((settings.data_dir / "referrals").glob("REF-*.json"), reverse=True):
        d = json.loads(f.read_text(encoding="utf-8"))
        referrals.append({"id": f.stem, "to": d.get("to"), "contact": d.get("contact"), "address": d.get(
            "address_string"), "description": d.get("description"), "service_code": d.get("service_code")})
    return {"open311": city if isinstance(city, list) else [], "referrals": referrals,
            "open311_inbox": settings.open311_inbox_url, "notifications": agent("GET", "/notifications")}


_llm_cache: dict = {}


@app.get("/api/system")
def system():
    if time.monotonic() - _llm_cache.get("at", -1e9) > 120:  # the quota lookup calls OpenRouter: cache it
        _llm_cache.update(at=time.monotonic(), value=agent("GET", "/llm/status"))
    deployment = agent("GET", "/system")
    return {"health": agent("GET", "/health"), "llm": _llm_cache["value"], "deployment": deployment,
            "auth": {"enabled": settings.auth_enabled, "sso": bool(settings.oidc_issuer and settings.oidc_client_id),
                     "secure_cookies": settings.cookie_secure},
            "privacy": {"edge_redaction": True, "images_to_llm": False, "approval_required": True,
                        "server_redaction": deployment["privacy"]["server_redaction"],
                        "signed_media_links": True, "raw_video_deleted": not settings.keep_raw_video}}


# ---------- service standards ----------
@app.get("/api/service-standards")
def standards_dashboard(request: Request):
    keys = ("authority", "neighbourhood", "damage", "priority", "status", "date_from", "date_to")
    return agent("GET", "/service-standards/dashboard",
                 params={k: request.query_params[k] for k in keys if request.query_params.get(k)})


@app.get("/api/service-standards/rules")
def standards_rules():
    return agent("GET", "/service-standards/rules")


@app.post("/api/service-standards/rules")
def standards_create(request: Request, body: dict = Body(...)):
    return agent("POST", "/service-standards/rules", need(request, "admin"), json=body)


@app.patch("/api/service-standards/rules/{rule_id}")
def standards_update(rule_id: int, request: Request, body: dict = Body(...)):
    return agent("PATCH", f"/service-standards/rules/{rule_id}", need(request, "admin"), json=body)


@app.post("/api/service-standards/holidays")
def standards_add_holiday(request: Request, body: dict = Body(...)):
    return agent("POST", "/service-standards/holidays", need(request, "admin"), json=body)


@app.delete("/api/service-standards/holidays/{day}")
def standards_remove_holiday(day: str, request: Request, authority: str | None = None):
    return agent("DELETE", f"/service-standards/holidays/{day}", need(request, "admin"),
                 params={"authority": authority} if authority else None)


@app.get("/api/service-standards/reports/{report_id}")
def standards_timeline(report_id: int, request: Request):
    return agent("GET", f"/service-standards/reports/{report_id}", need(request, "review"))


@app.post("/api/service-standards/reports/{report_id}/events")
def standards_record(report_id: int, request: Request, body: dict = Body(...)):
    return agent("POST", f"/service-standards/reports/{report_id}/events", need(request, "review"), json=body)


@app.get("/api/service-standards/integrity")
def standards_integrity(request: Request, report_id: int | None = None):
    return agent("GET", "/service-standards/integrity", need(request, "review"),
                 params={"report_id": report_id} if report_id else None)


# ---------- Road Inspection Assistant (read-only; conversations are per person) ----------
@app.get("/api/assistant/capabilities")
def assistant_capabilities(request: Request):
    return agent("GET", "/assistant/capabilities", need(request, "read"))


@app.post("/api/assistant/chat")
def assistant_chat(request: Request, body: dict = Body(...)):
    user = need(request, "read")
    question, cid = body.get("question"), body.get("conversation_id")
    if not isinstance(question, str) or len(question) > 2000:
        raise HTTPException(422, "question must be text (at most 500 characters are used)")
    return agent("POST", "/assistant/chat", user, json={"question": question, "conversation_id": cid or None},
                 timeout=120)


@app.get("/api/assistant/conversations")
def assistant_conversations(request: Request):
    return agent("GET", "/assistant/conversations", need(request, "read"))


def _cid(cid: str) -> str:
    if not (len(cid) == 16 and all(c in "0123456789abcdef" for c in cid)):
        raise HTTPException(404, "unknown conversation")
    return cid


@app.get("/api/assistant/conversations/{cid}")
def assistant_conversation(cid: str, request: Request):
    _cid(cid)
    return agent("GET", f"/assistant/conversations/{cid}", need(request, "read"))


@app.delete("/api/assistant/conversations/{cid}")
def assistant_delete(cid: str, request: Request):
    _cid(cid)
    return agent("DELETE", f"/assistant/conversations/{cid}", need(request, "read"))


@app.get("/api/labels")
def labels():
    return agent("GET", "/labels")


# ---------- actions ----------
@app.post("/api/reports/{report_id}/approve")
def approve(report_id: int, request: Request, body: dict = Body(...)):
    user = need(request, "review")
    return agent("POST", f"/reports/{report_id}/approve", user, json={"payload_hash": body.get("payload_hash", "")},
                 timeout=300)


@app.post("/api/reports/{report_id}/reject")
def reject(report_id: int, request: Request, body: dict | None = Body(None)):
    return agent("POST", f"/reports/{report_id}/reject", need(request, "review"),
                 json={"reason": str((body or {}).get("reason") or "")[:500]})


@app.post("/api/reports/{report_id}/assign")
def assign(report_id: int, request: Request, body: dict = Body(...)):
    return agent("POST", f"/reports/{report_id}/assign", need(request, "review"),
                 json={"inspector_id": body.get("inspector_id")})


MAX_PHOTO_BYTES = 5 * 1024 * 1024


async def _photo_file(photo: UploadFile | None) -> dict | None:
    if photo is None or not photo.filename:
        return None
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "photo larger than 5 MB")
    return {"photo": (Path(photo.filename).name[:80], data, photo.content_type or "application/octet-stream")}


@app.post("/api/reports/{report_id}/inspection")
async def inspection(report_id: int, request: Request, outcome: str = Form(...), repair_eta: str = Form(""),
                     severity_band: str = Form(""), notes: str = Form(""), photo: UploadFile | None = File(None)):
    """The inspector's outcome, with an optional photo (JPEG/PNG, 5 MB; re-encoded and privacy-checked)."""
    user = need(request, "inspect")
    return agent("POST", f"/reports/{report_id}/inspection", user, files=await _photo_file(photo),
                 data={"outcome": outcome, "repair_eta": repair_eta, "severity_band": severity_band,
                       "notes": notes[:1000]})


@app.post("/api/reports/{report_id}/repaired")
async def repaired(report_id: int, request: Request, notes: str = Form(""), photo: UploadFile | None = File(None)):
    user = need(request, "inspect")
    return agent("POST", f"/reports/{report_id}/repaired", user, files=await _photo_file(photo),
                 data={"notes": notes[:1000]})


@app.post("/api/reports/{report_id}/reopen")
def reopen(report_id: int, request: Request, body: dict = Body(...)):
    return agent("POST", f"/reports/{report_id}/reopen", need(request, "inspect"),
                 json={"reason": str(body.get("reason") or "")[:500]})


@app.patch("/api/reports/{report_id}/eta")
def reschedule(report_id: int, request: Request, body: dict = Body(...)):
    return agent("PATCH", f"/reports/{report_id}/eta", need(request, "inspect"),
                 json={"repair_eta": body.get("repair_eta"), "reason": str(body.get("reason") or "")[:500]})


@app.post("/api/reports/{report_id}/class")
def reclassify(report_id: int, request: Request, body: dict = Body(...)):
    return agent("POST", f"/reports/{report_id}/class", need(request, "review"),
                 json={"class_code": body.get("class_code", "")})


@app.post("/api/reports/{report_id}/resend")
def resend(report_id: int, request: Request):
    return agent("POST", f"/reports/{report_id}/resend", need(request, "review"), timeout=300)


@app.post("/api/trips/{trip_id}/process")
def process(trip_id: str, request: Request):
    """Re-run the agents on a trip whose events were uploaded but never processed (store-and-forward recovery)."""
    return agent("POST", f"/trips/{trip_id}/process", need(request, "upload"), params={"wait": False})


@app.post("/api/follow-up")
def follow_up(request: Request):
    return agent("POST", "/follow-up", need(request, "review"), timeout=300)


@app.post("/api/forecast/run")
def forecast_run(request: Request, force: bool = False):
    return agent("POST", "/forecast/run", need(request, "review"), params={"force": force}, timeout=180)


@app.post("/api/risk/run")
def risk_run(request: Request):
    return agent("POST", "/risk/run", need(request, "review"), timeout=180)


@app.post("/api/external/sync")
def external_sync(request: Request):
    return agent("POST", "/external/sync", need(request, "admin"), timeout=120)


@app.get("/metrics", response_class=PlainTextResponse)
def web_metrics(request: Request):
    user = auth.current_user(request)
    if not user or not auth.allowed(user, "admin"):
        raise HTTPException(403, "admins only")
    return metrics.render()


# ---------- media ----------
@app.get("/api/media/pass/{pass_id}.jpg")
def pass_media(pass_id: str):
    """A repair-verification frame with the watched road region outlined."""
    if not pass_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "bad id")
    frame = cv2.imread(str(settings.media_dir / f"pass-{pass_id}.jpg"))
    if frame is None:
        raise HTTPException(404, "not found")
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})



@app.get("/api/media/photo/{photo_id}.jpg")
def staff_photo(photo_id: str):
    """An inspection or repair photo, stored re-encoded and privacy-checked by the agent service."""
    if not photo_id.isalnum():
        raise HTTPException(400, "bad id")
    path = settings.media_dir / f"photo-{photo_id}.jpg"
    if not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/media/{event_id}.jpg")
def media(event_id: str, crop: bool = False):
    """The privacy-redacted frame with the detection drawn on it (optionally cropped around the damage)."""
    if not event_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "bad id")
    frame = cv2.imread(str(settings.media_dir / f"{event_id}.jpg"))
    if frame is None:
        raise HTTPException(404, "not found")
    try:
        e = agent("GET", f"/events/{event_id}")
    except HTTPException:
        e = None
    if e:
        box = json.loads(e["box"])
        frame = annotate(frame, box, f"{e['class_name']} {e['confidence']:.2f}", COLOR_BY_CODE.get(e["class_code"]))
        if crop:
            x1, y1, x2, y2 = box
            h, w = frame.shape[:2]
            pad = max(x2 - x1, y2 - y1)
            frame = frame[max(y1 - pad, 0):min(y2 + pad, h), max(x1 - pad, 0):min(x2 + pad, w)]
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


# ---------- trips: upload a dashcam video and run the edge device + agents ----------
def _simulated_gps(video: Path, out: Path) -> Path:
    cap = cv2.VideoCapture(str(video))
    seconds = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    cap.release()
    length = sum(haversine_m(*a, *b) for a, b in zip(HALIFAX_ROUTE, HALIFAX_ROUTE[1:]))
    write_gpx(simulate_route(HALIFAX_ROUTE, min(max(length / max(seconds, 1) * 3.6, 5), 80)), out)
    return out


def _run_trip(job: dict, video: Path, gps: Path | None, user: dict):
    def step(name: str, progress: float, detail: str = ""):
        job.update(step=name, progress=round(progress, 3), detail=detail)

    try:
        with _gpu:
            step("edge", 0.0, "Loading the YOLOv8m edge detector")
            gps = gps or _simulated_gps(video, video.with_suffix(".gpx"))
            try:  # closed reports to re-observe on the way (repair verification); none if the API is down
                watch = agent("GET", "/verification/watchlist")
            except HTTPException:
                watch = []
            stats = process_video(video, gps, job["trip_id"], detector=edge_detector(),
                                  progress=lambda f, msg: step("edge", f, msg), watch=watch)
        job["edge"] = stats
        # the raw video and GPS track are no longer needed: only privacy-blurred frames leave this step
        job["raw_deleted"] = delete_trip_raw(video.parent)
        step("upload", 1.0, f"Uploading {stats['events']} privacy-blurred frames")
        job["upload"] = upload_outbox(Path(stats["outbox"]))
        step("agents", 0.0, "Agents are verifying, locating and triaging")
        run = agent("POST", f"/trips/{job['trip_id']}/process", user, params={"wait": False})
        while run["status"] in ("queued", "running"):
            time.sleep(2)
            run = agent("GET", f"/jobs/{run['id']}")
            events = agent("GET", f"/trips/{job['trip_id']}/events")
            done = sum(e["status"] in ("processed", "rejected") for e in events)
            step("agents", done / max(len(events), 1), f"{done}/{len(events)} detections decided")
        job["result"] = run.get("result")
        job["status"] = "done" if run["status"] == "done" else "failed"
        job["error"] = run.get("error")
        step("done", 1.0, (run.get("result") or {}).get("summary", ""))
    except Exception as e:  # surfaced in the UI
        log.exception("trip %s failed", job["trip_id"])
        job.update(status="failed", error=f"{type(e).__name__}: {e}")
        delete_trip_raw(video.parent)


@app.post("/api/trips")
async def create_trip(request: Request, video: UploadFile = File(...), gps: UploadFile | None = File(None),
                      simulate: bool = Form(True)):
    user = need(request, "upload")
    if not (video.filename or "").lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
        raise HTTPException(415, "video must be .mp4, .mov, .avi or .mkv")
    trip_id = time.strftime("trip%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)  # unique even in the same second
    folder = settings.data_dir / "uploads" / trip_id
    folder.mkdir(parents=True, exist_ok=True)
    video_path = folder / f"video{Path(video.filename).suffix.lower()}"
    size = 0
    with open(video_path, "wb") as f:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                f.close()
                delete_trip_raw(folder)
                raise HTTPException(413, "video larger than 500 MB")
            f.write(chunk)
    gps_path = None
    if gps is not None and gps.filename and not simulate:
        if not gps.filename.lower().endswith((".gpx", ".csv")):
            raise HTTPException(415, "GPS track must be .gpx or .csv")
        gps_path = folder / f"track{Path(gps.filename).suffix.lower()}"
        gps_path.write_bytes(await gps.read(20 * 1024 * 1024))
    job = {"id": uuid.uuid4().hex[:10], "trip_id": trip_id, "status": "running", "step": "queued", "progress": 0,
           "detail": "Queued", "video": video.filename, "gps": gps.filename if gps_path else "simulated Halifax route",
           "by": user["email"]}
    jobs[job["id"]] = job
    threading.Thread(target=_run_trip, args=(job, video_path, gps_path, user), daemon=True).start()
    return job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "unknown job")
    return jobs[job_id]


@app.get("/api/jobs")
def job_list():
    return sorted(jobs.values(), key=lambda j: j["trip_id"], reverse=True)


# ---------- single-page app ----------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith(("api/", "static/", "auth/")):  # unknown API or asset paths are errors, not the app shell
        raise HTTPException(404, "not found")
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


def main():
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7860)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
