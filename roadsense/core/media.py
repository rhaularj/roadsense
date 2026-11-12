"""Signed, expiring evidence links.

A road authority's system fetches the evidence photo from RoadSense without an account, so the link itself carries
the permission: an HMAC over the event id and an expiry. The expiry is derived from the report's creation time, not
from "now", so the payload a reviewer approves (and its hash) is the same whenever it is rebuilt.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta

from ..common.config import settings


def _sig(event_id: str, exp: int) -> str:
    return hmac.new(settings.media_secret.encode(), f"{event_id}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def expiry_for(created_at: str | None) -> int:
    try:
        base = datetime.fromisoformat(created_at) if created_at else None
    except ValueError:
        base = None
    if base is None:
        return int(time.time()) + settings.media_link_days * 86400
    return int((base + timedelta(days=settings.media_link_days)).timestamp())


def signed_path(event_id: str, exp: int) -> str:
    return f"/media/{event_id}.jpg?exp={exp}&sig={_sig(event_id, exp)}"


def signed_url(event_id: str, created_at: str | None) -> str:
    return settings.public_url.rstrip("/") + signed_path(event_id, expiry_for(created_at))


def verify(event_id: str, exp: int | None, sig: str | None) -> bool:
    if exp is None or not sig or exp < time.time():
        return False
    return hmac.compare_digest(_sig(event_id, exp), sig)
