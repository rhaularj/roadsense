"""MCP server (Location): where is the damage, and which road authority is responsible for that road."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..common.db import session
from ..core import geo, open311

mcp = FastMCP("roadsense-geo")
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _check(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ToolError("lat/lon out of range")


@mcp.tool(name="geo_reverse_geocode", annotations=READ)
def reverse_geocode(lat: float, lon: float) -> dict:
    """Street, road class and route number, suburb, municipality, province and country for a position (OpenStreetMap)."""
    _check(lat, lon)
    with session() as conn:
        return geo.reverse_geocode(conn, lat, lon)


@mcp.tool(name="geo_find_jurisdiction", annotations=READ)
def find_jurisdiction(lat: float, lon: float) -> dict:
    """Which road authority maintains the road at this position: ranked candidates with confidence and evidence
    (100-series highways are provincial; numbered routes through a municipality are ambiguous), plus how each
    candidate can be reached (open311 API, referral package, or none)."""
    _check(lat, lon)
    with session() as conn:
        place = geo.reverse_geocode(conn, lat, lon)
    candidates = []
    for c in geo.jurisdiction_candidates(place):
        info = open311.service_info(c["authority"])
        candidates.append({**c, "authority": info["authority"] if info else c["authority"],
                           "channel": info["channel"] if info else "none"})
    return {"address": place.get("address"), "road": place.get("road"), "road_class": place.get("road_class"),
            "road_ref": place.get("road_ref"), "municipality": place.get("municipality"), "candidates": candidates}


if __name__ == "__main__":
    mcp.run()
