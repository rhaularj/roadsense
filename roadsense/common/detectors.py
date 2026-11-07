"""Road damage detectors trained on RDD2022 (4 classes), shared by the edge pipeline and the verifier.

The class table and val-tuned thresholds come from the training repo (road-pot-hole-detector, README results):
each model's confidence threshold was tuned on the validation split and frozen before the test split.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

# class id -> (code, readable name, BGR box colour); ids follow configs/rdd2022.yaml of the training repo
CLASSES = {
    0: ("D00", "Longitudinal crack", (0, 179, 255)),
    1: ("D10", "Transverse crack", (255, 176, 0)),
    2: ("D20", "Alligator crack", (255, 0, 170)),
    3: ("D40", "Pothole", (68, 23, 255)),
}
POTHOLE = 3

# test-split results; conf is the threshold tuned on val
MODELS = {
    "rtdetr_l_rdd2022.pt": {"name": "RT-DETR-L", "conf": 0.50, "f1": 0.614, "map50": 0.613},
    "yolov8m_rdd2022.pt": {"name": "YOLOv8m", "conf": 0.25, "f1": 0.590, "map50": 0.599},
    "yolov8s_rdd2022.pt": {"name": "YOLOv8s", "conf": 0.20, "f1": 0.568, "map50": 0.566},
}


def resolve_device(device: str | None) -> str:
    """Device string in Ultralytics form: 'cpu' or a GPU index such as '0'."""
    if device is None:
        return "0" if torch.cuda.is_available() else "cpu"
    return device


def default_conf(weights: Path) -> float:
    return MODELS.get(weights.name, {}).get("conf", 0.25)


def make_detection(class_id: int, confidence: float, box, track_id: int | None = None) -> dict:
    code, name, _ = CLASSES[class_id]
    return {"class_id": class_id, "code": code, "name": name, "confidence": round(confidence, 4),
            "box": [round(float(v)) for v in box], "track_id": track_id}


class Detector:
    """RT-DETR or YOLO checkpoint fine-tuned on the 4 RDD2022 classes."""

    def __init__(self, weights: Path, device: str | None = None, imgsz: int = 640, conf: float | None = None):
        from ultralytics import RTDETR, YOLO

        if not weights.is_file():
            raise FileNotFoundError(f"Weights not found: {weights}. Set ROADSENSE_WEIGHTS_DIR or copy the fine-tuned "
                                    "best.pt files from the training repo into weights/.")
        self.weights = weights
        self.model = RTDETR(str(weights)) if "rtdetr" in weights.name.lower() else YOLO(str(weights))
        names = self.model.names
        if [names[i] for i in sorted(names)] != [code for code, _, _ in CLASSES.values()]:
            raise ValueError(f"{weights} was not trained on the 4 RDD2022 classes (its classes: {names}).")
        self.device, self.imgsz = resolve_device(device), imgsz
        self.conf = default_conf(weights) if conf is None else conf
        self.label = MODELS.get(weights.name, {}).get("name", weights.stem)

    def detect(self, bgr: np.ndarray, conf: float | None = None) -> list[dict]:
        r = self.model.predict(bgr, conf=self.conf if conf is None else conf, imgsz=self.imgsz,
                               device=self.device, verbose=False)[0]
        return self._parse(r)

    def track(self, bgr: np.ndarray, conf: float | None = None, tracker: str = "bytetrack.yaml") -> list[dict]:
        """Detect and keep tracker ids across consecutive calls (one video at a time)."""
        r = self.model.track(bgr, conf=self.conf if conf is None else conf, imgsz=self.imgsz, device=self.device,
                             persist=True, tracker=tracker, verbose=False)[0]
        return self._parse(r)

    def reset_tracker(self) -> None:
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", None) or []:
            tracker.reset()

    @staticmethod
    def _parse(r) -> list[dict]:
        b = r.boxes
        ids = b.id.int().cpu().tolist() if b.id is not None else [None] * len(b)
        return [make_detection(int(c), float(s), xyxy, tid)
                for xyxy, s, c, tid in zip(b.xyxy.cpu().numpy(), b.conf.cpu().numpy(), b.cls.cpu().numpy(), ids)]
