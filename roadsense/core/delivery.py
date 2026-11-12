"""Delivery adapters: how an approved payload reaches a road authority's system.

    open311    Open311 GeoReport v2 (POST /requests.json); status by GET /requests/{id}.json
    cityworks  Cityworks REST API: ServiceRequest/Create, ServiceRequest/ById, RequestComment/Add
    arcgis     ArcGIS Feature Service: addFeatures (+ addAttachment with the evidence photo), query, updateFeatures
    referral   a referral package on disk, also emailed when SMTP is configured (authorities without an API)

Each adapter implements submit / status / update. The authority's directory entry picks the adapter ("channel").
Credentials come from settings, never from the payload, so the approved payload and its hash contain none.

The Cityworks and ArcGIS adapters follow the vendors' public API shapes. Field names (ProblemSid, attribute names)
differ per installation and are set in the directory entry; validate them against the city's test instance before
switching a pilot to them.
"""
from __future__ import annotations

import json
import smtplib
import time
from email.message import EmailMessage

import httpx

from ..common.config import settings
from . import open311

TIMEOUT = 20


class DeliveryError(RuntimeError):
    """Delivery failed; the report stays approved and the scheduler retries with backoff."""


def _info(authority: str | None) -> dict:
    info = open311.service_info(authority)
    if info is None:
        raise DeliveryError(f"no delivery channel for {authority!r}")
    return info


# ---------------- Open311 GeoReport v2 ----------------
def _open311_submit(payload: dict, info: dict, report: dict | None) -> dict:
    data = {"api_key": settings.open311_api_key, **{k: payload[k] for k in
            ("service_code", "lat", "long", "description", "address_string", "media_url")}}
    for k, v in payload["attributes"].items():
        data[f"attribute[{k}]"] = str(v)
    r = httpx.post(f"{info['open311_url']}/requests.json", data=data, timeout=TIMEOUT)
    r.raise_for_status()
    ack = r.json()[0]
    return {"channel": "open311", "service_request_id": ack["service_request_id"], "notice": ack.get("service_notice")}


