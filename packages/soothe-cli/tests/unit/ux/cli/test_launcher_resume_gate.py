"""Tests for the launcher resume gate (execution-state fetch on resume)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe_cli.cli.execution.launcher import _prompt_resume, _resume_gate, run_tui


def test_resume_gate_returns_state_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    monkeypatch.setattr(
        "soothe_cli.cli.execution.launcher.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        assert method == "loop_execution_state_fetch"
        assert params == {"loop_id": "loop-1"}
        return {
            "step_index": 3,
            "iteration": 2,
            "status": "running",
            "plan": {"steps": ["a", "b", "c"]},
        }

    monkeypatch.setattr("soothe_cli.cli.execution.launcher.protocol1_rpc", fake_rpc)

    state = _resume_gate(cfg, "loop-1")
    assert state is not None
    assert state["step_index"] == 3
    assert state["iteration"] == 2
    assert state["status"] == "running"


def test_resume_gate_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    monkeypatch.setattr(
        "soothe_cli.cli.execution.launcher.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        return {"error": "loop not found"}

    monkeypatch.setattr("soothe_cli.cli.execution.launcher.protocol1_rpc", fake_rpc)

    state = _resume_gate(cfg, "loop-gone")
    assert state is None


def test_resume_gate_returns_none_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    monkeypatch.setattr(
        "soothe_cli.cli.execution.launcher.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        raise RuntimeError("daemon unreachable")

    monkeypatch.setattr("soothe_cli.cli.execution.launcher.protocol1_rpc", fake_rpc)

    state = _resume_gate(cfg, "loop-1")
    assert state is None


def test_run_tui_resume_surfaces_step_index(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """run_tui with auto_resume and a running loop prints the daemon step index."""
    cfg = MagicMock()
    cfg.auto_resume = True
    monkeypatch.setattr(
        "soothe_cli.cli.execution.launcher.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        return {"step_index": 5, "iteration": 1, "status": "running", "plan": None}

    monkeypatch.setattr("soothe_cli.cli.execution.launcher.protocol1_rpc", fake_rpc)

    monkeypatch.setattr("soothe_cli.tui.run_textual_tui", lambda **_kw: None)

    run_tui(cfg, resume_loop_id="loop-resume", initial_prompt=None)

    captured = capsys.readouterr()
    assert "Resuming loop loop-resume" in captured.out
    assert "iteration 1" in captured.out
    assert "step 5" in captured.out
    assert "running" in captured.out


def test_run_tui_idle_status_starts_fresh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A terminal/idle loop status starts a fresh session instead of resuming."""
    cfg = MagicMock()
    cfg.auto_resume = True
    monkeypatch.setattr(
        "soothe_cli.cli.execution.launcher.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        return {"step_index": 5, "iteration": 1, "status": "idle", "plan": None}

    monkeypatch.setattr("soothe_cli.cli.execution.launcher.protocol1_rpc", fake_rpc)
    monkeypatch.setattr("soothe_cli.tui.run_textual_tui", lambda **_kw: None)

    run_tui(cfg, resume_loop_id="loop-done", initial_prompt=None)

    captured = capsys.readouterr()
    assert "is idle" in captured.out
    assert "starting fresh session" in captured.out
    assert "Resuming loop" not in captured.out


def test_run_tui_prompt_confirms_resume(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without auto_resume, the user is prompted and 'y' confirms resume."""
    cfg = MagicMock()
    cfg.auto_resume = False
    monkeypatch.setattr(
        "soothe_cli.cli.execution.launcher.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        return {"step_index": 2, "iteration": 1, "status": "running", "plan": None}

    monkeypatch.setattr("soothe_cli.cli.execution.launcher.protocol1_rpc", fake_rpc)
    monkeypatch.setattr("soothe_cli.tui.run_textual_tui", lambda **_kw: None)
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: "y")

    run_tui(cfg, resume_loop_id="loop-prompt", initial_prompt=None)

    captured = capsys.readouterr()
    assert "Active loop found" in captured.out
    assert "Resuming loop loop-prompt" in captured.out


def test_run_tui_prompt_discards_resume(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without auto_resume, 'n' discards the loop and starts fresh."""
    cfg = MagicMock()
    cfg.auto_resume = False
    monkeypatch.setattr(
        "soothe_cli.cli.execution.launcher.websocket_url_from_config",
        lambda _cfg: "ws://test",
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        return {"step_index": 2, "iteration": 1, "status": "running", "plan": None}

    monkeypatch.setattr("soothe_cli.cli.execution.launcher.protocol1_rpc", fake_rpc)
    monkeypatch.setattr("soothe_cli.tui.run_textual_tui", lambda **_kw: None)
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: "n")

    run_tui(cfg, resume_loop_id="loop-prompt", initial_prompt=None)

    captured = capsys.readouterr()
    assert "Loop discarded" in captured.out
    assert "Resuming loop" not in captured.out


def test_prompt_resume_non_tty_auto_resumes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-interactive stdin (no TTY) auto-resumes without prompting."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    state = {"step_index": 1, "iteration": 0, "status": "running"}
    assert _prompt_resume("loop-1", state) is True
    captured = capsys.readouterr()
    assert "Non-interactive" in captured.out


def test_run_tui_no_resume_skips_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a resume_loop_id, the gate is not invoked."""
    cfg = MagicMock()
    called: list[str] = []

    async def fake_rpc(_ws_url, method, params=None, *, mode="request", timeout=30.0):  # noqa: ARG001
        called.append(method)
        return {}

    monkeypatch.setattr("soothe_cli.cli.execution.launcher.protocol1_rpc", fake_rpc)
    monkeypatch.setattr("soothe_cli.tui.run_textual_tui", lambda **_kw: None)

    run_tui(cfg, resume_loop_id=None, initial_prompt=None)

    assert called == []
