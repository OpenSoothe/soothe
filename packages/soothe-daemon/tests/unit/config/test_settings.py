"""Tests for daemon config path defaults."""

from __future__ import annotations

from pathlib import Path

from soothe_daemon.config.settings import (
    SootheDaemonConfig,
    default_daemon_config_path,
    default_soothe_config_path,
)


def test_default_paths_create_config_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("soothe_daemon.config.settings.SOOTHE_HOME", tmp_path)
    config_dir = tmp_path / "config"
    assert not config_dir.exists()

    daemon_path = default_daemon_config_path()
    soothe_path = default_soothe_config_path()

    assert config_dir.is_dir()
    assert daemon_path == config_dir / "daemon.yml"
    assert soothe_path == config_dir / "nano.yml"


def test_from_default_yaml_creates_config_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("soothe_daemon.config.settings.SOOTHE_HOME", tmp_path)
    config_dir = tmp_path / "config"
    assert not config_dir.exists()

    cfg = SootheDaemonConfig.from_default_yaml()

    assert isinstance(cfg, SootheDaemonConfig)
    assert config_dir.is_dir()
