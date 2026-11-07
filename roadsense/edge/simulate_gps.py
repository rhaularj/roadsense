"""Write a simulated GPX track along a real Halifax route, for dashcam clips recorded without GPS.

    python -m roadsense.edge.simulate_gps --out clips/halifax.gpx --speed 40
    python -m roadsense.edge.simulate_gps --refresh      # re-fetch the route geometry from OSRM

The route is the street geometry of a drivable path (South Park St, Spring Garden Rd, Barrington St, South St),
computed by OSRM over OpenStreetMap and stored in halifax_route.json, so simulated positions stay on the road.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gps import simulate_route, write_gpx

ROUTE_FILE = Path(__file__).with_name("halifax_route.json")
WAYPOINTS = [(44.6427, -63.5803), (44.6444, -63.5739), (44.6395, -63.5712)]  # via points the route must pass


def load_route() -> list[tuple[float, float]]:
    return [tuple(p) for p in json.loads(ROUTE_FILE.read_text(encoding="utf-8"))["points"]]


HALIFAX_ROUTE = load_route()


def refresh(osrm_url: str = "https://router.project-osrm.org") -> int:
    import httpx

    coords = ";".join(f"{lon},{lat}" for lat, lon in WAYPOINTS)
    r = httpx.get(f"{osrm_url}/route/v1/driving/{coords}", params={"overview": "full", "geometries": "geojson"},
                  timeout=20).raise_for_status().json()["routes"][0]
    data = json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    data.update(distance_m=round(r["distance"]),
                points=[[round(lat, 6), round(lon, 6)] for lon, lat in r["geometry"]["coordinates"]])
    ROUTE_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return len(data["points"])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out")
    p.add_argument("--speed", type=float, default=40.0, help="km/h")
    p.add_argument("--refresh", action="store_true", help="re-fetch the road geometry from OSRM")
    args = p.parse_args()
    if args.refresh:
        print(f"route refreshed: {refresh()} points")
    if args.out:
        fixes = simulate_route(load_route(), args.speed)
        write_gpx(fixes, args.out, name="Simulated Halifax route")
        print(f"wrote {len(fixes)} fixes ({(fixes[-1].time - fixes[0].time).total_seconds():.0f} s) to {args.out}")


if __name__ == "__main__":
    main()
