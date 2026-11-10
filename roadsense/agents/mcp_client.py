"""Connects to the four RoadSense MCP servers over stdio and exposes their tools to the agents."""
from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..common.config import PROJECT_ROOT

SERVERS = {
    "detector": "roadsense.mcp_servers.detector_server",
    "geo": "roadsense.mcp_servers.geo_server",
    "reports": "roadsense.mcp_servers.reports_server",
    "municipality": "roadsense.mcp_servers.municipality_server",
}


class Toolbox:
    """Async context manager: starts each MCP server as a subprocess and routes tool calls to the right one.

    MCP sessions are bound to the task that opened them, so one worker task should own a Toolbox."""

    def __init__(self, servers: dict[str, str] | None = None):
        self.servers = servers or SERVERS
        self.tools: dict[str, tuple[str, ClientSession, object]] = {}
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> Toolbox:
        env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "PYTHONUNBUFFERED": "1"}
        for name, module in self.servers.items():
            params = StdioServerParameters(command=sys.executable, args=["-m", module], cwd=str(PROJECT_ROOT), env=env)
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                self.tools[tool.name] = (name, session, tool)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    def schemas(self, names: list[str]) -> list[dict]:
        """OpenAI-style function definitions for the given tool names (an agent's allow-list)."""
        out = []
        for n in names:
            _, _, tool = self.tools[n]
            out.append({"type": "function", "function": {"name": n, "description": tool.description or n,
                                                         "parameters": tool.inputSchema}})
        return out

    async def call(self, name: str, args: dict) -> dict:
        if name not in self.tools:
            return {"error": f"unknown tool {name}"}
        _, session, _ = self.tools[name]
        result = await session.call_tool(name, args)
        texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
        if result.isError:
            return {"error": " ".join(texts) or "tool failed"}
        if result.structuredContent:
            sc = result.structuredContent
            return sc["result"] if set(sc) == {"result"} else sc
        try:
            return json.loads(texts[0]) if texts else {}
        except json.JSONDecodeError:
            return {"text": texts[0]}
