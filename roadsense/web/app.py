"""RoadSense web app: the product UI (single-page app) and its backend-for-frontend.

    python -m roadsense.web.app            # http://127.0.0.1:7860 (agent API and mock 311 must be running)

The browser never sees the agent API token: this server holds it and forwards a fixed set of calls. It also runs
the edge pipeline for uploaded dashcam videos (the laptop plays the role of the in-car device) and reports progress.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path

import cv2
import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ..common.config import settings
from ..common.detectors import CLASSES, Detector
from ..edge.gps import haversine_m, simulate_route, write_gpx
from ..edge.outbox import upload as upload_outbox
from ..edge.process_video import process_video
from ..edge.redact import annotate
from ..edge.simulate_gps import HALIFAX_ROUTE

STATIC = Path(__file__).with_name("static")
COLOR_BY_CODE = {code: color for code, _, color in CLASSES.values()}
MAX_VIDEO_BYTES = 500 * 1024 * 1024
app = FastAPI(title="RoadSense", docs_url=None, redoc_url=None)
jobs: dict[str, dict] = {}
_gpu = threading.Lock()  # one edge job at a time on the 4 GB GPU


def agent(method: str, path: str, **kw):
    with httpx.Client(base_url=settings.agent_api_url, timeout=kw.pop("timeout", 60),
                      headers={"Authorization": f"Bearer {settings.api_token}"}) as c:
        try:
            r = c.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"agent service unavailable: {e}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.json().get("detail", r.text) if r.headers.get(
            "content-type", "").startswith("application/json") else r.text)
    return r.json()


@lru_cache(maxsize=1)
def edge_detector() -> Detector:
    return Detector(settings.weights_dir / settings.edge_weights, settings.device)


# ---------- read APIs (forwarded) ----------
@app.get("/api/overview")
def overview():
    stats = agent("GET", "/stats")
    reports = agent("GET", "/reports")
    trips = agent("GET", "/trips")[:6]
    activity = [a for a in agent("GET", "/audit", params={"limit": 400})
                if a["action"].startswith(("verdict_", "report_", "status_", "trip_done"))][:12]
    return {"stats": stats, "reports": reports, "trips": trips, "activity": activity}


@app.get("/api/reports")
def reports(status: str | None = None):
    return agent("GET", "/reports", params={"status": status} if status else None)


@app.get("/api/reports/{report_id}")
def report(report_id: int):
    return agent("GET", f"/reports/{report_id}")


@app.get("/api/trips")
def trips():
    return agent("GET", "/trips")


@app.get("/api/trips/{trip_id}")
def trip(trip_id: str):
    return {"events": agent("GET", f"/trips/{trip_id}/events"), "reports": agent("GET", f"/trips/{trip_id}/reports")}


@app.get("/api/activity")
def activity(limit: int = 300):
    return agent("GET", "/audit", params={"limit": min(limit, 1000)})


@app.get("/api/authorities")
def authorities():
    try:
        city = httpx.get(f"{settings.open311_url}/requests.json", timeout=10).json()
    except httpx.HTTPError:
        city = []
    referrals = []
    for f in sorted((settings.data_dir / "referrals").glob("REF-*.json"), reverse=True):
        d = json.loads(f.read_text(encoding="utf-8"))
        referrals.append({"id": f.stem, "to": d.get("to"), "contact": d.get("contact"), "address": d.get(
            "address_string"), "description": d.get("description"), "service_code": d.get("service_code")})
    return {"open311": city, "referrals": referrals, "open311_inbox": settings.open311_url,
            "notifications": agent("GET", "/notifications")}


_llm_cache: dict = {}


@app.get("/api/system")
def system():
    if time.monotonic() - _llm_cache.get("at", -1e9) > 120:  # the quota lookup calls OpenRouter: cache it
        _llm_cache.update(at=time.monotonic(), value=agent("GET", "/llm/status"))
    return {"health": agent("GET", "/health"), "llm": _llm_cache["value"],
            "privacy": {"edge_redaction": True, "images_to_llm": False, "approval_required": True}}


# ---------- actions ----------
@app.post("/api/reports/{report_id}/approve")
def approve(report_id: int, body: dict):
    return agent("POST", f"/reports/{report_id}/approve", json={"payload_hash": body.get("payload_hash", "")},
                 timeout=300)


@app.post("/api/reports/{report_id}/reject")
def reject(report_id: int):
    return agent("POST", f"/reports/{report_id}/reject")


@app.post("/api/trips/{trip_id}/process")
def process(trip_id: str):
    """Re-run the agents on a trip whose events were uploaded but never processed (store-and-forward recovery)."""
    return agent("POST", f"/trips/{trip_id}/process", params={"wait": False})


@app.post("/api/follow-up")
def follow_up():
    return agent("POST", "/follow-up", timeout=300)


# ---------- media ----------
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
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=300"})


# ---------- trips: upload a dashcam video and run the edge device + agents ----------
def _simulated_gps(video: Path, out: Path) -> Path:
    cap = cv2.VideoCapture(str(video))
    seconds = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    cap.release()
    length = sum(haversine_m(*a, *b) for a, b in zip(HALIFAX_ROUTE, HALIFAX_ROUTE[1:]))
    write_gpx(simulate_route(HALIFAX_ROUTE, min(max(length / max(seconds, 1) * 3.6, 5), 80)), out)
    return out


def _run_trip(job: dict, video: Path, gps: Path | None):
    def step(name: str, progress: float, detail: str = ""):
        job.update(step=name, progress=round(progress, 3), detail=detail)

    try:
        with _gpu:
            step("edge", 0.0, "Loading the YOLOv8m edge detector")
            gps = gps or _simulated_gps(video, video.with_suffix(".gpx"))
            stats = process_video(video, gps, job["trip_id"], detector=edge_detector(),
                                  progress=lambda f, msg: step("edge", f, msg))
        job["edge"] = stats
        step("upload", 1.0, f"Uploading {stats['events']} privacy-blurred frames")
        job["upload"] = upload_outbox(Path(stats["outbox"]))
        step("agents", 0.0, "Agents are verifying, locating and triaging")
        run = agent("POST", f"/trips/{job['trip_id']}/process", params={"wait": False})
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
        job.update(status="failed", error=f"{type(e).__name__}: {e}")


@app.post("/api/trips")
async def create_trip(video: UploadFile = File(...), gps: UploadFile | None = File(None), simulate: bool = Form(True)):
    if not (video.filename or "").lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
        raise HTTPException(415, "video must be .mp4, .mov, .avi or .mkv")
    trip_id = time.strftime("trip%Y%m%d-%H%M%S")
    folder = settings.data_dir / "uploads" / trip_id
    folder.mkdir(parents=True, exist_ok=True)
    video_path = folder / f"video{Path(video.filename).suffix.lower()}"
    size = 0
    with open(video_path, "wb") as f:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                raise HTTPException(413, "video larger than 500 MB")
            f.write(chunk)
    gps_path = None
    if gps is not None and gps.filename and not simulate:
        if not gps.filename.lower().endswith((".gpx", ".csv")):
            raise HTTPException(415, "GPS track must be .gpx or .csv")
        gps_path = folder / f"track{Path(gps.filename).suffix.lower()}"
        gps_path.write_bytes(await gps.read(20 * 1024 * 1024))
    job = {"id": uuid.uuid4().hex[:10], "trip_id": trip_id, "status": "running", "step": "queued", "progress": 0,
           "detail": "Queued", "video": video.filename, "gps": gps.filename if gps_path else "simulated Halifax route"}
    jobs[job["id"]] = job
    threading.Thread(target=_run_trip, args=(job, video_path, gps_path), daemon=True).start()
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
    if path.startswith(("api/", "static/")):  # unknown API or asset paths are errors, not the app shell
        raise HTTPException(404, "not found")
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


def main():
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7860)
    args = p.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
