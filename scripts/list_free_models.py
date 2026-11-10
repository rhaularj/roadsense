#!/usr/bin/env python
"""List OpenRouter's free models that support tool calling (needed by the RoadSense agents), largest context first.

    python scripts/list_free_models.py

Put your choice, in order of preference, in ROADSENSE_LLM_MODELS in .env. The free list changes often.
"""
import httpx


def main():
    models = httpx.get("https://openrouter.ai/api/v1/models", timeout=30).raise_for_status().json()["data"]
    free = [m for m in models if m["id"].endswith(":free") and "tools" in (m.get("supported_parameters") or [])]
    for m in sorted(free, key=lambda m: -(m.get("context_length") or 0)):
        print(f"{m['id']:<55} context {m.get('context_length'):>9,}")
    print(f"\n{len(free)} free models with tool calling (of {len(models)})")


if __name__ == "__main__":
    main()
