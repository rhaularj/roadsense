#!/usr/bin/env python
"""One command for the evidence judges look for: lint, tests, and a dependency audit.

    python scripts/check.py
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def step(name: str, cmd: list[str]) -> bool:
    print(f"\n== {name}: {' '.join(cmd)}", flush=True)
    ok = subprocess.run(cmd, cwd=ROOT).returncode == 0
    print(f"== {name}: {'PASS' if ok else 'FAIL'}", flush=True)
    return ok


def main():
    results = {}
    if importlib.util.find_spec("ruff"):
        results["lint"] = step("lint", [sys.executable, "-m", "ruff", "check", "roadsense", "scripts", "tests"])
    else:
        print("ruff not installed: pip install ruff (skipped)")
    results["tests"] = step("tests", [sys.executable, "-m", "pytest", "-q"])
    if importlib.util.find_spec("pip_audit"):
        results["audit"] = step("dependency audit", [sys.executable, "-m", "pip_audit", "-r", "requirements.txt"])
    else:
        print("pip-audit not installed: pip install pip-audit (skipped)")
    print("\nSummary:", ", ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in results.items()))
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
