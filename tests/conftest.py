import os
import tempfile

# Settings are read at import time: point every test at a throwaway data dir, offline geocoding and no LLM.
_tmp = tempfile.mkdtemp(prefix="roadsense-test-")
os.environ.update(ROADSENSE_DATA_DIR=_tmp, ROADSENSE_OFFLINE_GEO="1", ROADSENSE_USE_LLM="0",
                  ROADSENSE_API_TOKEN="test-token", ROADSENSE_OPEN311_API_KEY="test-key", OPENROUTER_API_KEY="")

import json  # noqa: E402

import pytest  # noqa: E402

from roadsense.common.config import settings  # noqa: E402
from roadsense.common.db import now, session  # noqa: E402


@pytest.fixture
def db():
    # the audit log is append-only by design, so tests start from a fresh database file
    for suffix in ("", "-wal", "-shm"):
        path = settings.db_path.with_name(settings.db_path.name + suffix)
        if path.exists():
            path.unlink()
    yield


def add_event(event_id: str, lat: float, lon: float, code: str = "D40", trip: str = "trip1", status: str = "verified",
              area: float = 0.03, conf: float = 0.8, frames: int = 5):
    with session() as conn:
        conn.execute(
            "INSERT INTO events (id, trip_id, track_id, class_code, class_name, confidence, frames_seen, box_area_ratio,"
            " box, lat, lon, heading, captured_at, image_path, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, trip, 1, code, "Pothole" if code == "D40" else "Crack", conf, frames, area, json.dumps([0, 0, 10, 10]),
             lat, lon, 90.0, now(), "missing.jpg", status, now()))
