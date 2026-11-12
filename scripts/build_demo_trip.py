#!/usr/bin/env python
"""Build the fixed demo trip in demo/trip/ from labelled RDD2022 test images (run once; the output is committed).

    python scripts/build_demo_trip.py --images D:/py/road-pot-hole-detector/data/test

Six events with fixed ids, chosen so every agent decision appears: two real defects on Halifax streets, one on
Highway 102 (provincial), one on Bedford Highway (numbered route, ambiguous), one detection that overlaps no
labelled damage (likely false alarm), and a second driver's sighting of a street defect a few metres away (merge).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_verifier import ground_truth  # noqa: E402

from roadsense.common.config import settings  # noqa: E402
from roadsense.common.detectors import Detector  # noqa: E402
from roadsense.core import geo  # noqa: E402
from roadsense.core.verify import iou  # noqa: E402
from roadsense.edge.gps import points_along  # noqa: E402
from roadsense.edge.redact import redact  # noqa: E402
from roadsense.edge.simulate_gps import HALIFAX_ROUTE  # noqa: E402

OUT = ROOT / "demo" / "trip"


def on(seg, t):
    (a_lat, a_lon), (b_lat, b_lon) = seg
    return a_lat + t * (b_lat - a_lat), a_lon + t * (b_lon - a_lon)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--images", required=True)
    p.add_argument("--seed", type=int, default=11)
    args = p.parse_args()
    split = Path(args.images)
    edge = Detector(settings.weights_dir / settings.edge_weights, settings.device)
    paths = sorted((split / "images").glob("*.jpg"))
    random.Random(args.seed).shuffle(paths)
    real, false = [], []
    for path in paths:
        if len(real) >= 4 and false:
            break
        frame = cv2.imread(str(path))
        h, w = frame.shape[:2]
        gt = ground_truth(split / "labels" / f"{path.stem}.txt", w, h)
        for d in edge.detect(frame)[:1]:
            best = max((iou(d["box"], g) for _, g in gt), default=0.0)
            if best >= 0.5 and len(real) < 4 and d["confidence"] >= 0.5:
                real.append((path, frame, d))
            elif best == 0.0 and not false:
                false.append((path, frame, d))
    street = points_along(HALIFAX_ROUTE, 120.0)
    hwy = geo.OFFLINE_ROADS[0][3], geo.OFFLINE_ROADS[0][4]
    bed = geo.OFFLINE_ROADS[1][3], geo.OFFLINE_ROADS[1][4]
    plan = [("demo-01", "demo-halifax", real[0], street[2], "Halifax street"),
            ("demo-02", "demo-halifax", real[1], street[6], "Halifax street"),
            ("demo-03", "demo-halifax", real[2], on(hwy, 0.5), "Highway 102 (provincial)"),
            ("demo-04", "demo-halifax", real[3], on(bed, 0.5), "Bedford Highway (numbered route)"),
            ("demo-05", "demo-halifax", false[0], street[9], "detection overlapping no labelled damage"),
            ("demo-06", "demo-halifax-2", real[0], (street[2][0] + 0.00003, street[2][1] + 0.00002),
             "second driver, same defect as demo-01")]
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for eid, trip, (path, frame, d), (lat, lon), why in plan:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = d["box"]
        cv2.imwrite(str(OUT / f"{eid}.jpg"), redact(frame, [d["box"]]), [cv2.IMWRITE_JPEG_QUALITY, 80])
        event = {"id": eid, "trip_id": trip, "track_id": int(eid[-2:]), "class_code": d["code"],
                 "class_name": d["name"], "confidence": d["confidence"], "frames_seen": 4, "box": d["box"],
                 "box_area_ratio": round((x2 - x1) * (y2 - y1) / (w * h), 5), "lat": round(lat, 6),
                 "lon": round(lon, 6), "heading": 90.0, "captured_at": "2026-11-03T14:00:00Z"}
        (OUT / f"{eid}.json").write_text(json.dumps(event, indent=2), encoding="utf-8")
        manifest.append({"id": eid, "scenario": why, "source_image": path.name})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
