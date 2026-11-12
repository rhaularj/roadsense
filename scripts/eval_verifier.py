#!/usr/bin/env python
"""Measure what the Vision step adds: precision of edge detections before and after verification, on labelled
held-out images (RDD2022 splits from the training repo, location-blocked so no model saw these roads).

    # 1) tune the verification rule on the validation split
    python scripts/eval_verifier.py --split D:/py/road-pot-hole-detector/data/val --tune
    # 2) report it once on the test split with the tuned values (written to results/verifier_rule.json)
    python scripts/eval_verifier.py --split D:/py/road-pot-hole-detector/data/test

A detection is a true positive when it overlaps a labelled damage box (IoU >= 0.5). Verification runs on the
privacy-redacted frame, as in the app. For every edge detection we record the verifier's best overlapping confidence
on the full frame and on an enlarged close-up; the rule is: keep if full-frame confidence >= a, or if the edge
confidence >= b and the close-up confidence >= c.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roadsense.common.config import PROJECT_ROOT, settings  # noqa: E402
from roadsense.common.detectors import CLASSES, Detector  # noqa: E402
from roadsense.core import verify as checks  # noqa: E402
from roadsense.edge.redact import redact  # noqa: E402

CODES = [code for code, _, _ in CLASSES.values()]
RULE_FILE = PROJECT_ROOT / "results" / "verifier_rule.json"
FLOOR = 0.10  # collect verifier evidence down to this confidence; the rule thresholds are applied afterwards


def ground_truth(label: Path, w: int, h: int) -> list[tuple[str, list[float]]]:
    out = []
    if label.is_file():
        for line in label.read_text().split("\n"):
            parts = line.split()
            if len(parts) == 5 and int(parts[0]) < len(CODES):
                c, cx, cy, bw, bh = int(parts[0]), *map(float, parts[1:])
                out.append((CODES[c], [(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h]))
    return out


def sample(split: Path, per_country: int, seed: int) -> list[Path]:
    by_country = defaultdict(list)
    for p in sorted((split / "images").glob("*.jpg")):
        by_country[p.stem.rsplit("_", 1)[0]].append(p)
    rng = random.Random(seed)
    return [p for files in by_country.values() for p in rng.sample(files, min(per_country, len(files)))]


def collect(paths, split: Path, edge: Detector, ver: Detector) -> tuple[list[dict], int, dict]:
    rows, n_gt, t_edge, t_ver = [], 0, 0.0, 0.0
    old = checks.VERIFY_CONF, checks.RECHECK_CONF
    checks.VERIFY_CONF = checks.RECHECK_CONF = FLOOR
    try:
        for p in paths:
            frame = cv2.imread(str(p))
            h, w = frame.shape[:2]
            gt = ground_truth(split / "labels" / f"{p.stem}.txt", w, h)
            n_gt += len(gt)
            t0 = time.perf_counter()
            dets = edge.detect(frame)
            t_edge += time.perf_counter() - t0
            for d in dets:
                match = max(((c, checks.iou(d["box"], g)) for c, g in gt), key=lambda m: m[1], default=(None, 0.0))
                t0 = time.perf_counter()
                redacted = redact(frame, [d["box"]])
                full = checks.verify(ver, redacted, d["box"])
                close = checks.recheck(ver, redacted, d["box"])
                t_ver += time.perf_counter() - t0
                rows.append({"image": p.stem, "class": d["code"], "edge_conf": d["confidence"],
                             "full_conf": full[0]["confidence"] if full else 0.0,
                             "full_class": full[0]["code"] if full else None,
                             "close_conf": close["confidence"] if close else 0.0,
                             "tp": match[1] >= 0.5, "tp_class": match[1] >= 0.5 and match[0] == d["code"]})
    finally:
        checks.VERIFY_CONF, checks.RECHECK_CONF = old
    return rows, n_gt, {"edge_ms_per_image": round(1000 * t_edge / len(paths), 1),
                        "verify_ms_per_detection": round(1000 * t_ver / max(len(rows), 1), 1)}


def keep(r: dict, rule: dict) -> bool:
    return r["full_conf"] >= rule["a"] or (r["edge_conf"] >= rule["b"] and r["close_conf"] >= rule["c"])


def score(rows: list[dict], rule: dict, n_gt: int) -> dict:
    kept = [r for r in rows if keep(r, rule)]
    tp_all, tp_kept = sum(r["tp"] for r in rows), sum(r["tp"] for r in kept)
    fp_all = len(rows) - tp_all
    return {"detections_before": len(rows), "detections_after": len(kept),
            "precision_before": round(tp_all / len(rows), 3) if rows else None,
            "precision_after": round(tp_kept / len(kept), 3) if kept else None,
            "precision_class_aware_after": round(sum(r["tp_class"] for r in kept) / len(kept), 3) if kept else None,
            "false_alarms_removed": fp_all - (len(kept) - tp_kept), "false_alarms_total": fp_all,
            "false_alarm_reduction": round(1 - (len(kept) - tp_kept) / fp_all, 3) if fp_all else None,
            "true_damage_kept_share": round(tp_kept / tp_all, 3) if tp_all else None,
            "edge_recall_of_labels": round(tp_all / n_gt, 3) if n_gt else None,
            "disputed_share_of_kept": round(sum(1 for r in kept if r["full_class"] and r["full_class"] != r["class"])
                                            / max(len(kept), 1), 3)}


def tune(rows: list[dict], n_gt: int, min_keep: float) -> dict:
    """Largest false-alarm reduction that keeps at least `min_keep` of the true damage."""
    best = None
    for a, b, c in itertools.product([0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5],
                                     [0.3, 0.4, 0.5, 0.6, 0.7, 1.01], [0.1, 0.15, 0.2, 0.25, 0.3, 0.4]):
        rule = {"a": a, "b": b, "c": c}
        s = score(rows, rule, n_gt)
        if (s["true_damage_kept_share"] or 0) >= min_keep and (best is None or
                                                                s["false_alarm_reduction"] > best[1]["false_alarm_reduction"]):
            best = (rule, s)
    return {"rule": best[0], "val": best[1], "min_true_damage_kept": min_keep}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--split", required=True, help="split folder with images/ and labels/ (YOLO format)")
    p.add_argument("--per-country", type=int, default=50)
    p.add_argument("--tune", action="store_true", help="choose the rule on this split and save it")
    p.add_argument("--min-keep", type=float, default=0.95, help="share of true damage the filter must keep")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    split = Path(args.split)
    paths = sample(split, args.per_country, args.seed)
    edge = Detector(settings.weights_dir / settings.edge_weights, settings.device)
    ver = Detector(settings.weights_dir / settings.verify_weights, settings.device)
    rows, n_gt, timing = collect(paths, split, edge, ver)
    RULE_FILE.parent.mkdir(exist_ok=True)
    if args.tune:
        result = {**tune(rows, n_gt, args.min_keep), "split": split.name, "images": len(paths), **timing}
        RULE_FILE.write_text(json.dumps(result, indent=2))
    else:
        rule = json.loads(RULE_FILE.read_text())["rule"] if RULE_FILE.is_file() else \
            {"a": checks.VERIFY_CONF, "b": 0.6, "c": checks.RECHECK_CONF}
        result = {"split": split.name, "images": len(paths), "labelled_boxes": n_gt, "edge_model": edge.label,
                  "verifier": ver.label, "rule": rule, **score(rows, rule, n_gt), **timing}
        (PROJECT_ROOT / "results" / "verifier_eval.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
