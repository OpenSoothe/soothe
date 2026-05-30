"""Tests for CLI config loading from global flags."""

from __future__ import annotations

from pathlib import Path

from soothe_cli.config.cli_config import CLIConfig
from soothe_cli.config.loader import load_config, reset_runtime_config, set_runtime_config


def test_load_config_returns_defaults_when_no_runtime_config() -> None:
    reset_runtime_config()
    cfg = load_config()
    assert cfg.daemon_host == "127.0.0.1"
    assert cfg.daemon_port == 8765
    assert cfg.logging_level is None
    assert cfg.render_markdown is True


def test_load_config_returns_runtime_config() -> None:
    reset_runtime_config()
    expected = CLIConfig(
        daemon_host="10.0.0.5",
        daemon_port=9999,
        logging_level="DEBUG",
        render_markdown=False,
        soothe_home=Path("/tmp/soothe-test"),
    )
    set_runtime_config(expected)
    assert load_config() is expected


def test_global_cli_flags_are_parsed() -> None:
    from typer.testing import CliRunner

    from soothe_cli.cli.main import app
    from soothe_cli.config.loader import load_config, reset_runtime_config

    reset_runtime_config()
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--daemon-host",
            "192.168.1.10",
            "--daemon-port",
            "7777",
            "--log-level",
            "WARNING",
            "--no-render-markdown",
            "help",
        ],
    )
    assert result.exit_code == 0
    cfg = load_config()
    assert cfg.daemon_host == "192.168.1.10"
    assert cfg.daemon_port == 7777
    assert cfg.logging_level == "WARNING"
    assert cfg.render_markdown is False
