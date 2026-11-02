"""Runtime settings read from environment variables.

Settings are resolved lazily so that importing the app (CI smoke test) does
not require a database or secrets. Anything that needs a missing value fails
with a clear message at the point of use.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Local development: pick up the repository-level .env without overriding
# variables already provided by Docker or the host.
_REPO_ENV = Path(__file__).resolve().parents[2] / ".env"
if _REPO_ENV.is_file():
    load_dotenv(_REPO_ENV, override=False)


class ConfigError(RuntimeError):
    pass

def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default

def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")

@dataclass(frozen=True)
class Settings:
    database_url: str | None
    jwt_secret: str | None
    mfa_encryption_key: str | None
    ai_triage_url: str | None
    ai_triage_token: str | None
    access_token_minutes: int
    mfa_token_minutes: int
    login_max_attempts: int
    lockout_minutes: int
    dispatch_ack_timeout_minutes: int
    ai_low_confidence_threshold: float
    google_maps_api_key: str | None
    boundary_sync_enabled: bool
    boundary_sync_interval_hours: int
    boundary_sync_check_interval_seconds: int
    geojson_gujarat_districts_url: str
    cors_allowed_origins: list[str]
    ingest_token: str | None
    mock_gateway_secret: str | None
    app_env: str
    git_sha: str
    payment_gateway: str
    sachet_feed_url: str = ""

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise ConfigError(f"{name.upper()} is not configured")
        return value

@lru_cache
def get_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL")
    app_env = os.getenv("APP_ENV", "development").lower()
    cors_default = "http://localhost:3000,http://127.0.0.1:3000" if app_env == "development" else ""
    return Settings(
        database_url=database_url,
        jwt_secret=os.getenv("JWT_SECRET") or None,
        mfa_encryption_key=os.getenv("MFA_ENCRYPTION_KEY"),
        ai_triage_url=os.getenv("AI_TRIAGE_URL") or None,
        ai_triage_token=os.getenv("AI_TRIAGE_TOKEN") or None,
        access_token_minutes=_int("ACCESS_TOKEN_MINUTES", 60),
        mfa_token_minutes=_int("MFA_TOKEN_MINUTES", 5),
        login_max_attempts=_int("LOGIN_MAX_ATTEMPTS", 5),
        lockout_minutes=_int("LOGIN_LOCKOUT_MINUTES", 15),
        dispatch_ack_timeout_minutes=_int("DISPATCH_ACK_TIMEOUT_MINUTES", 15),
        ai_low_confidence_threshold=float(os.getenv("AI_LOW_CONFIDENCE_THRESHOLD", "0.6")),
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_GEOCODING_API_KEY"),
        boundary_sync_enabled=_bool("BOUNDARY_SYNC_ENABLED", True),
        boundary_sync_interval_hours=_int("BOUNDARY_SYNC_INTERVAL_HOURS", 720),  # Monthly (30 days = 720h)
        boundary_sync_check_interval_seconds=_int("BOUNDARY_SYNC_CHECK_INTERVAL_SECONDS", 86400),
        # Empty = boundary sync disabled; the packaged polygon + PostGIS data are used instead.
        geojson_gujarat_districts_url=os.getenv("GEOJSON_GUJARAT_DISTRICTS_URL", "").strip(),
        cors_allowed_origins=[
            o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", cors_default).split(",") if o.strip()
        ],
        ingest_token=os.getenv("INGEST_TOKEN"),
        mock_gateway_secret=os.getenv("MOCK_GATEWAY_SECRET"),
        app_env=app_env,
        git_sha=os.getenv("GIT_SHA", "dev"),
        payment_gateway=os.getenv("PAYMENT_GATEWAY", "mock").lower(),
        sachet_feed_url=os.getenv("SACHET_FEED_URL", "").strip(),
    )


_PLACEHOLDER_MARKERS = ("change", "insecure", "supersecret", "demo_only", "placeholder", "example", "test-only")


def validate_for_environment(settings: Settings) -> list[str]:
    """Return configuration problems that must stop startup outside development."""
    if settings.app_env == "development":
        return []
    problems = []
    for name in ("database_url", "jwt_secret", "mfa_encryption_key", "ingest_token"):
        if not getattr(settings, name):
            problems.append(f"{name.upper()} is required when APP_ENV={settings.app_env}")
    secret = settings.jwt_secret or ""
    if secret and (len(secret) < 32 or any(m in secret.lower() for m in _PLACEHOLDER_MARKERS)):
        problems.append("JWT_SECRET is too short or looks like a placeholder")
    if not settings.cors_allowed_origins:
        problems.append("CORS_ALLOWED_ORIGINS is required (comma-separated list of frontend origins)")
    return problems
