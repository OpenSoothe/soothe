"""Card prefix dot helpers (Claude Code-style ⏺ headers)."""

from __future__ import annotations

from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.theme import DARK_COLORS
from soothe_cli.tui.widgets.messages._helpers import (
    _assemble_card_header,
    _card_dot_tone,
)
from soothe_cli.tui.widgets.messages.assistant import AssistantMessage
from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage


def test_card_dot_tone_maps_lifecycle_phases() -> None:
    colors = DARK_COLORS
    assert _card_dot_tone("success", colors) == colors.card_success
    assert _card_dot_tone("error", colors) == colors.card_error
    assert _card_dot_tone("running", colors) == colors.muted
    assert _card_dot_tone("pending", colors) == colors.muted


def test_card_dot_tone_flashes_running_dot() -> None:
    colors = DARK_COLORS
    bright = _card_dot_tone("running", colors, spinner_position=0, animate_running=True)
    dim = _card_dot_tone("running", colors, spinner_position=1, animate_running=True)
    assert bright == colors.muted
    assert dim == colors.card_activity_muted
    assert bright != dim


def test_assemble_card_header_includes_dot_and_body() -> None:
    content = _assemble_card_header(None, "Scan workspace", status="running")
    plain = content.plain
    assert plain.startswith(get_glyphs().tool_prefix)
    assert "Scan workspace" in plain


def test_stream_cards_use_flush_horizontal_padding() -> None:
    """Agent cards no longer reserve space for removed border-left rails."""
    step_css = CognitionStepMessage.DEFAULT_CSS
    assistant_css = AssistantMessage.DEFAULT_CSS
    assert "padding: 0;" in step_css
    assert "padding: 0;" in assistant_css
    assert "border-left:" not in step_css
    assert "border-left:" not in assistant_css


def test_step_status_footer_uses_same_muted_base_as_tool_activity() -> None:
    """Footer status line shares $text-muted with tool/subagent activity panels."""
    step_css = CognitionStepMessage.DEFAULT_CSS
    assert "CognitionStepMessage .step-status" in step_css
    assert "color: $text-muted;" in step_css
