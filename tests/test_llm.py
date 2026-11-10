import asyncio

import pytest

from roadsense.agents.llm import LLM, LLMUnavailable, cache_key


def test_cache_key_ignores_timestamps_and_ids():
    a = [{"role": "tool", "content": '{"id": "call_abc", "created_at": "2026-11-02T18:45:12+00:00", "x": 1}'}]
    b = [{"role": "tool", "content": '{"id": "call_xyz", "created_at": "2026-11-03T09:00:01+00:00", "x": 1}'}]
    c = [{"role": "tool", "content": '{"id": "call_abc", "created_at": "2026-11-02T18:45:12+00:00", "x": 2}'}]
    assert cache_key(["m"], a, None) == cache_key(["m"], b, None) != cache_key(["m"], c, None)


def test_live_mode_needs_a_key():
    with pytest.raises(LLMUnavailable, match="OPENROUTER_API_KEY"):
        LLM(mode="live")


def test_replay_mode_never_calls_the_network(db):
    llm = LLM(mode="replay")
    with pytest.raises(LLMUnavailable, match="no cached response"):
        asyncio.run(llm.chat([{"role": "user", "content": "hello"}]))


def test_call_budget(db):
    llm = LLM(mode="replay", max_calls=0)
    with pytest.raises(LLMUnavailable, match="budget"):
        asyncio.run(llm.chat([{"role": "user", "content": "hello"}]))
