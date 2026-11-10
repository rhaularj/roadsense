"""Integration: real MCP servers over stdio, called through the same Toolbox the agents use."""
import asyncio

from conftest import add_event

from roadsense.agents.mcp_client import Toolbox

SERVERS = {"reports": "roadsense.mcp_servers.reports_server", "geo": "roadsense.mcp_servers.geo_server"}


def test_tools_over_stdio(db):
    add_event("ev-mcp-1", 44.6430, -63.5800)

    async def run():
        async with Toolbox(SERVERS) as tb:
            assert {"reports_create_or_merge", "geo_find_jurisdiction", "reports_notify_driver"} <= set(tb.tools)
            assert tb.tools["reports_list"][2].annotations.readOnlyHint is True
            place = await tb.call("geo_find_jurisdiction", {"lat": 44.6430, "lon": -63.5800})
            made = await tb.call("reports_create_or_merge", {
                "event_id": "ev-mcp-1", "severity": "high", "jurisdiction": place["candidates"][0]["authority"],
                "rationale": "local street in HRM"})
            bad = await tb.call("reports_create_or_merge", {"event_id": "ev-mcp-1", "severity": "extreme",
                                                            "jurisdiction": "x", "rationale": "x"})
            return place, made, bad

    place, made, bad = asyncio.run(run())
    assert place["candidates"][0]["authority"] == "Halifax Regional Municipality"
    assert place["candidates"][0]["channel"] == "open311"
    assert made["action"] == "created" and made["status"] == "pending_approval"
    assert "severity" in bad["error"]  # tool errors come back as isError results the model can correct
