"""Turn per-frame tracked detections into damage events: one event per physical defect, best frame kept."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


def sharpness(frame: np.ndarray, box: list[int]) -> float:
    """Variance of the Laplacian inside the box: low for motion-blurred frames."""
    x1, y1, x2, y2 = box
    patch = frame[max(y1, 0):max(y2, y1 + 1), max(x1, 0):max(x2, x1 + 1)]
    if patch.size == 0:
        return 0.0
    return float(cv2.Laplacian(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def frame_score(confidence: float, sharp: float) -> float:
    """Best frame = confident and sharp. Sharpness saturates at a Laplacian variance of 300."""
    return confidence * (0.5 + 0.5 * min(sharp / 300.0, 1.0))


@dataclass
class TrackState:
    track_id: int
    class_votes: dict[str, int] = field(default_factory=dict)
    frames_seen: int = 0
    max_conf: float = 0.0
    first_t: float = 0.0
    last_t: float = 0.0
    best: dict | None = None          # detection in the best frame (confidence x sharpness)
    best_frame: np.ndarray | None = None
    best_t: float = 0.0
    best_score: float = -1.0
    frame_area: int = 1

    @property
    def class_code(self) -> str:
        return max(self.class_votes, key=self.class_votes.get)


class TrackAggregator:
    """Collects detections per tracker id. A track is emitted once it has been gone for `max_gap_s` (the car drove
    past) and is accepted if seen in at least `min_frames` frames, or in 2+ frames with one strong detection, which
    filters one-frame false alarms while keeping small defects that are only briefly visible."""

    def __init__(self, min_frames: int = 3, max_gap_s: float = 1.5, strong_conf: float = 0.5):
        self.min_frames, self.max_gap_s, self.strong_conf = min_frames, max_gap_s, strong_conf
        self.active: dict[int, TrackState] = {}

    def update(self, t: float, frame: np.ndarray, detections: list[dict]) -> list[TrackState]:
        h, w = frame.shape[:2]
        for d in detections:
            tid = d.get("track_id")
            if tid is None:
                continue  # not yet confirmed by the tracker
            s = self.active.get(tid)
            if s is None:
                s = self.active[tid] = TrackState(tid, first_t=t, frame_area=h * w)
            s.frames_seen += 1
            s.last_t = t
            s.max_conf = max(s.max_conf, d["confidence"])
            s.class_votes[d["code"]] = s.class_votes.get(d["code"], 0) + 1
            score = frame_score(d["confidence"], sharpness(frame, d["box"]))
            if score > s.best_score:
                s.best, s.best_frame, s.best_t, s.best_score = d, frame.copy(), t, score
        return self._pop(lambda s: t - s.last_t > self.max_gap_s)

    def flush(self) -> list[TrackState]:
        return self._pop(lambda s: True)

    def accepted(self, s: TrackState) -> bool:
        return s.frames_seen >= self.min_frames or (s.frames_seen >= 2 and s.max_conf >= self.strong_conf)

    def _pop(self, done) -> list[TrackState]:
        finished = [s for s in self.active.values() if done(s)]
        for s in finished:
            del self.active[s.track_id]
        return [s for s in finished if self.accepted(s)]
