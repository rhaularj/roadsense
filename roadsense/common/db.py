"""SQLite store shared by the agent API and the MCP servers (separate processes, so WAL mode)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    track_id INTEGER,
    class_code TEXT NOT NULL,
    class_name TEXT NOT NULL,
    confidence REAL NOT NULL,
    frames_seen INTEGER NOT NULL,
    box_area_ratio REAL NOT NULL,
    box TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    heading REAL,
    captured_at TEXT NOT NULL,
    image_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    verified_confidence REAL,
    report_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL,
    class_code TEXT NOT NULL,
    class_name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    address TEXT,
    municipality TEXT,
    severity TEXT NOT NULL,
    priority REAL NOT NULL,
    confirmations INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending_approval',
    description TEXT,
    best_event_id TEXT,
    service_request_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    report_id INTEGER,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geocache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    role TEXT NOT NULL,
    password_hash TEXT,
    oidc_subject TEXT UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    args TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT,
    result TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    started TEXT,
    finished TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs (status, created);
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    channel TEXT,
    ok INTEGER NOT NULL,
    detail TEXT,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS external_requests (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    kind TEXT,
    status TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    description TEXT,
    reported_at TEXT,
    closed_at TEXT,
    report_id INTEGER,
    raw TEXT,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS external_pos ON external_requests (lat, lon);
CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    report_id INTEGER,
    label TEXT NOT NULL,
    class_code TEXT,
    actor TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""

# columns added after the first schema; applied to existing databases on connect
MIGRATIONS = {
    "events": {"car_lat": "REAL", "car_lon": "REAL", "distance_m": "REAL", "width_m": "REAL",
               "position_uncertainty_m": "REAL", "verifier_class": "TEXT", "recheck_confidence": "REAL",
               "class_disputed": "INTEGER NOT NULL DEFAULT 0", "rationale": "TEXT", "snap_m": "REAL",
               "jolt_g": "REAL", "server_redacted": "INTEGER NOT NULL DEFAULT 0", "suppressed_by": "INTEGER",
               "road_class": "TEXT", "road_name": "TEXT"},
    "reports": {"jurisdiction": "TEXT", "channel": "TEXT", "width_m": "REAL", "p1_candidate": "INTEGER DEFAULT 0",
                "class_disputed": "INTEGER NOT NULL DEFAULT 0", "rationale": "TEXT", "draft_description": "TEXT",
                "approved_payload_hash": "TEXT", "submitted_payload_hash": "TEXT",
                # the exact payload the reviewer approved: delivery sends this snapshot, never a rebuilt one
                "approved_payload": "TEXT", "approved_by": "TEXT", "approved_at": "TEXT", "rejected_by": "TEXT",
                "delivery_attempts": "INTEGER NOT NULL DEFAULT 0", "last_error": "TEXT", "next_attempt_at": "TEXT",
                "external_ref": "TEXT", "corroborations": "INTEGER NOT NULL DEFAULT 0",
                "severity_band": "TEXT", "repair_target_days": "INTEGER", "road_class": "TEXT", "road_name": "TEXT",
                "pending_update": "INTEGER NOT NULL DEFAULT 0"},
}

REPORT_STATUSES = ("pending_approval", "approved", "rejected", "submitted", "fixed", "delivery_failed")
EVENT_STATUSES = ("received", "checked", "verified", "rejected", "processed")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    for table, columns in MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    return conn


@contextmanager
def session(path: Path | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def audit(conn: sqlite3.Connection, actor: str, action: str, subject: str | None = None, detail=None) -> None:
    text = detail if isinstance(detail, str) or detail is None else json.dumps(detail, default=str)
    conn.execute("INSERT INTO audit (ts, actor, action, subject, detail) VALUES (?, ?, ?, ?, ?)",
                 (now(), actor, action, subject, text[:4000] if text else text))
