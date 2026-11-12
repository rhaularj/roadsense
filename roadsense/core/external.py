"""Requests and detections RoadSense did not make: the city's own service requests and third-party feeds.

City service requests (read-only). HRM records pothole requests in Cityworks and publishes them on its ArcGIS Hub
open-data portal. `sync_city_requests` reads any ArcGIS FeatureServer layer (ROADSENSE_CITY_SR_LAYER_URL) and stores
open and recently closed requests, so dedupe can say "the city already has this one" and follow-up can see closures
for reports filed by any channel. It needs no write access and no IT approval.

Third-party feeds (aggregator mode). Fleet and connected-vehicle data (Waze for Cities, Samsara, Nexar) is
increasingly free. `ingest_detections` takes normalised sightings from any source; they never become reports on their
own (no verifier evidence, no photo), but they corroborate RoadSense reports at the same spot and are shown to the
reviewer. `parse_waze_alerts` turns a Waze for Cities alerts feed into that shape.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import httpx

from ..common.config import settings
from ..common.db import audit, now
from ..edge.gps import haversine_m

POTHOLE_WORDS = ("pothole", "pot hole", "road surface", "pavement", "asphalt")


def _iso(value) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):  # ArcGIS dates are epoch milliseconds
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="seconds")
    return str(value)


def _field(attrs: dict, *names):
    lower = {k.lower(): v for k, v in attrs.items()}
    for n in names:
        if n.lower() in lower and lower[n.lower()] not in (None, ""):
            return lower[n.lower()]
    return None


def _store(conn: sqlite3.Connection, rec: dict) -> bool:
    exists = conn.execute("SELECT status FROM external_requests WHERE id = ?", (rec["id"],)).fetchone()
    conn.execute(
        "INSERT INTO external_requests (id, source, kind, status, lat, lon, description, reported_at, closed_at, raw,"
        " synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status = excluded.status, "
        "closed_at = excluded.closed_at, description = excluded.description, synced_at = excluded.synced_at",
        (rec["id"], rec["source"], rec.get("kind"), rec.get("status"), rec["lat"], rec["lon"],
         (rec.get("description") or "")[:1000], rec.get("reported_at"), rec.get("closed_at"),
         json.dumps(rec.get("raw") or {}, default=str)[:4000], now()))
    return exists is None


def sync_city_requests(conn: sqlite3.Connection, layer_url: str | None = None, where: str | None = None,
                       client: httpx.Client | None = None) -> dict:
    """Read open/closed service requests from an ArcGIS FeatureServer/MapServer layer (GeoJSON output, WGS84)."""
    url = (layer_url or settings.city_sr_layer_url).rstrip("/")
    if not url:
        return {"configured": False}
    http = client or httpx.Client(timeout=30)
    params = {"where": where or settings.city_sr_where, "outFields": "*", "outSR": 4326, "f": "geojson",
              "resultRecordCount": 2000}
    try:
        r = http.get(f"{url}/query", params=params)
        r.raise_for_status()
        features = r.json().get("features", [])
    except (httpx.HTTPError, ValueError) as e:
        return {"configured": True, "error": str(e)[:300]}
    added = updated = skipped = 0
    for f in features:
        attrs, geom = f.get("properties") or {}, f.get("geometry") or {}
        if geom.get("type") != "Point":
            skipped += 1
            continue
        kind = str(_field(attrs, "request_type", "problem", "description", "type", "category", "descript") or "")
        text = " ".join(str(v) for v in attrs.values() if isinstance(v, str)).lower()
        if not any(w in text for w in POTHOLE_WORDS):
            skipped += 1
            continue
        status = str(_field(attrs, "status", "sr_status", "state") or "open").lower()
        rid = _field(attrs, "requestid", "request_id", "sr_number", "objectid", "id") or f.get("id")
        new = _store(conn, {
            "id": f"city:{rid}", "source": "city_sr", "kind": kind[:80],
            "status": "closed" if any(s in status for s in ("clos", "complete", "cancel", "resolved")) else "open",
            "lon": geom["coordinates"][0], "lat": geom["coordinates"][1],
            "description": str(_field(attrs, "description", "details", "comments") or kind),
            "reported_at": _iso(_field(attrs, "initiateddate", "dateinvtdone", "created_date", "reported_date")),
            "closed_at": _iso(_field(attrs, "closeddate", "closed_date", "datetimeclosed")), "raw": attrs})
        added, updated = added + new, updated + (not new)
    closed = close_reports_fixed_by_city(conn)
    audit(conn, "sync", "city_requests_synced", None, {"added": added, "updated": updated, "skipped": skipped,
                                                      "reports_fixed": closed})
    return {"configured": True, "added": added, "updated": updated, "skipped": skipped, "reports_fixed": closed}


def close_reports_fixed_by_city(conn: sqlite3.Connection) -> list[int]:
    """A RoadSense report linked to a city request that the city closed is marked fixed (closed-loop status)."""
    from . import reports

    fixed = []
    for r in conn.execute("SELECT r.id FROM reports r JOIN external_requests x ON x.report_id = r.id "
                          "WHERE x.source = 'city_sr' AND x.status = 'closed' AND r.status = 'submitted'").fetchall():
        reports.set_status(conn, r["id"], "fixed", "sync:city")
        fixed.append(r["id"])
    return fixed


def ingest_detections(conn: sqlite3.Connection, source: str, items: list[dict], radius_m: float | None = None) -> dict:
    """Normalised third-party sightings: {id, lat, lon, kind?, reported_at?, description?}."""
    from . import reports

    radius = radius_m or settings.dedupe_radius_m * 2  # third-party positions are coarser than ours
    added = matched = 0
    for it in items:
        rec = {"id": f"{source}:{it['id']}", "source": source, "kind": it.get("kind", "pothole"),
               "status": it.get("status", "open"), "lat": float(it["lat"]), "lon": float(it["lon"]),
               "description": it.get("description"), "reported_at": it.get("reported_at"), "raw": it}
        added += _store(conn, rec)
        for rep in reports.find_nearby(conn, rec["lat"], rec["lon"], None, radius):
            if haversine_m(rec["lat"], rec["lon"], rep["lat"], rep["lon"]) <= radius:
                reports.link_external(conn, rep, radius)
                matched += 1
                break
    audit(conn, f"feed:{source}", "external_ingested", None, {"items": len(items), "added": added,
                                                              "matched": matched})
    return {"source": source, "items": len(items), "added": added, "matched_reports": matched}


def parse_waze_alerts(feed: dict) -> list[dict]:
    """Waze for Cities (Partner Hub) alerts feed → normalised sightings (pothole hazards only)."""
    out = []
    for a in feed.get("alerts", []):
        if "POT_HOLE" not in str(a.get("subtype", "")).upper():
            continue
        loc = a.get("location") or {}
        out.append({"id": a.get("uuid") or a.get("id"), "lat": loc.get("y"), "lon": loc.get("x"), "kind": "pothole",
                    "reported_at": _iso(a.get("pubMillis")), "description": a.get("street") or "Waze pothole alert",
                    "reliability": a.get("reliability")})
    return [o for o in out if o["id"] and o["lat"] is not None and o["lon"] is not None]
