from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = "sqlite:///./lxdash.db"

    # ------------------------------------------------------------------ #
    # JWT / Auth                                                           #
    # ------------------------------------------------------------------ #
    SECRET_KEY: str = "changeme"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ------------------------------------------------------------------ #
    # LXD                                                                  #
    # ------------------------------------------------------------------ #
    LXD_SOCKET_PATH: str = "/var/snap/lxd/common/lxd/unix.socket"

    # ------------------------------------------------------------------ #
    # CORS                                                                 #
    # ------------------------------------------------------------------ #
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors(cls, v: object) -> object:
        # Accept both "url1,url2" (CSV from .env) and ["url1","url2"] (JSON array)
        if isinstance(v, str) and not v.startswith("["):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # ------------------------------------------------------------------ #
    # Application                                                          #
    # ------------------------------------------------------------------ #
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    LXD_MOCK: bool = False  # set to true to use in-memory fake LXD client
    # Expose interactive API docs (/docs, /redoc, /openapi.json).
    # PRODUCTION.md \xA76 suggests restricting them in production. Defaults to
    # True so a single-host local deployment keeps convenience; set to false
    # when the instance is reachable from an untrusted network.
    DOCS_ENABLED: bool = True

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """Refuse to start with unsafe defaults when APP_ENV=production.

        Defence in depth: even if the operator forgets to set the env vars
        on first deploy, the process fails fast with a clear error instead
        of booting with a guessable SECRET_KEY or the in-memory LXD mock.
        """
        if self.APP_ENV != "production":
            return self

        if self.SECRET_KEY == "changeme" or len(self.SECRET_KEY) < 32:
            raise ValueError(
                "SECRET_KEY must be set to a strong value (>= 32 chars) when "
                "APP_ENV=production. Generate one with: openssl rand -hex 32"
            )

        if self.LXD_MOCK:
            raise ValueError(
                "LXD_MOCK=true is not allowed when APP_ENV=production. "
                "The mock client serves in-memory fake data; set "
                "LXD_MOCK=false and configure LXD_SOCKET_PATH to reach the "
                "real LXD daemon."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (singleton for the process lifetime)."""
    return Settings()
