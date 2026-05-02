"""Tests for resolve_cli_log_level (SOOTHE_LOG_LEVEL vs cli_config logging_level)."""

import pytest

from soothe_sdk.utils.logging import resolve_cli_log_level


def test_env_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_LOG_LEVEL", "DEBUG")
    assert resolve_cli_log_level(logging_level="INFO") == "DEBUG"


def test_env_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_LOG_LEVEL", "info")
    assert resolve_cli_log_level() == "INFO"


def test_invalid_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_LOG_LEVEL", "not_a_level")
    assert resolve_cli_log_level() == "INFO"


def test_missing_env_defaults_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_LOG_LEVEL", raising=False)
    assert resolve_cli_log_level() == "INFO"


def test_logging_level_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_LOG_LEVEL", raising=False)
    assert resolve_cli_log_level(logging_level="DEBUG") == "DEBUG"


def test_env_still_wins_over_config_logging_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_LOG_LEVEL", "WARNING")
    assert resolve_cli_log_level(logging_level="DEBUG") == "WARNING"
