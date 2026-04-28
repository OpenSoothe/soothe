"""Tests for daemon lifecycle CLI commands."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from soothe.cli.daemon_main import app
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus, HealthReport

runner = CliRunner()


def test_status_reports_stopped(monkeypatch) -> None:
    monkeypatch.setattr(
        "soothe.cli.daemon_main.SootheDaemon.is_running", staticmethod(lambda: False)
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Daemon status: stopped" in result.stdout


def test_status_reports_running_with_pid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("soothe.cli.daemon_main.SOOTHE_HOME", str(tmp_path))
    monkeypatch.setattr(
        "soothe.cli.daemon_main.SootheDaemon.is_running", staticmethod(lambda: True)
    )
    monkeypatch.setattr("soothe.cli.daemon_main.SootheDaemon.find_pid", staticmethod(lambda: 12345))

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Daemon status: running" in result.stdout
    assert "PID: 12345" in result.stdout
    assert "soothe.sock" in result.stdout


def test_start_fails_if_already_running(monkeypatch) -> None:
    monkeypatch.setattr(
        "soothe.cli.daemon_main.SootheDaemon.is_running", staticmethod(lambda: True)
    )
    monkeypatch.setattr("soothe.cli.daemon_main.SootheDaemon.find_pid", staticmethod(lambda: 99))

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 1
    assert "already running" in result.stdout


def test_start_background_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("soothe.cli.daemon_main.SOOTHE_HOME", str(tmp_path))

    state = {"calls": 0}

    def _is_running() -> bool:
        state["calls"] += 1
        return state["calls"] >= 2

    monkeypatch.setattr("soothe.cli.daemon_main.SootheDaemon.is_running", staticmethod(_is_running))
    monkeypatch.setattr("soothe.cli.daemon_main.SootheDaemon.find_pid", staticmethod(lambda: 4242))
    monkeypatch.setattr("soothe.cli.daemon_main._load_config", lambda _path: None)
    monkeypatch.setattr("soothe.cli.daemon_main.time.sleep", lambda _v: None)

    popen_called = {"value": False}

    def _fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        popen_called["value"] = True
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr("soothe.cli.daemon_main.subprocess.Popen", _fake_popen)

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    assert popen_called["value"] is True
    assert "Daemon started successfully" in result.stdout
    assert "PID: 4242" in result.stdout
    assert "soothe.sock" in result.stdout


def test_stop_reports_not_running(monkeypatch) -> None:
    monkeypatch.setattr("soothe.cli.daemon_main.SootheDaemon.find_pid", staticmethod(lambda: None))
    monkeypatch.setattr(
        "soothe.cli.daemon_main.SootheDaemon.stop_running", staticmethod(lambda: False)
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
        def __init__(self, _cfg: object) -> None:
            pass

        async def run_all_checks(  # type: ignore[no-untyped-def]
            self, categories=None, exclude=None
        ) -> HealthReport:
            captured["categories"] = categories
            captured["exclude"] = exclude
            return report

    monkeypatch.setattr("soothe.cli.daemon_main.HealthChecker", _FakeChecker)
    monkeypatch.setattr("soothe.cli.daemon_main.format_json", lambda _report: '{"ok": true}')

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
        def __init__(self, _cfg: object) -> None:
            pass

        async def run_all_checks(  # type: ignore[no-untyped-def]
            self, categories=None, exclude=None
        ) -> HealthReport:
            return report

    monkeypatch.setattr("soothe.cli.daemon_main.HealthChecker", _FakeChecker)
    monkeypatch.setattr(
        "soothe.cli.daemon_main.format_text", lambda _r, use_color=True: "warn report"
    )

    result = runner.invoke(app, ["doctor", "--fail-on", "warning"])

    assert result.exit_code == 1
    assert "warn report" in result.stdout


def test_doctor_output_to_file(monkeypatch, tmp_path: Path) -> None:
    report = _make_health_report(CheckStatus.OK)

    class _FakeChecker:
        def __init__(self, _cfg: object) -> None:
            pass

        async def run_all_checks(  # type: ignore[no-untyped-def]
            self, categories=None, exclude=None
        ) -> HealthReport:
            return report

    monkeypatch.setattr("soothe.cli.daemon_main.HealthChecker", _FakeChecker)
    monkeypatch.setattr("soothe.cli.daemon_main.format_markdown", lambda _r: "# report")
    output_file = tmp_path / "doctor.md"

    result = runner.invoke(app, ["doctor", "--format", "markdown", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.read_text() == "# report"
    assert "Health report written to" in result.stdout
