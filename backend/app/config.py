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
    demo_mode: bool
    ai_triage_url: str | None
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
    ingest_token: str | None
    mock_gateway_secret: str | None
    app_env: str
    git_sha: str
    payment_gateway: str
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    email_from: str
    frontend_url: str
    invitation_token_hours: int
    password_reset_token_minutes: int
    google_client_id: str | None
    google_client_secret: str | None

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise ConfigError(f"{name.upper()} is not configured")
        return value

@lru_cache
def get_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL")
    demo_mode = os.getenv("DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    return Settings(
        database_url=database_url,
        jwt_secret=os.getenv("JWT_SECRET") or (
            "drch_demo_only_jwt_secret_change_before_deployment_32chars"
            if demo_mode and not database_url
            else None
        ),
        mfa_encryption_key=os.getenv("MFA_ENCRYPTION_KEY"),
        demo_mode=demo_mode,
        ai_triage_url=os.getenv("AI_TRIAGE_URL") or None,
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
        geojson_gujarat_districts_url=os.getenv(
            "GEOJSON_GUJARAT_DISTRICTS_URL",
            "https://raw.githubusercontent.com/datameet/maps/master/Districts/Gujarat.geojson",
        ),
        ingest_token=os.getenv("INGEST_TOKEN"),
        mock_gateway_secret=os.getenv("MOCK_GATEWAY_SECRET"),
        app_env=os.getenv("APP_ENV", "development").lower(),
        git_sha=os.getenv("GIT_SHA", "dev"),
        payment_gateway=os.getenv("PAYMENT_GATEWAY", "mock").lower(),
        smtp_host=os.getenv("SMTP_HOST") or None,
        smtp_port=_int("SMTP_PORT", 587),
        smtp_username=os.getenv("SMTP_USERNAME") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        email_from=os.getenv("EMAIL_FROM", "no-reply@drch.gujarat.gov.in"),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/"),
        invitation_token_hours=_int("INVITATION_TOKEN_HOURS", 48),
        password_reset_token_minutes=_int("PASSWORD_RESET_TOKEN_MINUTES", 15),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID") or None,
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET") or None,
    )
