"""Unit tests for app.core.settings."""

from __future__ import annotations

import pytest

from app.core.settings import Settings, get_settings


def test_defaults_are_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.app_env == "dev"
    assert s.app_log_level == "INFO"
    assert s.service_name == "agripulse-api"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    get_settings.cache_clear()
    s = get_settings()
    assert s.app_env == "staging"
    assert s.app_log_level == "DEBUG"


def test_cors_csv_split() -> None:
    s = Settings(cors_allowed_origins="https://a.io,https://b.io")  # type: ignore[arg-type]
    assert s.cors_allowed_origins == ["https://a.io", "https://b.io"]


def test_cors_list_passthrough() -> None:
    s = Settings(cors_allowed_origins=["https://a.io"])
    assert s.cors_allowed_origins == ["https://a.io"]


def test_get_settings_is_singleton() -> None:
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
