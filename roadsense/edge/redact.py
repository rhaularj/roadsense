"""Privacy redaction on the device: blur everything except the damage itself.

Blurring the whole scene outside the damage boxes removes faces, licence plates and house numbers without needing a
face or plate detector, and nothing unblurred but the road surface ever leaves the vehicle.
"""
from __future__ import annotations

import cv2
import numpy as np


def redact(frame: np.ndarray, boxes: list[list[int]], margin: float = 0.15, strength: int = 41) -> np.ndarray:
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (max(w // 8, 1), max(h // 8, 1)), interpolation=cv2.INTER_AREA)
    out = cv2.GaussianBlur(cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR), (strength, strength), 0)
    for x1, y1, x2, y2 in boxes:
        mx, my = int((x2 - x1) * margin), int((y2 - y1) * margin)
        x1, y1, x2, y2 = max(x1 - mx, 0), max(y1 - my, 0), min(x2 + mx, w), min(y2 + my, h)
        out[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
    return out


def annotate(frame: np.ndarray, box: list[int], label: str, color=(68, 23, 255)) -> np.ndarray:
    out = frame.copy()
    x1, y1, x2, y2 = box
    thickness = max(2, frame.shape[1] // 400)
    cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(out, (x1, max(y1 - th - 8, 0)), (x1 + tw + 6, max(y1, th + 8)), color, -1)
    cv2.putText(out, label, (x1 + 3, max(y1 - 5, th + 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return out
