"""GPS track for a dashcam video: load GPX or CSV, then look up position and heading at any video time."""
from __future__ import annotations

import bisect
import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class Fix:
    time: datetime
    lat: float
    lon: float


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _parse_time(value: str) -> datetime:
    t = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class GpsTrack:
    """Time-ordered GPS fixes. Video time t (seconds) maps to start + offset + t."""

    def __init__(self, fixes: list[Fix], offset_s: float = 0.0):
        if len(fixes) < 2:
            raise ValueError("a GPS track needs at least 2 fixes")
        self.fixes = sorted(fixes, key=lambda f: f.time)
        self.offset_s = offset_s
        self._times = [f.time.timestamp() for f in self.fixes]

    @property
    def start(self) -> datetime:
        return self.fixes[0].time

    @classmethod
    def load(cls, path: str | Path, offset_s: float = 0.0) -> GpsTrack:
        path = Path(path)
        if path.suffix.lower() == ".gpx":
            import gpxpy

            with open(path, encoding="utf-8") as f:
                gpx = gpxpy.parse(f)
            fixes = [Fix(p.time if p.time.tzinfo else p.time.replace(tzinfo=timezone.utc), p.latitude, p.longitude)
                     for trk in gpx.tracks for seg in trk.segments for p in seg.points if p.time]
        elif path.suffix.lower() == ".csv":
            with open(path, newline="", encoding="utf-8") as f:
                fixes = [Fix(_parse_time(r["time"]), float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)]
        else:
            raise ValueError(f"unsupported GPS file {path.name}: use .gpx or .csv (time,lat,lon)")
        return cls(fixes, offset_s)

    def at(self, video_t: float) -> tuple[float, float, float, datetime]:
        """(lat, lon, heading in degrees, absolute time) at video_t seconds, linearly interpolated and clamped."""
        ts = self._times[0] + self.offset_s + video_t
        i = min(max(bisect.bisect_right(self._times, ts), 1), len(self.fixes) - 1)
        a, b = self.fixes[i - 1], self.fixes[i]
        span = self._times[i] - self._times[i - 1]
        w = min(max((ts - self._times[i - 1]) / span, 0.0), 1.0) if span > 0 else 0.0
        lat, lon = a.lat + w * (b.lat - a.lat), a.lon + w * (b.lon - a.lon)
        when = datetime.fromtimestamp(ts, tz=timezone.utc)
        return lat, lon, bearing_deg(a.lat, a.lon, b.lat, b.lon), when


def write_gpx(fixes: list[Fix], path: str | Path, name: str = "RoadSense route") -> None:
    import gpxpy.gpx

    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack(name=name)
    segment = gpxpy.gpx.GPXTrackSegment()
    segment.points = [gpxpy.gpx.GPXTrackPoint(f.lat, f.lon, time=f.time) for f in fixes]
    track.segments.append(segment)
    gpx.tracks.append(track)
    Path(path).write_text(gpx.to_xml(), encoding="utf-8")


def simulate_route(waypoints: list[tuple[float, float]], speed_kmh: float, start: datetime | None = None,
                   step_s: float = 1.0) -> list[Fix]:
    """1 Hz fixes driving along straight segments between waypoints at constant speed."""
    start = start or datetime.now(timezone.utc).replace(microsecond=0)
    speed = speed_kmh / 3.6
    fixes, t = [Fix(start, *waypoints[0])], 0.0
    for (lat1, lon1), (lat2, lon2) in zip(waypoints, waypoints[1:]):
        seg_s = haversine_m(lat1, lon1, lat2, lon2) / speed
        k = 1
        while k * step_s < seg_s:
            w = k * step_s / seg_s
            fixes.append(Fix(start + timedelta(seconds=t + k * step_s), lat1 + w * (lat2 - lat1), lon1 + w * (lon2 - lon1)))
            k += 1
        t += seg_s
        fixes.append(Fix(start + timedelta(seconds=t), lat2, lon2))
    return fixes


def points_along(route: list[tuple[float, float]], spacing_m: float) -> list[tuple[float, float]]:
    """Points every `spacing_m` metres along a polyline (on the road when the polyline follows it)."""
    out, carry = [route[0]], 0.0
    for (lat1, lon1), (lat2, lon2) in zip(route, route[1:]):
        seg = haversine_m(lat1, lon1, lat2, lon2)
        d = spacing_m - carry
        while d <= seg:
            w = d / seg
            out.append((lat1 + w * (lat2 - lat1), lon1 + w * (lon2 - lon1)))
            d += spacing_m
        carry = seg - (d - spacing_m)
    return out
