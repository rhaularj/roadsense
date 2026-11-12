"""Server-side privacy: check every stored frame was redacted, and enforce retention.

The edge device blurs everything outside the damage box (core of the privacy model). The server does not trust
that: each uploaded frame is checked for sharp detail outside the damage area and re-redacted when it has any. An
optional face and licence-plate model (EgoBlur, Apache-2.0, exported to TorchScript) can then blur faces or plates
that fall inside the unblurred damage area itself.

Retention: raw dashcam video and GPS tracks are deleted as soon as the edge pipeline has processed them (unless
ROADSENSE_KEEP_RAW_VIDEO=1), photos of rejected detections after ROADSENSE_REJECTED_MEDIA_DAYS, and the car's own
position after ROADSENSE_CAR_POSITION_DAYS (the defect's position is kept: it is the report).
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from ..common.config import settings
from ..common.db import audit
from ..edge.redact import redact

log = logging.getLogger("roadsense.privacy")
SHARPNESS_LIMIT = 60.0  # Laplacian variance; the edge blur leaves ~1-10, a raw street scene is in the hundreds


def _outside_mask(shape, box, margin: float = 0.2) -> np.ndarray:
    h, w = shape[:2]
    x1, y1, x2, y2 = box
    mx, my = int((x2 - x1) * margin), int((y2 - y1) * margin)
    mask = np.ones((h, w), dtype=bool)
    mask[max(y1 - my, 0):min(y2 + my, h), max(x1 - mx, 0):min(x2 + mx, w)] = False
    return mask


def outside_sharpness(frame: np.ndarray, box: list[int]) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    mask = _outside_mask(frame.shape, box)
    return float(lap[mask].var()) if mask.any() else 0.0


@lru_cache(maxsize=1)
def _egoblur():
    if not settings.egoblur_weights:
        return None
    try:
        import torch

        return torch.jit.load(settings.egoblur_weights, map_location="cpu").eval()
    except Exception as e:  # optional component: a missing or incompatible model must not stop uploads
        log.warning("EgoBlur model not loaded: %s", e)
        return None


def _egoblur_boxes(crop: np.ndarray, threshold: float = 0.5) -> list[list[int]]:
    model = _egoblur()
    if model is None or crop.size == 0:
        return []
    import torch

    tensor = torch.from_numpy(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float()
    with torch.no_grad():
        out = model(tensor)
    boxes, scores = out[0], out[2] if len(out) > 2 else torch.ones(len(out[0]))
    return [[int(v) for v in b.tolist()] for b, s in zip(boxes, scores) if float(s) >= threshold]


def server_redact(path: Path, box: list[int]) -> dict:
    """Check and, if needed, redo the redaction of one stored frame in place. Returns what was done."""
    frame = cv2.imread(str(path))
    if frame is None:
        return {"checked": False, "reason": "unreadable image"}
    sharp = outside_sharpness(frame, box)
    reapplied = sharp > SHARPNESS_LIMIT
    if reapplied:
        frame = redact(frame, [box])
    hits = 0
    x1, y1, x2, y2 = box
    for bx1, by1, bx2, by2 in _egoblur_boxes(frame[y1:y2, x1:x2]):
        region = frame[y1 + by1:y1 + by2, x1 + bx1:x1 + bx2]
        if region.size:
            frame[y1 + by1:y1 + by2, x1 + bx1:x1 + bx2] = cv2.GaussianBlur(region, (51, 51), 0)
            hits += 1
    if reapplied or hits:
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return {"checked": True, "outside_sharpness": round(sharp, 1), "reapplied": reapplied, "faces_or_plates": hits,
            "egoblur": _egoblur() is not None}


def delete_trip_raw(folder: Path) -> list[str]:
    """Delete the raw video and GPS track of a processed trip (the privacy-blurred frames are already uploaded)."""
    if settings.keep_raw_video or not folder.is_dir():
        return []
    removed = []
    for f in folder.iterdir():
        if f.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv", ".gpx", ".csv"):
            f.unlink(missing_ok=True)
            removed.append(f.name)
    return removed


def purge(conn: sqlite3.Connection, now_ts: float | None = None) -> dict:
    """Apply the retention policy. Idempotent; the scheduler runs it every hour."""
    now_ts = now_ts or time.time()
    out = {"raw_folders": 0, "rejected_media": 0, "car_positions": 0}
    uploads = settings.data_dir / "uploads"
    if uploads.is_dir() and not settings.keep_raw_video:
        limit = settings.raw_retention_hours * 3600
        for folder in uploads.iterdir():
            if folder.is_dir() and now_ts - folder.stat().st_mtime > max(limit, 3600 * 24):
                shutil.rmtree(folder, ignore_errors=True)  # anything a failed job left behind
                out["raw_folders"] += 1
    cutoff = lambda days: (datetime.fromtimestamp(now_ts, timezone.utc) - timedelta(days=days)).isoformat(  # noqa: E731
        timespec="seconds")
    for (event_id,) in conn.execute("SELECT id FROM events WHERE status = 'rejected' AND created_at < ?",
                                    (cutoff(settings.rejected_media_days),)).fetchall():
        p = settings.media_dir / f"{event_id}.jpg"
        if p.exists():
            p.unlink()
            out["rejected_media"] += 1
    cur = conn.execute("UPDATE events SET car_lat = NULL, car_lon = NULL WHERE car_lat IS NOT NULL AND created_at < ?",
                       (cutoff(settings.car_position_days),))
    out["car_positions"] = cur.rowcount
    if any(out.values()):
        audit(conn, "retention", "purge", None, json.dumps(out))
    return out
