"""Road-authority directory, the exact payload a report becomes, and the channels that deliver it.

The payload is built deterministically from the database, so the driver approves exactly what will be sent: the
approval stores its hash, and submission refuses if the payload changed after approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from ..common.config import settings

DIRECTORY = Path(__file__).with_name("municipalities.json")


def directory() -> dict:
    text = DIRECTORY.read_text(encoding="utf-8").replace("${ROADSENSE_OPEN311_URL}", settings.open311_url)
    return json.loads(text)


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
    return {"authority": info.get("authority", report.get("jurisdiction")), "channel": info.get("channel", "none"),
            "service_code": code, "lat": round(report["lat"], 6), "long": round(report["lon"], 6),
            "address_string": report.get("address") or "",
            "description": report.get("draft_description") or default_description(report),
            "media_url": f"{settings.agent_api_url}/media/{report['best_event_id']}.jpg",
            "attributes": {"severity": report["severity"], "confirmations": report["confirmations"],
                           "p1_candidate": bool(report.get("p1_candidate")), "source": "RoadSense"}}


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def submit(payload: dict) -> dict:
    """Deliver an approved payload. Open311 authorities get a GeoReport v2 request; the others a referral package."""
    info = service_info(payload["authority"])
    if info is None:
        raise ValueError(f"no delivery channel for {payload['authority']!r}")
    if info["channel"] == "open311":
        data = {"api_key": settings.open311_api_key, **{k: payload[k] for k in
                ("service_code", "lat", "long", "description", "address_string", "media_url")}}
        for k, v in payload["attributes"].items():
            data[f"attribute[{k}]"] = str(v)
        r = httpx.post(f"{info['open311_url']}/requests.json", data=data, timeout=15)
        r.raise_for_status()
        ack = r.json()[0]
        return {"channel": "open311", "service_request_id": ack["service_request_id"],
                "notice": ack.get("service_notice")}
    folder = settings.data_dir / "referrals"
    folder.mkdir(parents=True, exist_ok=True)
    ref_id = f"REF-{payload_hash(payload)[:10]}"
    (folder / f"{ref_id}.json").write_text(json.dumps({"to": info["authority"], "contact": info.get("contact"),
                                                       **payload}, indent=2), encoding="utf-8")
    return {"channel": "referral", "service_request_id": ref_id,
            "notice": f"Referral package prepared for {info['authority']} ({info.get('contact')})."}


def request_status(authority: str, service_request_id: str) -> dict:
    info = service_info(authority)
    if not info or info["channel"] != "open311":
        return {"status": "unknown", "status_notes": "referral channel has no status feed"}
    r = httpx.get(f"{info['open311_url']}/requests/{service_request_id}.json", timeout=15)
    r.raise_for_status()
    return r.json()[0]
