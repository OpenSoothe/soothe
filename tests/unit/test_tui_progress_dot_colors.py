"""TUI progress line prefix colors (agentic / LoopAgent completion)."""

from __future__ import annotations

from soothe.ux.tui.renderer import TuiRenderer
from soothe.ux.tui.utils import DOT_COLORS


def test_loop_completed_done_prefix_is_green() -> None:
    r = TuiRenderer(on_panel_write=lambda _x: None)
    c = r._progress_event_dot_color("soothe.agentic.loop.completed", {"status": "done"}, ())
    assert c == DOT_COLORS["plan_step_done"]


def test_loop_reason_done_prefix_is_green() -> None:
    r = TuiRenderer(on_panel_write=lambda _x: None)
    c = r._progress_event_dot_color("soothe.cognition.loop_agent.reason", {"status": "done"}, ())
    assert c == DOT_COLORS["plan_step_done"]


def test_agentic_step_completed_success_prefix_is_green() -> None:
    r = TuiRenderer(on_panel_write=lambda _x: None)
    c = r._progress_event_dot_color("soothe.agentic.step.completed", {"success": True}, ())
    assert c == DOT_COLORS["plan_step_done"]


def test_subagent_finalize_snapshot_then_short_main_prefix_suppresses_duplicate() -> None:
    """Subagent stream ends without on_tool_call; main echo must match short first chunk."""
    writes = 0

    def w(_x: object) -> None:
        nonlocal writes
        writes += 1

    r = TuiRenderer(on_panel_write=w, on_panel_update_last=lambda _x: None)
    body = "P" * 450  # >= _DUP_SNAPSHOT_MIN_CHARS
    r.on_assistant_text(body[:200], is_main=False, is_streaming=True)
    r.on_assistant_text(body[200:], is_main=False, is_streaming=False)
    # First main chunk shorter than 320 chars but matching snap prefix (variable n compare)
    r.on_assistant_text(body[:120], is_main=True, is_streaming=True)
    r.on_assistant_text(body[120:240], is_main=True, is_streaming=False)
    assert writes == 1


def test_subagent_then_distinct_main_starts_new_panel_entry() -> None:
    writes = 0

    def w(_x: object) -> None:
        nonlocal writes
        writes += 1

    r = TuiRenderer(on_panel_write=w, on_panel_update_last=lambda _x: None)
    sub = "S" * 450
    r.on_assistant_text(sub, is_main=False, is_streaming=False)
    r.on_assistant_text("different-main-text", is_main=True, is_streaming=False)
    assert writes == 2


def test_main_then_duplicate_main_suppressed_when_both_marked_main() -> None:
    """Executor/tool streams often have empty namespace → is_main=True for both echoes."""
    writes = 0

    def w(_x: object) -> None:
        nonlocal writes
        writes += 1

    r = TuiRenderer(on_panel_write=w, on_panel_update_last=lambda _x: None)
    body = "Q" * 450
    r.on_assistant_text(body[:200], is_main=True, is_streaming=True)
    r.on_assistant_text(body[200:], is_main=True, is_streaming=False)
    r.on_assistant_text(body[:120], is_main=True, is_streaming=True)
    r.on_assistant_text(body[120:240], is_main=True, is_streaming=False)
    assert writes == 1


def test_dedup_compare_ignores_block_drawing_noise() -> None:
    writes = 0

    def w(_x: object) -> None:
        nonlocal writes
        writes += 1

    r = TuiRenderer(on_panel_write=w, on_panel_update_last=lambda _x: None)
    base = "Z" * 450
    polluted = base[:220] + "\n\u2582\u2582\n" + base[220:]
    r.on_assistant_text(polluted, is_main=True, is_streaming=False)
    r.on_assistant_text(base[:130], is_main=True, is_streaming=True)
    r.on_assistant_text(base[130:260], is_main=True, is_streaming=False)
    assert writes == 1


def test_embed_duplicate_main_suppressed_after_subagent() -> None:
    """Main stream that re-embeds prior subagent body should not open a new panel entry (IG-130)."""
    writes = 0

    def w(_x: object) -> None:
        nonlocal writes
        writes += 1

    body = "T" * 450
    r = TuiRenderer(on_panel_write=w, on_panel_update_last=lambda _x: None)
    r.on_assistant_text(body, is_main=False, is_streaming=False)
    r.on_assistant_text("See below:\n" + body, is_main=True, is_streaming=False)
    assert writes == 1
