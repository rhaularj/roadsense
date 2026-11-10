#!/usr/bin/env python
"""Check that each configured OpenRouter model really does tool calling, before trusting it with the agents.

    python scripts/smoke_llm.py                       # models from ROADSENSE_LLM_MODELS
    python scripts/smoke_llm.py google/gemma-4-31b-it:free

Put the models that pass first in ROADSENSE_LLM_MODELS. Uses 1-2 requests per model.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roadsense.agents.llm import LLM, LLMUnavailable  # noqa: E402
from roadsense.common.config import settings  # noqa: E402

TOOL = [{"type": "function", "function": {
    "name": "find_municipality", "description": "Municipality responsible for the road at a GPS position.",
    "parameters": {"type": "object", "required": ["lat", "lon"],
                   "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}}}}}]
PROMPT = [{"role": "system", "content": "You are a road-damage agent. Use your tools."},
          {"role": "user", "content": "Which municipality is responsible for a pothole at 44.6430, -63.5800?"}]


async def check(model: str) -> dict:
    llm = LLM(models=[model], mode="live", max_calls=2)
    t0 = time.perf_counter()
    try:
        msg = await llm.chat(PROMPT, TOOL)
    except LLMUnavailable as e:
        return {"model": model, "ok": False, "error": str(e)[:160]}
    calls = msg.tool_calls or []
    args = json.loads(calls[0].function.arguments) if calls else {}
    ok = bool(calls) and calls[0].function.name == "find_municipality" and abs(args.get("lat", 0) - 44.643) < 0.01
    return {"model": model, "ok": ok, "seconds": round(time.perf_counter() - t0, 1),
            "tool_call": calls[0].function.name if calls else None, "args": args,
            "text": (msg.content or "")[:80]}


async def main():
    models = sys.argv[1:] or settings.llm_models
    for m in models:
        print(json.dumps(await check(m)))


if __name__ == "__main__":
    asyncio.run(main())
