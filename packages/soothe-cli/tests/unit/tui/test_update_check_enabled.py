"""Tests for startup update-check gating."""

from __future__ import annotations

import pytest

from soothe_cli.tui import update_check
from soothe_cli.tui._env_vars import AUTO_UPDATE, NO_UPDATE_CHECK, UPDATE_CHECK


@pytest.mark.parametrize("env_name", ("SOOTHE_NO_UPDATE_CHECK", NO_UPDATE_CHECK))
def test_is_update_check_enabled_respects_disable_env(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    monkeypatch.setenv(env_name, "1")
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {"check": True})
    assert update_check.is_update_check_enabled() is False


def test_is_update_check_enabled_defaults_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv(NO_UPDATE_CHECK, raising=False)
    monkeypatch.delenv(UPDATE_CHECK, raising=False)
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {})
    assert update_check.is_update_check_enabled() is True


def test_is_update_check_enabled_config_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv(NO_UPDATE_CHECK, raising=False)
    monkeypatch.delenv(UPDATE_CHECK, raising=False)
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {"check": False})
    assert update_check.is_update_check_enabled() is False


def test_is_update_check_enabled_config_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv(NO_UPDATE_CHECK, raising=False)
    monkeypatch.delenv(UPDATE_CHECK, raising=False)
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {"check": True})
    assert update_check.is_update_check_enabled() is True


@pytest.mark.parametrize("truthy", ("1", "true", "yes"))
def test_is_update_check_enabled_enable_env(monkeypatch: pytest.MonkeyPatch, truthy: str) -> None:
    monkeypatch.delenv("SOOTHE_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv(NO_UPDATE_CHECK, raising=False)
    monkeypatch.setenv(UPDATE_CHECK, truthy)
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {})
    assert update_check.is_update_check_enabled() is True


def test_disable_env_overrides_enable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NO_UPDATE_CHECK, "1")
    monkeypatch.setenv(UPDATE_CHECK, "true")
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {"check": True})
    assert update_check.is_update_check_enabled() is False


def test_is_auto_update_enabled_defaults_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("soothe_cli.tui.config._is_editable_install", lambda: False)
    monkeypatch.delenv(AUTO_UPDATE, raising=False)
    monkeypatch.delenv("SOOTHE_AUTO_UPDATE", raising=False)
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {})
    assert update_check.is_auto_update_enabled() is True


def test_is_auto_update_enabled_editable_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("soothe_cli.tui.config._is_editable_install", lambda: True)
    monkeypatch.setenv(AUTO_UPDATE, "1")
    assert update_check.is_auto_update_enabled() is False


def test_is_auto_update_enabled_config_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("soothe_cli.tui.config._is_editable_install", lambda: False)
    monkeypatch.delenv(AUTO_UPDATE, raising=False)
    monkeypatch.delenv("SOOTHE_AUTO_UPDATE", raising=False)
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {"auto_update": False})
    assert update_check.is_auto_update_enabled() is False


def test_is_auto_update_enabled_env_overrides_config_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("soothe_cli.tui.config._is_editable_install", lambda: False)
    monkeypatch.setenv(AUTO_UPDATE, "1")
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {"auto_update": False})
    assert update_check.is_auto_update_enabled() is True


def test_is_auto_update_enabled_env_false_overrides_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("soothe_cli.tui.config._is_editable_install", lambda: False)
    monkeypatch.setenv(AUTO_UPDATE, "0")
    monkeypatch.setattr(update_check, "_read_update_config", lambda: {"auto_update": True})
    assert update_check.is_auto_update_enabled() is False
