"""Tests for `soothe loop continue` default LOOP_ID resolution."""

from typer.testing import CliRunner

from soothe_cli.cli.main import app


def test_loop_continue_without_loop_id_uses_most_recent_loop(monkeypatch) -> None:
    """Continue command auto-selects loop when LOOP_ID is omitted."""
    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd.load_config", lambda: {})
    monkeypatch.setattr(
        "soothe_cli.cli.commands.loop_cmd.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )
    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd._require_daemon", lambda _ws_url: None)

    captured = {}

    def fake_run_impl(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_impl", fake_run_impl)

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        if method == "loop_list":
            return {
                "loops": [
                    {"loop_id": "loop_running", "status": "running"},
                    {"loop_id": "loop_completed", "status": "completed"},
                ]
            }
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd._rpc", fake_rpc)

    result = CliRunner().invoke(app, ["loop", "continue"])
    assert result.exit_code == 0
    assert captured["resume_loop_id"] == "loop_running"
    assert captured["no_tui"] is False
    assert captured["autonomous"] is False
    assert captured["max_iterations"] is None


def test_loop_continue_without_loop_id_errors_when_no_loops(monkeypatch) -> None:
    """Continue command fails with clear error when no loops exist."""
    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd.load_config", lambda: {})
    monkeypatch.setattr(
        "soothe_cli.cli.commands.loop_cmd.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )
    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd._require_daemon", lambda _ws_url: None)

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        if method == "loop_list":
            return {"loops": []}
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd._rpc", fake_rpc)

    result = CliRunner().invoke(app, ["loop", "continue"])
    assert result.exit_code == 1
    assert "No loops found" in result.output


def test_loop_continue_with_explicit_loop_id_launches_tui(monkeypatch) -> None:
    """Explicit LOOP_ID bypasses lookup and opens TUI on that loop."""
    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd.load_config", lambda: {})
    monkeypatch.setattr(
        "soothe_cli.cli.commands.loop_cmd.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )
    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd._require_daemon", lambda _ws_url: None)

    captured = {}

    def fake_run_impl(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_impl", fake_run_impl)

    result = CliRunner().invoke(app, ["loop", "continue", "ggqfpkrumdbx"])
    assert result.exit_code == 0
    assert captured["resume_loop_id"] == "ggqfpkrumdbx"
