"""OpenRouter chat client with tool calling, built for free-tier limits.

- One request carries the whole fallback chain (OpenRouter `models` array), and `require_parameters` keeps
  tool-calling requests away from providers that cannot do tools.
- A client-side token bucket keeps under the free tier's requests/minute; 429s honour Retry-After.
- Responses are cached in SQLite. Mode `cache` (default) reads through the cache, so eval reruns and video takes do
  not burn quota; mode `replay` never calls the network, which gives a keyless demo; mode `live` skips the cache.
- A per-run call budget stops a looping agent.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time

import httpx
from openai import APIError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessage

from ..common.config import settings
from ..common.db import session

CACHE_SCHEMA = "CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, model TEXT, message TEXT, usage TEXT)"
# timestamps and random ids change between runs but not the meaning of a prompt; drop them from the cache key
_VOLATILE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00|Z)?|call_[A-Za-z0-9]+|\"id\": ?\"[^\"]*\"")


class LLMUnavailable(RuntimeError):
    pass


class _Bucket:
    def __init__(self, per_minute: int):
        self.interval = 60.0 / max(per_minute, 1)
        self.next_at = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            delay = self.next_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_at = max(self.next_at, time.monotonic()) + self.interval


_bucket = _Bucket(settings.llm_rpm)


def cache_key(models: list[str], messages: list[dict], tools: list[dict] | None) -> str:
    text = json.dumps([models, messages, tools or []], sort_keys=True, default=str)
    return hashlib.sha256(_VOLATILE.sub("~", text).encode()).hexdigest()


class LLM:
    def __init__(self, models: list[str] | None = None, max_calls: int = 40, mode: str | None = None):
        self.mode = mode or settings.llm_mode
        if self.mode != "replay" and not settings.openrouter_api_key:
            raise LLMUnavailable("OPENROUTER_API_KEY is not set (use ROADSENSE_LLM_MODE=replay for the keyless demo)")
        self.client = AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key or "none",
                                  timeout=90, max_retries=0,
                                  default_headers={"HTTP-Referer": "https://roadsense.local", "X-Title": "RoadSense"})
        self.models = models or settings.llm_models
        self.max_calls, self.calls, self.cache_hits = max_calls, 0, 0
        self.prompt_tokens = self.completion_tokens = 0
        self.last_model: str | None = None

    def _cached(self, key: str):
        with session() as conn:
            conn.execute(CACHE_SCHEMA)
            return conn.execute("SELECT model, message, usage FROM llm_cache WHERE key = ?", (key,)).fetchone()

    def _store(self, key: str, model: str, message: ChatCompletionMessage, usage) -> None:
        with session() as conn:
            conn.execute(CACHE_SCHEMA)
            conn.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?, ?)",
                         (key, model, message.model_dump_json(exclude_none=True), json.dumps(usage or {})))

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatCompletionMessage:
        if self.calls >= self.max_calls:
            raise LLMUnavailable(f"LLM call budget of {self.max_calls} used up")
        self.calls += 1
        key = cache_key(self.models, messages, tools)
        if self.mode in ("cache", "replay"):
            hit = self._cached(key)
            if hit:
                self.cache_hits += 1
                self.last_model = f"{hit['model']} (cached)"
                return ChatCompletionMessage.model_validate_json(hit["message"])
            if self.mode == "replay":
                raise LLMUnavailable("replay mode: no cached response for this step")

        extra = {"models": self.models[1:], "provider": {"require_parameters": True}} if tools else \
            {"models": self.models[1:]}
        for attempt in range(3):
            await _bucket.wait()
            try:
                resp = await self.client.chat.completions.create(
                    model=self.models[0], messages=messages, tools=tools or None, temperature=0.1, max_tokens=1500,
                    extra_body=extra)
            except RateLimitError as e:
                retry = e.response.headers.get("retry-after")
                await asyncio.sleep(min(float(retry) if retry and retry.isdigit() else 5.0 * (attempt + 1), 30))
                continue
            except (APITimeoutError, APIStatusError, APIError) as e:
                if attempt == 2:
                    raise LLMUnavailable(f"OpenRouter error: {str(e)[:200]}") from e
                await asyncio.sleep(2)
                continue
            if not resp.choices:
                continue
            self.last_model = resp.model or self.models[0]
            usage = resp.usage.model_dump() if resp.usage else {}
            self.prompt_tokens += usage.get("prompt_tokens") or 0
            self.completion_tokens += usage.get("completion_tokens") or 0
            message = resp.choices[0].message
            if self.mode != "live":
                self._store(key, self.last_model, message, usage)
            return message
        raise LLMUnavailable("OpenRouter rate limit: retries exhausted")

    def stats(self) -> dict:
        return {"model": self.last_model, "calls": self.calls, "cache_hits": self.cache_hits,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}


def key_status() -> dict:
    """Remaining OpenRouter quota for the configured key (free tier: 50/day, 1,000/day after $10 of credit)."""
    if not settings.openrouter_api_key:
        return {"configured": False, "mode": settings.llm_mode}
    try:
        r = httpx.get(f"{settings.openrouter_base_url}/key", timeout=10,
                      headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})
        r.raise_for_status()
        data = r.json().get("data", {})
    except httpx.HTTPError as e:
        return {"configured": True, "error": str(e)}
    return {"configured": True, "mode": settings.llm_mode, "label": data.get("label"),
            "free_tier": data.get("is_free_tier"), "usage": data.get("usage"), "limit": data.get("limit"),
            "limit_remaining": data.get("limit_remaining")}
