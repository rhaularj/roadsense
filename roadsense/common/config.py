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
    # a sighting near a report a human rejected is suppressed (not re-proposed) for this many days
    rejected_suppress_days: int = int(os.environ.get("ROADSENSE_REJECTED_SUPPRESS_DAYS", "90"))
    authorities_file: str = os.environ.get("ROADSENSE_AUTHORITIES_FILE", "")  # tenant directory; default: built-in

    # ---- evidence links and privacy ----
    # base URL the road authority uses to fetch evidence photos (must be reachable from the city's network)
    public_url: str = os.environ.get("ROADSENSE_PUBLIC_URL", "") or os.environ.get("ROADSENSE_AGENT_API_URL",
                                                                                     "http://127.0.0.1:8000")
    media_secret: str = os.environ.get("ROADSENSE_MEDIA_SECRET", "") or os.environ.get("ROADSENSE_API_TOKEN",
                                                                                        "dev-token-change-me")
    media_link_days: int = int(os.environ.get("ROADSENSE_MEDIA_LINK_DAYS", "120"))
    server_redaction: bool = os.environ.get("ROADSENSE_SERVER_REDACTION", "1") != "0"
    egoblur_weights: str = os.environ.get("ROADSENSE_EGOBLUR_WEIGHTS", "")  # optional TorchScript face/plate model
    keep_raw_video: bool = os.environ.get("ROADSENSE_KEEP_RAW_VIDEO", "0") == "1"
    raw_retention_hours: float = float(os.environ.get("ROADSENSE_RAW_RETENTION_HOURS", "0"))
    rejected_media_days: int = int(os.environ.get("ROADSENSE_REJECTED_MEDIA_DAYS", "30"))
    car_position_days: int = int(os.environ.get("ROADSENSE_CAR_POSITION_DAYS", "30"))
    # "ca": refuse LLM endpoints outside the allow-list and free (prompt-logging) models; "any": development
    data_residency: str = os.environ.get("ROADSENSE_DATA_RESIDENCY", "any").lower()
    residency_llm_hosts: list[str] = field(default_factory=lambda: _list("ROADSENSE_RESIDENCY_LLM_HOSTS", []))

    # ---- identity ----
    auth_enabled: bool = os.environ.get("ROADSENSE_AUTH", "1") != "0"
    session_secret: str = os.environ.get("ROADSENSE_SESSION_SECRET", "")
    session_hours: float = float(os.environ.get("ROADSENSE_SESSION_HOURS", "12"))
    admin_email: str = os.environ.get("ROADSENSE_ADMIN_EMAIL", "admin@roadsense.local")
    admin_password: str = os.environ.get("ROADSENSE_ADMIN_PASSWORD", "")
    cookie_secure: bool = os.environ.get("ROADSENSE_COOKIE_SECURE", "0") == "1"
    oidc_issuer: str = os.environ.get("ROADSENSE_OIDC_ISSUER", "")  # e.g. https://login.microsoftonline.com/<t>/v2.0
    oidc_client_id: str = os.environ.get("ROADSENSE_OIDC_CLIENT_ID", "")
    oidc_client_secret: str = os.environ.get("ROADSENSE_OIDC_CLIENT_SECRET", "")
    oidc_redirect_url: str = os.environ.get("ROADSENSE_OIDC_REDIRECT_URL", "http://127.0.0.1:7860/auth/oidc/callback")
    oidc_default_role: str = os.environ.get("ROADSENSE_OIDC_DEFAULT_ROLE", "viewer")

    # ---- delivery, scheduling and city systems ----
    max_delivery_attempts: int = int(os.environ.get("ROADSENSE_MAX_DELIVERY_ATTEMPTS", "6"))
    scheduler_enabled: bool = os.environ.get("ROADSENSE_SCHEDULER", "1") != "0"
    follow_up_minutes: float = float(os.environ.get("ROADSENSE_FOLLOW_UP_MINUTES", "60"))
    external_sync_minutes: float = float(os.environ.get("ROADSENSE_EXTERNAL_SYNC_MINUTES", "30"))
    # ArcGIS FeatureServer layer with the city's open service requests (HRM publishes Cityworks SRs on ArcGIS Hub)
    city_sr_layer_url: str = os.environ.get("ROADSENSE_CITY_SR_LAYER_URL", "")
    city_sr_where: str = os.environ.get("ROADSENSE_CITY_SR_WHERE", "1=1")
    cityworks_url: str = os.environ.get("ROADSENSE_CITYWORKS_URL", "")
    cityworks_user: str = os.environ.get("ROADSENSE_CITYWORKS_USER", "")
    cityworks_password: str = os.environ.get("ROADSENSE_CITYWORKS_PASSWORD", "")
    arcgis_layer_url: str = os.environ.get("ROADSENSE_ARCGIS_LAYER_URL", "")
    arcgis_token: str = os.environ.get("ROADSENSE_ARCGIS_TOKEN", "")
    smtp_host: str = os.environ.get("ROADSENSE_SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("ROADSENSE_SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("ROADSENSE_SMTP_USER", "")
    smtp_password: str = os.environ.get("ROADSENSE_SMTP_PASSWORD", "")
    smtp_from: str = os.environ.get("ROADSENSE_SMTP_FROM", "")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "roadsense.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def production_warnings(self) -> list[str]:
        """Settings that are fine on a laptop and wrong anywhere else (shown on the Trust & system page)."""
        out = []
        if self.api_token in ("dev-token-change-me", "") or len(self.api_token) < 24:
            out.append("ROADSENSE_API_TOKEN is the development default or shorter than 24 characters")
        if not self.auth_enabled:
            out.append("sign-in is disabled (ROADSENSE_AUTH=0)")
        if self.data_residency != "ca":
            out.append("data residency is not enforced (ROADSENSE_DATA_RESIDENCY is not 'ca')")
        if "127.0.0.1" in self.public_url or "localhost" in self.public_url:
            out.append("ROADSENSE_PUBLIC_URL points at this machine; road authorities cannot fetch evidence photos")
        if self.media_secret == self.api_token:
            out.append("ROADSENSE_MEDIA_SECRET is not set (evidence links are signed with the API token)")
        if "router.project-osrm.org" in self.osrm_url:
            out.append("road snapping uses the public OSRM demo server")
        if self.keep_raw_video:
            out.append("raw dashcam video is kept after processing (ROADSENSE_KEEP_RAW_VIDEO=1)")
        return out

    @property
    def llm_enabled(self) -> bool:
        return self.agents_enabled and self.use_llm and (bool(self.openrouter_api_key) or self.llm_mode == "replay")


settings = Settings()
