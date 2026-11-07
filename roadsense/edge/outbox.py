"""Store-and-forward upload of edge events: anything not yet accepted by the agent API stays queued on disk."""
from __future__ import annotations

import shutil
from pathlib import Path

import httpx

from ..common.config import settings


def pending(trip_dir: Path) -> list[Path]:
    return sorted(p for p in trip_dir.glob("*.json") if p.name != "trip.json" and p.with_suffix(".jpg").is_file())


def upload(trip_dir: Path, api_url: str | None = None, token: str | None = None, timeout: float = 30.0) -> dict:
    """POST each queued event (metadata + redacted frame) to the agent API; move accepted ones to sent/."""
    api_url, token = api_url or settings.agent_api_url, token or settings.api_token
    sent_dir = trip_dir / "sent"
    sent_dir.mkdir(exist_ok=True)
    accepted, failed = 0, []
    with httpx.Client(base_url=api_url, timeout=timeout, headers={"Authorization": f"Bearer {token}"}) as client:
        for meta in pending(trip_dir):
            image = meta.with_suffix(".jpg")
            try:
                with open(image, "rb") as f:
                    r = client.post("/events", data={"event": meta.read_text(encoding="utf-8")},
                                    files={"image": (image.name, f, "image/jpeg")})
                r.raise_for_status()
            except httpx.HTTPError as e:
                failed.append({"event": meta.stem, "error": str(e)})
                continue
            shutil.move(str(meta), sent_dir / meta.name)
            shutil.move(str(image), sent_dir / image.name)
            accepted += 1
    return {"accepted": accepted, "failed": failed, "still_queued": len(pending(trip_dir))}
