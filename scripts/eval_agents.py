#!/usr/bin/env python
"""Scenario evaluation of the agent layer: does it make the right decisions, end to end, through the real MCP servers?

    python scripts/eval_agents.py                       # deterministic pipeline (no LLM)
    python scripts/eval_agents.py --llm                 # the LLM agents (needs OPENROUTER_API_KEY, or replay mode)

Scenarios are built from labelled RDD2022 test images (held-out roads), so the right answer is known:
- real damage vs false alarm: an edge detection overlapping a labelled box (IoU >= 0.5) should become a report,
  one that overlaps nothing should be rejected;
- jurisdiction: defects placed on Highway 102 belong to Nova Scotia Public Works, on local streets to HRM; defects on
  a numbered route through the city (Bedford Highway) are ambiguous and the choice is only recorded;
- duplicates: the same defect reported again by a second driver within a few metres must merge, not file twice.
Trajectory rules are checked from the audit log: nothing is sent to an authority during trip processing, no agent
uses a tool outside its allow-list, and every report comes from an event with a verdict.
Writes results/agent_eval.json. Uses an isolated data folder (data/eval) and offline geocoding.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import shutil
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "data" / "eval"
os.environ.update(ROADSENSE_DATA_DIR=str(EVAL_DIR), ROADSENSE_OFFLINE_GEO="1")
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from roadsense.agents import orchestrator  # noqa: E402
from roadsense.agents.mcp_client import Toolbox  # noqa: E402
from roadsense.common.config import settings  # noqa: E402
from roadsense.common.db import now, session  # noqa: E402
from roadsense.common.detectors import Detector  # noqa: E402
from roadsense.core import geo  # noqa: E402
from roadsense.core.verify import iou  # noqa: E402
from roadsense.edge.gps import points_along  # noqa: E402
from roadsense.edge.redact import redact  # noqa: E402
from roadsense.edge.simulate_gps import HALIFAX_ROUTE  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from eval_verifier import ground_truth  # noqa: E402


def on_segment(seg, lat):
    (a_lat, a_lon), (b_lat, b_lon) = seg
    t = (lat - a_lat) / (b_lat - a_lat)
    return lat, a_lon + t * (b_lon - a_lon)


def street_points(n: int) -> list[tuple[float, float]]:
    """Points 45 m apart along the Halifax route (which follows real streets), so they never dedupe by accident."""
    pts = points_along(HALIFAX_ROUTE, 45.0)
    if len(pts) < n:
        raise SystemExit(f"route too short for {n} street scenarios")
    return pts[:n]


def build(images: Path, n_single: int, seed: int) -> list[dict]:
    """Pick edge detections on held-out images with a known answer, and give each scenario a place on the map."""
    edge = Detector(settings.weights_dir / settings.edge_weights, settings.device)
    rng = random.Random(seed)
    paths = sorted((images / "images").glob("*.jpg"))
    rng.shuffle(paths)
    real, false = [], []
    for p in paths:
        if len(real) >= n_single and len(false) >= n_single // 2:
            break
        frame = cv2.imread(str(p))
        h, w = frame.shape[:2]
        gt = ground_truth(images / "labels" / f"{p.stem}.txt", w, h)
        for d in edge.detect(frame)[:1]:
            best = max((iou(d["box"], g) for _, g in gt), default=0.0)
            item = {"image": p, "det": d, "frame_shape": (h, w)}
            if best >= 0.5 and len(real) < n_single:
                real.append({**item, "real": True})
            elif best == 0.0 and len(false) < n_single // 2:  # overlaps no labelled damage
                false.append({**item, "real": False})
    items = real + false
    rng.shuffle(items)  # spread false alarms over every kind of road
    n_hwy, n_bed = max(len(items) // 6, 2), max(len(items) // 9, 1)
    hwy_lats = [44.6700 + i * 0.020 / n_hwy for i in range(n_hwy)]
    bed_lats = [44.6700 + i * 0.015 / n_bed for i in range(n_bed)]
    hwy = [on_segment((geo.OFFLINE_ROADS[0][3], geo.OFFLINE_ROADS[0][4]), lat) for lat in hwy_lats]
    bed = [on_segment((geo.OFFLINE_ROADS[1][3], geo.OFFLINE_ROADS[1][4]), lat) for lat in bed_lats]
    streets = street_points(len(items) - n_hwy - n_bed)
    del edge  # free the GPU for the verifier in the detector MCP server
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    scenarios = []
    for i, item in enumerate(items):
        kind = "highway" if i < n_hwy else ("numbered_route" if i < n_hwy + n_bed else "street")
        place = hwy[i] if kind == "highway" else (bed[i - n_hwy] if kind == "numbered_route" else streets[i - n_hwy - n_bed])
        scenarios.append({**item, "id": f"s{i:02d}", "trip": "evalA", "kind": kind, "lat": place[0], "lon": place[1],
                          "expect_jurisdiction": {"highway": geo.PROVINCIAL, "street": "Halifax Regional Municipality",
                                                  "numbered_route": None}[kind]})
    for j, item in enumerate([s for s in scenarios if s["real"] and s["kind"] == "street"][:max(len(items) // 6, 2)]):
        scenarios.append({**item, "id": f"d{j:02d}", "trip": "evalB", "kind": "duplicate", "of": item["id"],
                          "lat": item["lat"] + 0.00003, "lon": item["lon"] + 0.00002})  # ~4 m away, second driver
    return scenarios


def load(scenarios: list[dict]) -> None:
    media = settings.media_dir
    media.mkdir(parents=True, exist_ok=True)
    with session() as conn:
        for s in scenarios:
            frame = cv2.imread(str(s["image"]))
            d, (h, w) = s["det"], s["frame_shape"]
            path = media / f"{s['id']}.jpg"
            cv2.imwrite(str(path), redact(frame, [d["box"]]))
            x1, y1, x2, y2 = d["box"]
            conn.execute(
                "INSERT INTO events (id, trip_id, track_id, class_code, class_name, confidence, frames_seen,"
                " box_area_ratio, box, lat, lon, heading, captured_at, image_path, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (s["id"], s["trip"], 1, d["code"], d["name"], d["confidence"], 4, (x2 - x1) * (y2 - y1) / (w * h),
                 json.dumps(d["box"]), s["lat"], s["lon"], 90.0, now(), str(path), now()))


def score(scenarios: list[dict], runs: list[dict]) -> dict:
    with session() as conn:
        events = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM events")}
        reports = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM reports")}
        audit = [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id")]
    singles = [s for s in scenarios if s["kind"] != "duplicate"]
    reported = [s for s in singles if events[s["id"]]["status"] == "processed"]
    tp = sum(s["real"] for s in reported)
    juris = [s for s in reported if s["expect_jurisdiction"]]
    juris_ok = sum(reports[events[s["id"]]["report_id"]]["jurisdiction"] == s["expect_jurisdiction"] for s in juris)
    dups = [s for s in scenarios if s["kind"] == "duplicate"]
    dup_ok = sum(1 for s in dups if events[s["id"]]["report_id"] and
                 events[s["id"]]["report_id"] == events[s["of"]]["report_id"])
    dup_applicable = sum(1 for s in dups if events[s["of"]]["status"] == "processed")
    ambiguous = [reports[events[s["id"]]["report_id"]]["jurisdiction"] for s in reported
                 if s["kind"] == "numbered_route"]
    sent_during_trip = [a for a in audit if a["action"] in ("tool:city_submit_request", "status_submitted")]
    off_list = [a for a in audit if "is not available to" in (a["detail"] or "")]
    return {
        "scenarios": len(scenarios), "real_damage": sum(s["real"] for s in singles),
        "false_alarms": sum(not s["real"] for s in singles),
        "report_precision": round(tp / len(reported), 3) if reported else None,
        "real_damage_reported": round(tp / max(sum(s["real"] for s in singles), 1), 3),
        "false_alarms_rejected": round(sum(1 for s in singles if not s["real"] and events[s["id"]]["status"] ==
                                           "rejected") / max(sum(not s["real"] for s in singles), 1), 3),
        "jurisdiction_accuracy": round(juris_ok / len(juris), 3) if juris else None,
        "numbered_route_choices": ambiguous,
        "duplicate_merge_accuracy": round(dup_ok / dup_applicable, 3) if dup_applicable else None,
        "disputed_events": sum(e["class_disputed"] for e in events.values()),
        "trajectory_violations": {"sent_without_approval": len(sent_during_trip),
                                  "tool_outside_allow_list": len(off_list)},
        "fallback_rate": round(sum(r.get("fallback_events", 0) for r in runs) / len(scenarios), 3),
        "seconds_per_trip": [r.get("seconds") for r in runs],
        "llm": [r.get("llm") for r in runs], "mode": [r.get("mode") for r in runs],
    }


async def run(scenarios: list[dict], use_llm: bool) -> list[dict]:
    async with Toolbox() as tb:
        out = []
        for trip in ("evalA", "evalB"):
            out.append(await orchestrator.process_trip(tb, trip, use_llm))
        return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--images", default="D:/py/road-pot-hole-detector/data/test")
    p.add_argument("--singles", type=int, default=24, help="real-damage scenarios (half as many false alarms)")
    p.add_argument("--llm", action="store_true")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    if EVAL_DIR.exists():
        shutil.rmtree(EVAL_DIR)
    scenarios = build(Path(args.images), args.singles, args.seed)
    load(scenarios)
    t0 = time.perf_counter()
    runs = asyncio.run(run(scenarios, args.llm))
    result = {"agents": args.llm, **score(scenarios, runs), "total_seconds": round(time.perf_counter() - t0, 1)}
    secs = [s for s in result["seconds_per_trip"] if s]
    result["median_trip_seconds"] = statistics.median(secs) if secs else None
    out = ROOT / "results" / ("agent_eval_llm.json" if args.llm else "agent_eval.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
