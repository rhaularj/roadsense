"""Segment-level condition estimate and per-defect deterioration.

Capital planning works on road segments (HRM: a 0-100 Pavement Quality Index; US practice: PCI per ASTM D6433, which
converts distress type, severity and extent into deduct values). RoadSense sees defects, not a full survey, so this is
an ESTIMATE in the same spirit: each open defect on a segment deducts points by type and severity band, scaled by
density per 100 m, and the index is 100 minus the capped total. It is labelled as an estimate everywhere; it is
not a certified pavement survey.

Repeated passes are what a survey van cannot do: dedupe already links every sighting of a defect, so its severity
over time is a deterioration curve.
"""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime

from ..edge.gps import haversine_m

# deduct points per defect, by class and band (shaped after ASTM D6433 deduct curves, simplified)
DEDUCT = {"D40": {"S1": 8, "S2": 15, "S3": 25, "S4": 35}, "D20": {"S1": 5, "S2": 10, "S3": 18, "S4": 25},
          "D10": {"S1": 2, "S2": 4, "S3": 6, "S4": 8}, "D00": {"S1": 2, "S2": 4, "S3": 6, "S4": 8}}
BIN_M = 100.0
OPEN = ("pending_approval", "approved", "submitted", "delivery_failed")


def rating(index: float) -> str:
    return "good" if index >= 70 else "fair" if index >= 55 else "poor" if index >= 40 else "very poor"


def _segment_key(r: dict) -> tuple[str, int]:
    """Road name + 100 m bin along the road (projected on the dominant axis: good enough for a city street grid)."""
    name = r.get("road_name") or (r.get("address") or "").split(" near ")[0]
    if not name or name.startswith("near "):  # the offline geocoder's "near lat, lon" is not a road name
        name = "Unnamed road"
    meters = r["lat"] * 111_000 if abs(math.cos(math.radians(r["lat"]))) < 0.5 else r["lon"] * 111_000 * math.cos(
        math.radians(r["lat"]))
    return name, int(meters // BIN_M)


def segments(conn: sqlite3.Connection) -> list[dict]:
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM reports WHERE status IN ({','.join('?' * len(OPEN))})", OPEN)]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[_segment_key(r)].append(r)
    out = []
    for (name, _bin), items in groups.items():
        lats, lons = [i["lat"] for i in items], [i["lon"] for i in items]
        length = max(haversine_m(min(lats), min(lons), max(lats), max(lons)), BIN_M)
        deducts = sorted((DEDUCT.get(i["class_code"], DEDUCT["D00"]).get(i.get("severity_band") or "S2", 10)
                          for i in items), reverse=True)
        # diminishing returns for many defects, like PCI's corrected deduct value
        total = sum(d * (0.85 ** k) for k, d in enumerate(deducts)) * (BIN_M / length)
        index = max(0.0, round(100 - min(total, 100), 1))
        out.append({"road": name, "lat": sum(lats) / len(lats), "lon": sum(lons) / len(lons), "defects": len(items),
                    "potholes": sum(i["class_code"] == "D40" for i in items),
                    "priority1": sum(bool(i.get("p1_candidate")) for i in items),
                    "condition_index": index, "rating": rating(index), "report_ids": [i["id"] for i in items],
                    "estimate": True})
    return sorted(out, key=lambda s: s["condition_index"])


def deterioration(conn: sqlite3.Connection, report_id: int) -> dict:
    """Severity and size of one defect at each independent pass, and the trend."""
    events = [dict(e) for e in conn.execute(
        "SELECT id, trip_id, captured_at, width_m, box_area_ratio, confidence FROM events WHERE report_id = ? "
        "AND suppressed_by IS NULL ORDER BY captured_at", (report_id,))]
    points = []
    for e in events:
        size = e["width_m"] if e["width_m"] is not None else e["box_area_ratio"]
        points.append({"event_id": e["id"], "trip_id": e["trip_id"], "at": e["captured_at"], "size": size,
                       "unit": "m" if e["width_m"] is not None else "frame share"})
    trend, per_week = "insufficient data", None
    if len(points) >= 2:
        try:
            t0, t1 = (datetime.fromisoformat(points[i]["at"].replace("Z", "+00:00")) for i in (0, -1))
            days = max((t1 - t0).total_seconds() / 86400, 1e-6)
            delta = points[-1]["size"] - points[0]["size"]
            per_week = round(delta / days * 7, 4)
            rel = delta / max(points[0]["size"], 1e-6)
            trend = "worsening" if rel > 0.15 else "improving" if rel < -0.15 else "stable"
        except (ValueError, TypeError):
            pass
    return {"report_id": report_id, "passes": len(points), "points": points, "trend": trend,
            "growth_per_week": per_week}
