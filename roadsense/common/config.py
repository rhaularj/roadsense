"""Settings shared by every RoadSense process, read from the environment and an optional .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# Order from scripts/smoke_llm.py (2026-11-02): both Nemotron models returned correct tool calls; Gemma's free
# endpoint was rate-limited upstream on every attempt
DEFAULT_FREE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-31b-it:free",
]


def _path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    path = Path(value) if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


def _list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    return [v.strip() for v in value.split(",") if v.strip()] if value else list(default)


@dataclass(frozen=True)
class Settings:
    weights_dir: Path = field(default_factory=lambda: _path("ROADSENSE_WEIGHTS_DIR", Path("weights")))
    edge_weights: str = os.environ.get("ROADSENSE_EDGE_WEIGHTS", "yolov8m_rdd2022.pt")
    verify_weights: str = os.environ.get("ROADSENSE_VERIFY_WEIGHTS", "rtdetr_l_rdd2022.pt")
    device: str | None = os.environ.get("ROADSENSE_DEVICE") or None
    data_dir: Path = field(default_factory=lambda: _path("ROADSENSE_DATA_DIR", Path("data")))

    agent_api_url: str = os.environ.get("ROADSENSE_AGENT_API_URL", "http://127.0.0.1:8000")
    api_token: str = os.environ.get("ROADSENSE_API_TOKEN", "dev-token-change-me")
    open311_url: str = os.environ.get("ROADSENSE_OPEN311_URL", "http://127.0.0.1:8311")
    open311_api_key: str = os.environ.get("ROADSENSE_OPEN311_API_KEY", "dev-open311-key")

    openrouter_api_key: str = os.environ.get("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    llm_models: list[str] = field(default_factory=lambda: _list("ROADSENSE_LLM_MODELS", DEFAULT_FREE_MODELS))
    use_llm: bool = os.environ.get("ROADSENSE_USE_LLM", "1") != "0"
    llm_mode: str = os.environ.get("ROADSENSE_LLM_MODE", "cache")   # live | cache | replay (keyless demo)
    llm_rpm: int = int(os.environ.get("ROADSENSE_LLM_RPM", "15"))   # free tier allows 20 requests/minute
    agents_enabled: bool = os.environ.get("ROADSENSE_AGENTS_ENABLED", "1") != "0"  # kill switch

    nominatim_url: str = os.environ.get("ROADSENSE_NOMINATIM_URL", "https://nominatim.openstreetmap.org")
    # road snapping (OSRM "nearest"); the public demo server is for development only, run your own in production
    osrm_url: str = os.environ.get("ROADSENSE_OSRM_URL", "https://router.project-osrm.org")
    max_snap_m: float = float(os.environ.get("ROADSENSE_MAX_SNAP_M", "25"))
    nominatim_user_agent: str = os.environ.get("ROADSENSE_USER_AGENT", "RoadSense-MVP/0.1 (student hackathon project)")
    offline_geo: bool = os.environ.get("ROADSENSE_OFFLINE_GEO", "0") == "1"
    dedupe_radius_m: float = float(os.environ.get("ROADSENSE_DEDUPE_RADIUS_M", "15"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "roadsense.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def llm_enabled(self) -> bool:
        return self.agents_enabled and self.use_llm and (bool(self.openrouter_api_key) or self.llm_mode == "replay")


settings = Settings()