def _open311_status(info: dict, sr_id: str) -> dict:
    r = httpx.get(f"{info['open311_url']}/requests/{sr_id}.json", timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()[0]
    return {"status": d.get("status"), "status_notes": d.get("status_notes")}


def _open311_update(info: dict, sr_id: str, message: str) -> dict:
    # GeoReport v2 has no update call: the new information stays in RoadSense and the audit log
    return {"ok": False, "unsupported": True, "detail": "Open311 GeoReport v2 cannot update a request"}


# ---------------- Cityworks REST ----------------
_cw_token: dict = {}


def _cw_call(service: str, data: dict) -> dict:
    base = settings.cityworks_url.rstrip("/")
    if not base:
        raise DeliveryError("ROADSENSE_CITYWORKS_URL is not set")
    if not _cw_token or _cw_token.get("exp", 0) < time.time():
        r = httpx.post(f"{base}/Services/General/Authentication/Authenticate", timeout=TIMEOUT,
                       data={"data": json.dumps({"LoginName": settings.cityworks_user,
                                                 "Password": settings.cityworks_password})})
        r.raise_for_status()
        body = r.json()
        token = (body.get("Value") or {}).get("Token")
        if body.get("Status") not in (0, None) or not token:
            raise DeliveryError(f"Cityworks authentication failed: {body.get('Message')}")
        _cw_token.update(token=token, exp=time.time() + 50 * 60)
    r = httpx.post(f"{base}/Services/{service}", timeout=TIMEOUT,
                   data={"data": json.dumps(data), "token": _cw_token["token"]})
    r.raise_for_status()
    body = r.json()
    if body.get("Status") not in (0, None):
        if body.get("Status") == 2:  # unauthorized: token expired early
            _cw_token.clear()
        raise DeliveryError(f"Cityworks {service} failed: {body.get('Message')}")
    return body.get("Value") or {}


def _cityworks_submit(payload: dict, info: dict, report: dict | None) -> dict:
    value = _cw_call("Ams/ServiceRequest/Create", {
        "ProblemSid": info.get("cityworks_problem_sid", 0), "RequestType": info.get("cityworks_request_type"),
        "X": payload["long"], "Y": payload["lat"], "Address": payload["address_string"],
        "Details": payload["description"], "Comments": f"Evidence photo: {payload['media_url']}",
        "SubmitTo": info.get("cityworks_submit_to"), "Priority": "1" if payload["attributes"].get("p1_candidate")
        else None, "Text1": json.dumps(payload["attributes"])[:255]})
    sr_id = str(value.get("RequestId") or value.get("Id") or "")
    if not sr_id:
        raise DeliveryError("Cityworks did not return a RequestId")
    return {"channel": "cityworks", "service_request_id": sr_id, "notice": f"Cityworks service request {sr_id}"}


def _cityworks_status(info: dict, sr_id: str) -> dict:
    value = _cw_call("Ams/ServiceRequest/ById", {"RequestId": int(sr_id)})
    raw = str(value.get("Status") or "").upper()
    return {"status": "closed" if raw in ("CLOSED", "CLOSE", "COMPLETE", "COMPLETED", "CANCEL") else "open",
            "status_notes": value.get("Status")}


def _cityworks_update(info: dict, sr_id: str, message: str) -> dict:
    _cw_call("Ams/RequestComment/Add", {"RequestId": int(sr_id), "Comments": message[:2000]})
    return {"ok": True}


# ---------------- ArcGIS Feature Service ----------------
def _ag(path: str, data: dict, files=None) -> dict:
    base = settings.arcgis_layer_url.rstrip("/")
    if not base:
        raise DeliveryError("ROADSENSE_ARCGIS_LAYER_URL is not set")
    data = {"f": "json", **data, **({"token": settings.arcgis_token} if settings.arcgis_token else {})}
    r = httpx.post(f"{base}/{path}", data=data, files=files, timeout=TIMEOUT)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise DeliveryError(f"ArcGIS {path} failed: {body['error'].get('message')}")
    return body


def _arcgis_submit(payload: dict, info: dict, report: dict | None) -> dict:
    fields = info.get("arcgis_fields", {})
    attrs = {fields.get("description", "description"): payload["description"],
             fields.get("address", "address"): payload["address_string"],
             fields.get("service_code", "request_type"): payload["service_code"],
             fields.get("status", "status"): "open",
             fields.get("media_url", "media_url"): payload["media_url"],
             fields.get("severity", "severity"): payload["attributes"].get("severity"),
             fields.get("confirmations", "confirmations"): payload["attributes"].get("confirmations"),
             fields.get("source", "source"): "RoadSense"}
    feature = {"geometry": {"x": payload["long"], "y": payload["lat"], "spatialReference": {"wkid": 4326}},
               "attributes": attrs}
    body = _ag("addFeatures", {"features": json.dumps([feature])})
    res = (body.get("addResults") or [{}])[0]
    if not res.get("success"):
        raise DeliveryError(f"ArcGIS addFeatures failed: {res.get('error')}")
    oid = str(res["objectId"])
    if report and report.get("best_event_id"):
        path = settings.media_dir / f"{report['best_event_id']}.jpg"
        if path.is_file():
            _ag(f"{oid}/addAttachment", {}, files={"attachment": (path.name, path.read_bytes(), "image/jpeg")})
    return {"channel": "arcgis", "service_request_id": oid, "notice": f"ArcGIS feature {oid}"}


def _arcgis_status(info: dict, sr_id: str) -> dict:
    status_field = info.get("arcgis_fields", {}).get("status", "status")
    body = _ag("query", {"objectIds": sr_id, "outFields": status_field, "returnGeometry": "false"})
    feats = body.get("features") or []
    raw = str((feats[0]["attributes"].get(status_field) if feats else "") or "")
    return {"status": "closed" if raw.lower() in ("closed", "complete", "completed", "fixed") else "open",
            "status_notes": raw or None}


def _arcgis_update(info: dict, sr_id: str, message: str, report: dict | None = None) -> dict:
    fields = info.get("arcgis_fields", {})
    attrs = {"OBJECTID": int(sr_id), fields.get("notes", "notes"): message[:2000]}
    if report:
        attrs[fields.get("confirmations", "confirmations")] = report["confirmations"]
    _ag("updateFeatures", {"features": json.dumps([{"attributes": attrs}])})
    return {"ok": True}


# ---------------- referral package (+ email) ----------------
def _referral_submit(payload: dict, info: dict, report: dict | None) -> dict:
    folder = settings.data_dir / "referrals"
    folder.mkdir(parents=True, exist_ok=True)
    ref_id = f"REF-{open311.payload_hash(payload)[:10]}"
    package = {"to": info["authority"], "contact": info.get("contact"), **payload}
    (folder / f"{ref_id}.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
    emailed = False
    if settings.smtp_host and info.get("referral_email"):
        msg = EmailMessage()
        msg["Subject"] = f"RoadSense referral {ref_id}: {payload['service_code']} at {payload['address_string']}"
        msg["From"] = settings.smtp_from or settings.smtp_user
        msg["To"] = info["referral_email"]
        msg.set_content(f"{payload['description']}\n\nLocation: {payload['lat']}, {payload['long']}\n"
                        f"Evidence photo: {payload['media_url']}\nReference: {ref_id}\n\n{json.dumps(payload, indent=2)}")
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT) as s:
                s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            raise DeliveryError(f"referral email failed: {e}") from e
        emailed = True
    how = f"emailed to {info['referral_email']}" if emailed else "prepared (send it to " + str(info.get("contact")) + ")"
    return {"channel": "referral", "service_request_id": ref_id,
            "notice": f"Referral package {how} for {info['authority']}."}


ADAPTERS = {
    "open311": (_open311_submit, _open311_status, _open311_update),
    "cityworks": (_cityworks_submit, _cityworks_status, _cityworks_update),
    "arcgis": (_arcgis_submit, _arcgis_status, _arcgis_update),
    "referral": (_referral_submit, None, None),
}


def submit(payload: dict, report: dict | None = None) -> dict:
    info = _info(payload["authority"])
    channel = info.get("channel")
    if channel not in ADAPTERS:
        raise DeliveryError(f"unknown channel {channel!r} for {info['authority']}")
    try:
        return ADAPTERS[channel][0](payload, info, report)
    except httpx.HTTPError as e:
        raise DeliveryError(f"{channel} delivery failed: {e}") from e


def status(authority: str, sr_id: str, channel: str | None = None) -> dict:
    info = _info(authority)
    fn = ADAPTERS.get(channel or info.get("channel"), (None, None, None))[1]
    if fn is None:
        return {"status": "unknown", "status_notes": "this channel has no status feed"}
    try:
        return fn(info, sr_id)
    except httpx.HTTPError as e:
        raise DeliveryError(f"status check failed: {e}") from e


def update(authority: str, sr_id: str, channel: str | None, message: str, report: dict | None = None) -> dict:
    """Push new information (more confirmations, higher severity) to a request already filed."""
    info = _info(authority)
    ch = channel or info.get("channel")
    fn = ADAPTERS.get(ch, (None, None, None))[2]
    if fn is None:
        return {"ok": False, "unsupported": True, "detail": f"{ch} has no update call"}
    try:
        return fn(info, sr_id, message, report) if ch == "arcgis" else fn(info, sr_id, message)
    except httpx.HTTPError as e:
        raise DeliveryError(f"update failed: {e}") from e


def backoff_seconds(attempt: int) -> int:
    """1, 5, 15, 60, 180 ... minutes between delivery attempts."""
    return [60, 300, 900, 3600, 10800, 21600][min(attempt - 1, 5)]
