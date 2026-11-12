"""Road-authority directory and the exact payload a report becomes.

The payload is built deterministically from the database, so the reviewer approves exactly what will be sent: the
approval stores the payload and its hash, and delivery sends that stored snapshot (see core.delivery).

The directory is configuration, not code: authorities, aliases, channels, service codes and the regional rules
(provincial routes, Priority 1 width, severity bands, repair targets) live in a JSON file. The built-in file covers
the Halifax pilot; ROADSENSE_AUTHORITIES_FILE points at another region's file.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from ..common.config import PROJECT_ROOT, settings
from . import media

DIRECTORY = Path(__file__).with_name("municipalities.json")


@lru_cache(maxsize=4)
def _load(path: str, open311_url: str) -> dict:
    text = Path(path).read_text(encoding="utf-8").replace("${ROADSENSE_OPEN311_URL}", open311_url)
    return json.loads(text)


def _file() -> str:
    if settings.authorities_file:
        p = Path(settings.authorities_file)
        return str(p if p.is_absolute() else PROJECT_ROOT / p)
    return str(DIRECTORY)


def directory() -> dict:
    """Authorities by name (rules and other reserved keys starting with '_' left out)."""
    return {k: v for k, v in _load(_file(), settings.open311_url).items() if not k.startswith("_")}


def rules() -> dict:
    return _load(_file(), settings.open311_url).get("_rules", {})


def service_info(authority: str | None) -> dict | None:
    """Directory entry by name or alias (e.g. 'Halifax' or 'Dartmouth' → Halifax Regional Municipality)."""
    if not authority:
        return None
    wanted = authority.strip().lower()
    for name, info in directory().items():
        if wanted == name.lower() or wanted in (a.lower() for a in info.get("aliases", [])):
            return {"authority": name, **{k: v for k, v in info.items() if k != "aliases"}}
    return None


def default_description(report: dict) -> str:
    seen = "1 driver" if report["confirmations"] == 1 else f"{report['confirmations']} independent drivers"
    # width is meaningful for potholes; for a long crack the box width is its extent, not its size
    width = f", about {report['width_m'] * 100:.0f} cm wide" if report.get("width_m") and report["class_code"] == "D40" \
        else ""
    return (f"{report['class_name']} ({report['severity']} severity{width}) detected by RoadSense dashcam analysis and "
            f"confirmed by {seen}. Location: {report['address'] or 'see coordinates'}. The photo is privacy-blurred "
            "except for the damaged area.")


def build_payload(report: dict) -> dict:
    """What the road authority will receive for this report (without credentials)."""
    info = service_info(report.get("jurisdiction")) or {}
    code = info.get("service_code", "POTHOLE") if report["class_code"] == "D40" else \
        info.get("crack_service_code", info.get("service_code", "ROAD_SURFACE"))
    attributes = {"severity": report["severity"], "confirmations": report["confirmations"],
                  "p1_candidate": bool(report.get("p1_candidate")), "source": "RoadSense"}
    if report.get("severity_band"):
        attributes["severity_band"] = report["severity_band"]
    if report.get("repair_target_days"):
        attributes["repair_target_days"] = report["repair_target_days"]
    return {"authority": info.get("authority", report.get("jurisdiction")), "channel": info.get("channel", "none"),
            "service_code": code, "lat": round(report["lat"], 6), "long": round(report["lon"], 6),
            "address_string": report.get("address") or "",
            "description": report.get("draft_description") or default_description(report),
            "media_url": media.signed_url(report["best_event_id"], report.get("created_at")),
            "attributes": attributes}


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def submit(payload: dict, report: dict | None = None) -> dict:
    from . import delivery  # late import: delivery imports this module

    return delivery.submit(payload, report)


def request_status(authority: str, service_request_id: str, channel: str | None = None) -> dict:
    from . import delivery

    return delivery.status(authority, service_request_id, channel)
