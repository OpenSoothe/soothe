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

    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd.protocol1_rpc", fake_rpc)

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

    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd.protocol1_rpc", fake_rpc)

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


def test_loop_resume_is_alias_of_continue(monkeypatch) -> None:
    """Resume subcommand delegates to continue with the same arguments."""
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
        if method == "loop_execution_state_fetch":
            return {"step_index": 2, "iteration": 1, "status": "running", "plan": None}
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd.protocol1_rpc", fake_rpc)

    result = CliRunner().invoke(app, ["loop", "resume", "loop_abc123", "--prompt", "hello"])
    assert result.exit_code == 0
    assert captured["resume_loop_id"] == "loop_abc123"
    assert captured["prompt"] == "hello"
    # Resume surfaces the daemon step index
    assert "iteration 1" in result.output
    assert "step 2" in result.output


def test_loop_continue_resume_flag_fetches_step_index(monkeypatch) -> None:
    """`continue --resume` fetches execution state and surfaces step index."""
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
        if method == "loop_execution_state_fetch":
            return {
                "step_index": 4,
                "iteration": 2,
                "status": "idle",
                "plan": {"steps": ["a", "b"]},
            }
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd.protocol1_rpc", fake_rpc)

    result = CliRunner().invoke(app, ["loop", "continue", "loop_xyz", "--resume"])
    assert result.exit_code == 0
    assert captured["resume_loop_id"] == "loop_xyz"
    assert "iteration 2" in result.output
    assert "step 4" in result.output
    assert "idle" in result.output


def test_loop_continue_resume_without_flag_skips_fetch(monkeypatch) -> None:
    """Without --resume, continue does not call loop_execution_state_fetch."""
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

    called_methods: list[str] = []

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        called_methods.append(method)
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr("soothe_cli.cli.commands.loop_cmd.protocol1_rpc", fake_rpc)

    result = CliRunner().invoke(app, ["loop", "continue", "loop_abc"])
    assert result.exit_code == 0
    assert captured["resume_loop_id"] == "loop_abc"
    # No execution-state fetch without --resume
    assert "loop_execution_state_fetch" not in called_methods
