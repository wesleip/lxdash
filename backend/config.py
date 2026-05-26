from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
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


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (singleton for the process lifetime)."""
    return Settings()
