"""Tests for resolve_cli_log_level (SOOTHE_LOG_LEVEL vs verbosity)."""

import pytest

from soothe_sdk.utils.logging import VERBOSITY_TO_LOG_LEVEL, resolve_cli_log_level


def test_env_overrides_verbosity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_LOG_LEVEL", "DEBUG")
    assert resolve_cli_log_level("normal") == "DEBUG"


def test_env_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_LOG_LEVEL", "info")
    assert resolve_cli_log_level("normal") == "INFO"


def test_invalid_env_falls_back_to_verbosity_map(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_LOG_LEVEL", "not_a_level")
    assert resolve_cli_log_level("minimal") == VERBOSITY_TO_LOG_LEVEL["minimal"]


def test_missing_env_uses_verbosity_map(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_LOG_LEVEL", raising=False)
    assert resolve_cli_log_level("debug") == "DEBUG"


def test_logging_level_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_LOG_LEVEL", raising=False)
    assert resolve_cli_log_level("normal", logging_level="DEBUG") == "DEBUG"


def test_env_still_wins_over_config_logging_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_LOG_LEVEL", "WARNING")
    assert resolve_cli_log_level("debug", logging_level="DEBUG") == "WARNING"
