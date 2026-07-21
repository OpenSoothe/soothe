"""Tests for daemon lifecycle CLI commands."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from soothe_daemon.cli import app
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus, HealthReport

runner = CliRunner()


def test_status_reports_stopped(monkeypatch) -> None:
    monkeypatch.setattr("soothe_daemon.cli._fast_is_running", lambda: (False, False))

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Daemon status: stopped" in result.stdout


def test_status_reports_running_with_pid(monkeypatch, tmp_path: Path) -> None:
    # Redirect PID path so the test doesn't pick up a real daemon's PID file
    monkeypatch.setattr("soothe_daemon.cli.SOOTHE_HOME", tmp_path)
    monkeypatch.setattr("soothe_daemon.cli._fast_is_running", lambda: (True, False))
    monkeypatch.setattr("soothe_daemon.cli._fast_find_pid", lambda: 12345)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Daemon status: running" in result.stdout
    assert "orphan" not in result.stdout
    assert "PID: 12345" in result.stdout
    assert "ws://" in result.stdout


def test_status_reports_orphan(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("soothe_daemon.cli.SOOTHE_HOME", tmp_path)
    monkeypatch.setattr("soothe_daemon.cli._fast_is_running", lambda: (True, True))
    monkeypatch.setattr("soothe_daemon.cli._fast_find_pid", lambda: 47263)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "orphan" in result.stdout
    assert "PID file missing" in result.stdout
    assert "PID: 47263" in result.stdout


def test_start_fails_if_already_running(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("soothe_daemon.cli.SOOTHE_HOME", tmp_path)
    monkeypatch.setattr("soothe_daemon.cli._fast_is_running", lambda: (True, False))
    monkeypatch.setattr("soothe_daemon.cli._fast_find_pid", lambda: 99)
    # Mock daemon config to not load any file
    daemon_cfg = SootheDaemonConfig()
    daemon_cfg.soothe_config_path = tmp_path / "config.yml"
    monkeypatch.setattr(
        "soothe_daemon.cli._load_daemon_config",
        lambda *_args: daemon_cfg,
    )

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 1
    assert "already running" in result.stdout


def test_start_background_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("soothe_daemon.cli.SOOTHE_HOME", tmp_path)

    state = {"calls": 0}

    def _is_running() -> tuple[bool, bool]:
        state["calls"] += 1
        return (state["calls"] >= 2, False)

    monkeypatch.setattr("soothe_daemon.cli._fast_is_running", _is_running)
    monkeypatch.setattr("soothe_daemon.cli._fast_find_pid", lambda: 4242)
    # Mock daemon config to not load any file
    daemon_cfg = SootheDaemonConfig()
    daemon_cfg.soothe_config_path = tmp_path / "config.yml"
    monkeypatch.setattr(
        "soothe_daemon.cli._load_daemon_config",
        lambda *_args: daemon_cfg,
    )
    monkeypatch.setattr("soothe_daemon.cli.time.sleep", lambda _v: None)

    popen_called = {"value": False}

    def _fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        popen_called["value"] = True
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr("soothe_daemon.cli.subprocess.Popen", _fake_popen)

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    assert popen_called["value"] is True
    assert "Daemon started successfully" in result.stdout
    assert "PID: 4242" in result.stdout
    assert "ws://" in result.stdout


def test_stop_reports_not_running(monkeypatch) -> None:
    # Mock the SootheDaemon class methods (lazy import will happen on access)
    monkeypatch.setattr("soothe_daemon.server.SootheDaemon.find_pid", staticmethod(lambda: None))
    monkeypatch.setattr(
        "soothe_daemon.server.SootheDaemon.stop_running", staticmethod(lambda: False)
    )

    result = runner.invoke(app, ["stop"])

    assert result.exit_code == 1
    assert "No running daemon found." in result.stdout


def test_help_subcommand_shows_root_help() -> None:
    result = runner.invoke(app, ["help"])

    assert result.exit_code == 0
    # Strip ANSI color codes for assertion
    import re

    clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "Usage: soothed [OPTIONS] COMMAND [ARGS]..." in clean_output
    assert "Commands" in clean_output
    assert "start" in clean_output


def _make_health_report(status: CheckStatus) -> HealthReport:
    return HealthReport(
        timestamp="2026-01-01T00:00:00Z",
        soothe_version="0.0.0",
        config_path=None,
        overall_status=status,
        categories=[
            CategoryResult(
                category="daemon",
                status=status,
                checks=[CheckResult(name="daemon_running", status=status, message="daemon health")],
            )
        ],
    )


def test_doctor_json_format_with_filters(monkeypatch) -> None:
    report = _make_health_report(CheckStatus.OK)
    captured: dict[str, object] = {}

    class _FakeChecker:
        def __init__(self, _cfg: object, daemon_config: object = None) -> None:
            pass

        async def run_all_checks(  # type: ignore[no-untyped-def]
            self, categories=None, exclude=None
        ) -> HealthReport:
            captured["categories"] = categories
            captured["exclude"] = exclude
            return report

    # Mock at the module where HealthChecker is actually imported (health.checker)
    monkeypatch.setattr("soothe_daemon.health.checker.HealthChecker", _FakeChecker)
    monkeypatch.setattr(
        "soothe_daemon.health.formatters.format_json", lambda _report: '{"ok": true}'
    )
    # Mock config loading
    monkeypatch.setattr(
        "soothe_daemon.cli._load_daemon_config",
        lambda *_args: SootheDaemonConfig(),
    )

    result = runner.invoke(
        app,
        ["doctor", "--format", "json", "--category", "daemon", "--exclude", "external_apis"],
    )

    assert result.exit_code == 0
    assert '{"ok": true}' in result.stdout
    assert captured["categories"] == ["daemon"]
    assert captured["exclude"] == ["external_apis"]


def test_doctor_invalid_format(monkeypatch) -> None:
    result = runner.invoke(app, ["doctor", "--format", "xml"])

    assert result.exit_code == 2
    assert "Invalid format" in result.output


def test_doctor_fail_on_warning(monkeypatch) -> None:
    report = _make_health_report(CheckStatus.WARNING)

    class _FakeChecker:
        def __init__(self, _cfg: object, daemon_config: object = None) -> None:
            pass

        async def run_all_checks(  # type: ignore[no-untyped-def]
            self, categories=None, exclude=None
        ) -> HealthReport:
            return report

    monkeypatch.setattr("soothe_daemon.health.checker.HealthChecker", _FakeChecker)
    monkeypatch.setattr(
        "soothe_daemon.health.formatters.format_text", lambda _r, use_color=True: "warn report"
    )
    monkeypatch.setattr(
        "soothe_daemon.cli._load_daemon_config",
        lambda *_args: SootheDaemonConfig(),
    )

    result = runner.invoke(app, ["doctor", "--fail-on", "warning"])

    assert result.exit_code == 1
    assert "warn report" in result.stdout


def test_doctor_output_to_file(monkeypatch, tmp_path: Path) -> None:
    report = _make_health_report(CheckStatus.OK)

    class _FakeChecker:
        def __init__(self, _cfg: object, daemon_config: object = None) -> None:
            pass

        async def run_all_checks(  # type: ignore[no-untyped-def]
            self, categories=None, exclude=None
        ) -> HealthReport:
            return report

    monkeypatch.setattr("soothe_daemon.health.checker.HealthChecker", _FakeChecker)
    monkeypatch.setattr("soothe_daemon.health.formatters.format_markdown", lambda _r: "# report")
    monkeypatch.setattr(
        "soothe_daemon.cli._load_daemon_config",
        lambda *_args: SootheDaemonConfig(),
    )
    output_file = tmp_path / "doctor.md"

    result = runner.invoke(app, ["doctor", "--format", "markdown", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.read_text() == "# report"
    assert "Health report written to" in result.stdout
