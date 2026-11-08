"""Second-opinion verification, shared by the detector MCP server and the evaluation script so that what is measured
is exactly what runs."""
from __future__ import annotations

import cv2
import numpy as np

# Tuned on the RDD2022 validation split with scripts/eval_verifier.py --tune (largest false-alarm reduction that keeps
# >= 95% of true damage), then reported once on test: precision 0.714 -> 0.744, false alarms -21%, 92% of true damage
# kept (results/verifier_eval.json).
VERIFY_CONF = 0.50        # full-frame RT-DETR-L confidence that confirms a detection
RECHECK_EDGE_CONF = 0.40  # edge detections at least this confident get a close-up re-check when unconfirmed
RECHECK_CONF = 0.10       # close-up confidence that confirms
MIN_IOU = 0.2


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def verify(verifier, frame: np.ndarray, box: list[int]) -> tuple[dict, float] | None:
    """Best verifier detection overlapping the box on the full frame, as (detection, IoU), or None."""
    hits = [(d, iou(box, d["box"])) for d in verifier.detect(frame, conf=VERIFY_CONF)]
    hits = [(d, i) for d, i in hits if i >= MIN_IOU]
    return max(hits, key=lambda h: h[0]["confidence"] * (1 + h[1]), default=None)


def recheck(verifier, frame: np.ndarray, box: list[int]) -> dict | None:
    """Verifier on an enlarged crop around the box (helps small or distant damage); best overlapping detection."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    cx, cy, side = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1) * 2.5
    cx1, cy1 = int(max(cx - side / 2, 0)), int(max(cy - side / 2, 0))
    cx2, cy2 = int(min(cx + side / 2, w)), int(min(cy + side / 2, h))
    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None
    scale = 640 / max(crop.shape[:2])
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    local = [(x1 - cx1) * scale, (y1 - cy1) * scale, (x2 - cx1) * scale, (y2 - cy1) * scale]
    hits = [d for d in verifier.detect(crop, conf=RECHECK_CONF) if iou(local, d["box"]) >= 0.1]
    return max(hits, key=lambda d: d["confidence"], default=None)
