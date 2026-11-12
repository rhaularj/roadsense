"""Address, road and jurisdiction lookup: OpenStreetMap Nominatim with a SQLite cache and an offline Halifax fixture."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time

import httpx

from ..common.config import settings

# Halifax Regional Municipality, rough bounding box (lat_min, lat_max, lon_min, lon_max)
OFFLINE_REGIONS = [("Halifax Regional Municipality", "Nova Scotia", (44.40, 45.25, -64.20, -62.50))]
# Offline road fixture (approximate OSM geometry) so routing works without network: (name, class, ref, a, b, buffer m)
OFFLINE_ROADS = [
    ("Highway 102", "motorway", "NS 102", (44.66842, -63.67697), (44.69157, -63.68247), 80),
    ("Bedford Highway", "primary", "NS 2", (44.66249, -63.62983), (44.69819, -63.66102), 40),
]
PROVINCIAL = "Nova Scotia Public Works"
_lock = threading.Lock()
_last_call = 0.0
_down_until = 0.0  # circuit breaker: after a failure, use the offline fixture for a while instead of waiting again
NETWORK_TIMEOUT_S, BREAK_S = 5, 120


def _seg_distance_m(p, a, b) -> float:
    """Distance from point p to segment ab in metres (local flat approximation)."""
    k = 111_320.0
    c = math.cos(math.radians(p[0]))
    ax, ay, bx, by, px, py = a[1] * k * c, a[0] * k, b[1] * k * c, b[0] * k, p[1] * k * c, p[0] * k
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _offline(lat: float, lon: float) -> dict:
    out = {"address": f"near {lat:.5f}, {lon:.5f}", "municipality": None, "province": None, "country": None,
           "road": None, "road_class": None, "road_ref": None, "source": "offline_fixture"}
    for name, province, (a, b, c, d) in OFFLINE_REGIONS:
        if a <= lat <= b and c <= lon <= d:
            out.update(municipality=name, province=province, country="Canada")
    for name, cls, ref, pa, pb, buf in OFFLINE_ROADS:
        if _seg_distance_m((lat, lon), pa, pb) <= buf:
            out.update(road=name, road_class=cls, road_ref=ref, address=f"{name} near {lat:.5f}, {lon:.5f}")
    return out


def _municipality(addr: dict) -> str | None:
    # The local government that maintains the road: OSM's "municipality" (e.g. Halifax Regional Municipality, which
    # contains the communities Halifax, Dartmouth, Bedford...), else the city/town itself
    return (addr.get("municipality") or addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("county") or None)


def reverse_geocode(conn: sqlite3.Connection, lat: float, lon: float) -> dict:
    global _last_call, _down_until
    key = f"v3:{lat:.4f},{lon:.4f}"  # ~10 m cells: one lookup serves every sighting of the same spot
    hit = conn.execute("SELECT value FROM geocache WHERE key = ?", (key,)).fetchone()
    if hit:
        return {**json.loads(hit["value"]), "cached": True}
    if settings.offline_geo or time.monotonic() < _down_until:
        return _offline(lat, lon)
    try:
        with _lock:  # Nominatim usage policy: at most 1 request per second, identify the application
            wait = 1.05 - (time.monotonic() - _last_call)
            if wait > 0:
                time.sleep(wait)
            # zoom 17 = streets, so the matched object is the road itself, with its class and route number
            r = httpx.get(f"{settings.nominatim_url}/reverse", timeout=NETWORK_TIMEOUT_S,
                          params={"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "namedetails": 1,
                                  "zoom": 17},
                          headers={"User-Agent": settings.nominatim_user_agent})
            _last_call = time.monotonic()
        r.raise_for_status()
        data = r.json()
        addr = data.get("address", {})
        is_road = data.get("category") == "highway"
        road = addr.get("road") or (data.get("name") if is_road else None)
        result = {"address": road or data.get("display_name", key),
                  "suburb": addr.get("suburb") or addr.get("neighbourhood"),
                  "municipality": _municipality(addr), "province": addr.get("state"), "country": addr.get("country"),
                  "road": road, "road_class": data.get("type") if is_road else None,
                  "road_ref": (data.get("namedetails") or {}).get("ref") if is_road else None,
                  "source": "openstreetmap_nominatim"}
    except (httpx.HTTPError, ValueError):
        _down_until = time.monotonic() + BREAK_S
        return _offline(lat, lon)
    conn.execute("INSERT OR REPLACE INTO geocache (key, value) VALUES (?, ?)", (key, json.dumps(result)))
    conn.commit()
    return result


_snap_down_until = 0.0


def snap_to_road(conn: sqlite3.Connection, lat: float, lon: float) -> dict:
    """Nearest point on the drivable road network (OSRM "nearest"). GPS drifts 5-10 m and the camera projection adds
    its own error, so a defect can land beside the road; potholes are on it. Snaps only within settings.max_snap_m:
    a point farther away is more likely a parking lot or private road than a GPS error, and is left as measured.
    Returns {lat, lon, snapped, distance_m, road}."""
    global _snap_down_until
    out = {"lat": lat, "lon": lon, "snapped": False, "distance_m": None, "road": None}
    if settings.offline_geo or time.monotonic() < _snap_down_until:
        return out
    key = f"snap:{lat:.5f},{lon:.5f}"
    hit = conn.execute("SELECT value FROM geocache WHERE key = ?", (key,)).fetchone()
    if hit:
        return json.loads(hit["value"])
    try:
        r = httpx.get(f"{settings.osrm_url}/nearest/v1/driving/{lon},{lat}", params={"number": 1},
                      timeout=NETWORK_TIMEOUT_S, headers={"User-Agent": settings.nominatim_user_agent})
        r.raise_for_status()
        w = r.json()["waypoints"][0]
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        _snap_down_until = time.monotonic() + BREAK_S
        return out
    if w["distance"] <= settings.max_snap_m:
        out = {"lat": round(w["location"][1], 6), "lon": round(w["location"][0], 6), "snapped": True,
               "distance_m": round(w["distance"], 1), "road": w.get("name") or None}
    else:
        out.update(distance_m=round(w["distance"], 1), road=w.get("name") or None)
    conn.execute("INSERT OR REPLACE INTO geocache (key, value) VALUES (?, ?)", (key, json.dumps(out)))
    conn.commit()
    return out


def jurisdiction_candidates(place: dict) -> list[dict]:
    """Who maintains this road, best first, with confidence and the evidence for each.

    100-series highways and motorways are provincial. Other numbered provincial routes (NS 2, Trunk 7, Route 333...)
    run through municipalities and ownership varies by section, so they are returned as ambiguous for the agent to
    weigh; local streets belong to the municipality."""
    from .open311 import rules

    r = rules()
    provincial = r.get("provincial_authority", PROVINCIAL)
    lo, hi = r.get("provincial_route_range", [100, 199])
    muni, cls, ref = place.get("municipality"), place.get("road_class"), place.get("road_ref") or ""
    numbers = [int(n) for n in re.findall(r"\d+", ref)]
    if cls in r.get("provincial_road_classes", ["motorway", "motorway_link"]) or any(lo <= n <= hi for n in numbers):
        return [{"authority": provincial, "confidence": "high",
                 "evidence": f"{place.get('road') or 'road'} is a {lo}-series highway ({ref or cls})"},
                {"authority": muni, "confidence": "low", "evidence": "municipality surrounding the highway"}]
    if numbers or cls in r.get("ambiguous_road_classes", ["trunk"]):
        return [{"authority": muni, "confidence": "medium",
                 "evidence": f"numbered route {ref or cls} inside {muni}; many urban sections are municipally "
                             "maintained"},
                {"authority": provincial, "confidence": "medium",
                 "evidence": f"{ref or cls} is a numbered provincial route; rural sections are provincially maintained"}]
    return [{"authority": muni, "confidence": "high" if muni else "low",
             "evidence": f"local road ({cls or 'unknown class'}) in {muni or 'unknown municipality'}"}]
