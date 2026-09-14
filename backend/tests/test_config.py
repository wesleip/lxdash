"""Tests for backend.config.Settings validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def _make(**overrides):
    """Build Settings without going through the lru_cache singleton."""
    from config import Settings

    # defaults match conftest: APP_ENV=development, SECRET_KEY=x*48, LXD_MOCK=true
    return Settings(**overrides)


def test_development_accepts_default_secret():
    s = _make()
    assert s.APP_ENV == "development"
    assert s.SECRET_KEY  # populated


def test_cors_csv_string_parses_to_list():
    s = _make(CORS_ORIGINS="https://a.example, https://b.example")
    assert s.CORS_ORIGINS == ["https://a.example", "https://b.example"]


def test_cors_json_string_parses_to_list():
    s = _make(CORS_ORIGINS='["https://a.example", "https://b.example"]')
    assert s.CORS_ORIGINS == ["https://a.example", "https://b.example"]


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError) as exc:
        _make(APP_ENV="production", SECRET_KEY="changeme")
    assert "SECRET_KEY" in str(exc.value)


def test_production_rejects_short_secret():
    with pytest.raises(ValidationError) as exc:
        _make(APP_ENV="production", SECRET_KEY="tooshort")
    assert "SECRET_KEY" in str(exc.value)


def test_production_rejects_mock_lxd():
    with pytest.raises(ValidationError) as exc:
        _make(APP_ENV="production", SECRET_KEY="x" * 32, LXD_MOCK=True)
    assert "LXD_MOCK" in str(exc.value)


def test_production_accepts_strong_secret_and_real_lxd():
    s = _make(APP_ENV="production", SECRET_KEY="x" * 32, LXD_MOCK=False)
    assert s.APP_ENV == "production"
    assert s.LXD_MOCK is False
