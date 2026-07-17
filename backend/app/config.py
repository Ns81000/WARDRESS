"""Application settings, loaded from the environment (.env via Compose).

Secrets have no defaults on purpose (master prompt §9): a missing
JWT_SECRET or DATABASE_URL must fail loudly at startup, never fall back
to something guessable.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_url: str
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str
    # Fernet key material for credentials at rest (app/crypto.py). Any
    # sufficiently-random string; install.ps1 generates it. No default —
    # a missing key must fail loudly, never fall back to guessable.
    credentials_encryption_key: str

    @field_validator("credentials_encryption_key")
    @classmethod
    def encryption_key_strong_enough(cls, v: str) -> str:
        if len(v.encode("utf-8")) < 32:
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY must be at least 32 bytes")
        return v

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_strong_enough(cls, v: str) -> str:
        # RFC 7518 §3.2: HS256 keys must be >= 32 bytes. Fail at startup,
        # not at first login.
        if len(v.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET must be at least 32 bytes")
        return v

    # Token lifetimes (seconds). Access tokens are short-lived by design;
    # refresh tokens rotate on every use (see app/routers/auth.py).
    access_token_ttl: int = 15 * 60
    refresh_token_ttl: int = 7 * 24 * 60 * 60

    # Where scan artifacts (HTML snapshots, screenshots) live. The worker
    # writes here (rw); the app container mounts the same volume read-only
    # to serve screenshots to the dashboard.
    artifacts_dir: str = "/data/artifacts"

    # Set true when serving over HTTPS so the refresh cookie is
    # Secure-flagged. Defaults false for the localhost self-hosted case.
    cookie_secure: bool = False

    # --- Optional intelligence layer (§8). The DB settings rows (Settings
    # screen) are the source of truth; these env values act only as
    # bootstrap defaults for a fresh install that pre-set them in .env.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    enable_ollama: bool = False
    ollama_base_url: str = "http://ollama:11434/v1"

    # Shown in alert emails/messages as the dashboard link target; the
    # self-hosted default is the local port from install.ps1.
    public_base_url: str = "http://localhost:8321"


@lru_cache
def get_settings() -> Settings:
    return Settings()
