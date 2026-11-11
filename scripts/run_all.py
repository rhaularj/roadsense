#!/usr/bin/env python
"""Start the whole RoadSense stack on this laptop: mock 311 (8311), agent API (8000) and dashboard (7860).

    python scripts/run_all.py                    # Ctrl+C stops everything
    python scripts/run_all.py --host 0.0.0.0     # inside Docker
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SERVICES = [
    ("mock 311", "roadsense.services.mock_open311", 8311, "/services.json"),
    ("agent API", "roadsense.services.agent_api", 8000, "/health"),
    ("web app", "roadsense.web.app", 7860, "/api/system"),
]


def wait(url: str, seconds: int = 180) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            r = httpx.get(url, timeout=2)
            if r.status_code < 500 and ("tools_ready" not in r.text or '"tools_ready":true' in r.text):
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()
    procs = []
    try:
        for name, module, port, path in SERVICES:
            procs.append(subprocess.Popen([sys.executable, "-m", module, "--host", args.host, "--port", str(port)],
                                          cwd=ROOT))
            url = f"http://127.0.0.1:{port}"
            print(f"{name}: {'ready' if wait(url + path) else 'NOT READY'} at {url}", flush=True)
        print("\nOpen http://127.0.0.1:7860  (Ctrl+C to stop)", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in procs:
            proc.terminate()


if __name__ == "__main__":
    main()
