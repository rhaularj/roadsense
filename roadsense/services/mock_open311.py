"""Mock municipal 311 system implementing the parts of Open311 GeoReport v2 that RoadSense uses.

    python -m roadsense.services.mock_open311          # http://127.0.0.1:8311, inbox at /

Endpoints: GET /services.json, POST /requests.json, GET /requests/{id}.json, GET /requests.json, plus a small
city-staff inbox page where a request can be marked closed (fixed) for the demo.
"""
from __future__ import annotations

import argparse
import html
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from ..common.config import settings
from ..common.db import now

SERVICES = [
    {"service_code": "POTHOLE", "service_name": "Pothole", "description": "Pothole on a street or road",
     "metadata": False, "type": "realtime", "keywords": "road,pothole", "group": "Streets"},
    {"service_code": "ROAD_SURFACE", "service_name": "Road surface damage", "description": "Cracked or broken pavement",
     "metadata": False, "type": "realtime", "keywords": "road,crack", "group": "Streets"},
]
SCHEMA = """CREATE TABLE IF NOT EXISTS requests (
    service_request_id INTEGER PRIMARY KEY AUTOINCREMENT, service_code TEXT, description TEXT, lat REAL, long REAL,
    address TEXT, media_url TEXT, attributes TEXT, status TEXT, status_notes TEXT, requested_datetime TEXT,
    updated_datetime TEXT)"""


def create_app(db_path: Path | None = None) -> FastAPI:
    db_path = db_path or settings.data_dir / "mock_open311.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Mock Open311 (Halifax 311 demo)")

    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(SCHEMA)
        return conn

    def as_json(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["service_request_id"] = str(d["service_request_id"])
        d.pop("attributes", None)
        return d

    @app.get("/services.json")
    def services():
        return SERVICES

    @app.post("/requests.json")
    async def create(api_key: str = Form(...), service_code: str = Form(...), lat: float = Form(...),
                     long: float = Form(...), description: str = Form(""), address_string: str = Form(""),
                     media_url: str = Form("")):
        if api_key != settings.open311_api_key:
            raise HTTPException(403, "invalid api_key")
        if service_code not in {s["service_code"] for s in SERVICES}:
            raise HTTPException(400, "unknown service_code")
        ts = now()
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO requests (service_code, description, lat, long, address, media_url, status, status_notes,"
                " requested_datetime, updated_datetime) VALUES (?, ?, ?, ?, ?, ?, 'open', 'Received', ?, ?)",
                (service_code, description[:4000], lat, long, address_string[:300], media_url[:500], ts, ts))
        return [{"service_request_id": str(cur.lastrowid), "service_notice": "Thank you, your request was received.",
                 "account_id": None}]

    @app.get("/requests/{rid}.json")
    def get_request(rid: int):
        with db() as conn:
            r = conn.execute("SELECT * FROM requests WHERE service_request_id = ?", (rid,)).fetchone()
        if r is None:
            raise HTTPException(404, "not found")
        return [as_json(r)]

    @app.get("/requests.json")
    def list_requests():
        with db() as conn:
            return [as_json(r) for r in conn.execute("SELECT * FROM requests ORDER BY service_request_id DESC")]

    @app.post("/admin/requests/{rid}/close")
    def close(rid: int, notes: str = Form("Repaired by Public Works")):
        with db() as conn:
            conn.execute("UPDATE requests SET status = 'closed', status_notes = ?, updated_datetime = ? "
                         "WHERE service_request_id = ?", (notes, now(), rid))
        return RedirectResponse("/", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def inbox():
        with db() as conn:
            rows = conn.execute("SELECT * FROM requests ORDER BY service_request_id DESC").fetchall()
        items = "".join(
            f"<tr><td>{r['service_request_id']}</td><td>{html.escape(r['service_code'])}</td>"
            f"<td>{html.escape(r['address'] or '')}<br><small>{r['lat']:.5f}, {r['long']:.5f}</small></td>"
            f"<td style='max-width:420px'>{html.escape(r['description'] or '')}</td>"
            f"<td>{html.escape(r['status'])}</td><td>"
            + ("" if r["status"] == "closed" else
               f"<form method=post action='/admin/requests/{r['service_request_id']}/close'>"
               "<button>Mark fixed</button></form>") + "</td></tr>" for r in rows)
        return f"""<!doctype html><meta charset=utf-8><title>Halifax 311 inbox (mock)</title>
<style>body{{font:14px system-ui;margin:24px}}td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left;
vertical-align:top}}</style><h2>Halifax 311 – service requests (mock Open311)</h2>
<table><tr><th>#</th><th>Service</th><th>Location</th><th>Description</th><th>Status</th><th></th></tr>{items}</table>"""

    return app


def main():
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8311)
    args = p.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
