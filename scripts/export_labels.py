#!/usr/bin/env python
"""Export reviewer decisions as a labelled dataset for fine-tuning and for the Halifax ground-truth program.

    python scripts/export_labels.py                       # → data/labels_export/ (YOLO format + labels.csv)
    python scripts/export_labels.py --out exports/2026-11

Every approve, reject and class correction in the review inbox labels the report's events (table `labels`):
    approved      the detection was real damage of the stored class
    reclassified  real damage, of the class the reviewer chose
    rejected      not damage worth reporting (a hard negative: written with an empty label file)

The images are the privacy-redacted frames the server stored, so the dataset carries no faces or plates beyond
what redaction left. Split by trip (not by image) so the same pothole never lands in both train and validation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CLASS_IDS = {"D00": 0, "D10": 1, "D20": 2, "D40": 3}  # RDD2022 order used by the training repo


def main():
    from roadsense.common.config import settings
    from roadsense.common.db import session

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=settings.data_dir / "labels_export")
    p.add_argument("--val-share", type=float, default=0.2)
    args = p.parse_args()

    with session() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT l.event_id, l.label, l.class_code AS label_class, l.actor, l.ts, e.trip_id, e.class_code, e.box, "
            "e.image_path FROM labels l JOIN events e ON e.id = l.event_id ORDER BY l.id")]
    latest = {}
    for r in rows:  # the last decision on an event wins (e.g. reclassified, then approved)
        latest[r["event_id"]] = r
    if not latest:
        raise SystemExit("no reviewer decisions recorded yet")
    if args.out.exists():
        shutil.rmtree(args.out)
    counts = {"train": 0, "val": 0, "skipped": 0}
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "trip_id", "split", "label", "class_code", "decided_by", "decided_at"])
        for r in latest.values():
            img_path = Path(r["image_path"])
            img = cv2.imread(str(img_path)) if img_path.is_file() else None
            if img is None:
                counts["skipped"] += 1
                continue
            split = "val" if int(hashlib.sha1(r["trip_id"].encode()).hexdigest(), 16) % 100 < args.val_share * 100 \
                else "train"
            h, wd = img.shape[:2]
            (args.out / "images" / split).mkdir(parents=True, exist_ok=True)
            (args.out / "labels" / split).mkdir(parents=True, exist_ok=True)
            shutil.copy(img_path, args.out / "images" / split / f"{r['event_id']}.jpg")
            lines = []
            code = r["label_class"] or r["class_code"]
            if r["label"] in ("approved", "reclassified") and code in CLASS_IDS:
                x1, y1, x2, y2 = json.loads(r["box"])
                lines.append(f"{CLASS_IDS[code]} {(x1 + x2) / 2 / wd:.6f} {(y1 + y2) / 2 / h:.6f} "
                             f"{(x2 - x1) / wd:.6f} {(y2 - y1) / h:.6f}")
            (args.out / "labels" / split / f"{r['event_id']}.txt").write_text("\n".join(lines), encoding="utf-8")
            counts[split] += 1
            w.writerow([r["event_id"], r["trip_id"], split, r["label"], code, r["actor"], r["ts"]])
    (args.out / "data.yaml").write_text(
        f"path: {args.out.resolve()}\ntrain: images/train\nval: images/val\n"
        "names: {0: D00, 1: D10, 2: D20, 3: D40}\n", encoding="utf-8")
    print(f"exported {counts['train']} train / {counts['val']} val images to {args.out} "
          f"({counts['skipped']} skipped: photo purged or missing); decisions in {args.out.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
