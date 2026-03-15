"""Tests for TUI/headless progress rendering behavior."""

from __future__ import annotations

from soothe.cli.main import _render_progress_event
from soothe.cli.tui_shared import TuiState, _handle_protocol_event, _handle_subagent_text_activity


def test_render_progress_event_policy_includes_profile(capsys) -> None:
    _render_progress_event({"type": "soothe.policy.checked", "verdict": "allow", "profile": "strict"})
    captured = capsys.readouterr()
    assert "[policy] allow (profile=strict)" in captured.err


def test_tui_policy_activity_includes_profile() -> None:
    state = TuiState()
    _handle_protocol_event(
        {"type": "soothe.policy.checked", "verdict": "allow", "profile": "standard"},
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "Policy: allow (profile=standard)" in state.activity_lines[0].plain


def test_subagent_text_activity_respects_verbosity() -> None:
    state = TuiState()
    _handle_subagent_text_activity(("tools:abc",), "working on it", state, verbosity="normal")
    assert state.activity_lines == []

    _handle_subagent_text_activity(("tools:abc",), "working on it", state, verbosity="detailed")
    assert len(state.activity_lines) == 1
    assert "Text: working on it" in state.activity_lines[0].plain
