#!/usr/bin/env python
"""Keyless demo: replay a real, recorded run of the RoadSense agents on a fixed demo trip.

    python scripts/demo.py               # replay demo/llm_cache.json: no API key, no network calls to an LLM
    python scripts/demo.py --record      # live run with OPENROUTER_API_KEY (~17 requests), saves demo/llm_cache.json
    python scripts/demo.py --no-llm      # rule engine only (plumbing check)

The demo trip (demo/trip/, built by scripts/build_demo_trip.py) has six events with fixed ids covering every agent
decision: real damage on Halifax streets, Highway 102 (provincial), Bedford Highway (ambiguous numbered route), a
likely false alarm, and a second driver's sighting that must merge. Each run starts from a fresh data/demo folder
with offline geocoding, so the agents see exactly the same tool results as when the run was recorded, and the
replayed answers match. To browse the result afterwards:

    ROADSENSE_DATA_DIR=data/demo ROADSENSE_OFFLINE_GEO=1 python scripts/run_all.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
DATA = ROOT / "data" / "demo"
CACHE = DEMO / "llm_cache.json"
TRIPS = ("demo-halifax", "demo-halifax-2")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--record", action="store_true", help="live LLM run; saves the responses for replay")
    p.add_argument("--no-llm", action="store_true", help="rule engine only")
    args = p.parse_args()
    if DATA.exists():
        shutil.rmtree(DATA)
    os.environ.update(ROADSENSE_DATA_DIR=str(DATA), ROADSENSE_OFFLINE_GEO="1",
                      ROADSENSE_LLM_MODE="cache" if args.record else "replay",
                      ROADSENSE_USE_LLM="0" if args.no_llm else "1")
    sys.path.insert(0, str(ROOT))
    from roadsense.agents import orchestrator
    from roadsense.agents.llm import CACHE_SCHEMA
    from roadsense.agents.mcp_client import Toolbox
    from roadsense.common.config import settings
    from roadsense.common.db import now, session

    if not args.record and not args.no_llm and not CACHE.is_file():
        raise SystemExit("demo/llm_cache.json not found: record it first with --record (needs an OpenRouter key)")
    with session() as conn:
        conn.execute(CACHE_SCHEMA)
        if not args.record and CACHE.is_file():
            rows = json.loads(CACHE.read_text(encoding="utf-8"))
            conn.executemany("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?, ?)",
                             [(r["key"], r["model"], r["message"], r["usage"]) for r in rows])
        settings.media_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted((DEMO / "trip").glob("demo-*.json")):
            e = json.loads(f.read_text(encoding="utf-8"))
            image = settings.media_dir / f"{e['id']}.jpg"
            shutil.copy(f.with_suffix(".jpg"), image)
            conn.execute(
                "INSERT INTO events (id, trip_id, track_id, class_code, class_name, confidence, frames_seen,"
                " box_area_ratio, box, lat, lon, heading, captured_at, image_path, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (e["id"], e["trip_id"], e["track_id"], e["class_code"], e["class_name"], e["confidence"],
                 e["frames_seen"], e["box_area_ratio"], json.dumps(e["box"]), e["lat"], e["lon"], e["heading"],
                 e["captured_at"], str(image), now()))

    async def run():
        async with Toolbox() as tb:
            return [await orchestrator.process_trip(tb, t, settings.llm_enabled) for t in TRIPS]

    results = asyncio.run(run())
    for r in results:
        print(f"\n=== {r['trip_id']}: mode {r['mode']}, fallback rate {r.get('fallback_rate')}, "
              f"{r.get('seconds')} s, llm {r.get('llm')}")
        print(r["summary"])
    if args.record:
        with session() as conn:
            rows = [dict(x) for x in conn.execute("SELECT key, model, message, usage FROM llm_cache")]
        CACHE.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"\nsaved {len(rows)} recorded responses to {CACHE.relative_to(ROOT)}")
    replay_ok = all(r["mode"] == "agents" and r.get("fallback_rate") == 0 for r in results)
    if not args.record and not args.no_llm:
        print("\nreplay:", "complete (every agent step served from the recording)" if replay_ok else
              "INCOMPLETE: some steps were not in the recording and fell back to the rule engine")
        sys.exit(0 if replay_ok else 1)


if __name__ == "__main__":
    main()
