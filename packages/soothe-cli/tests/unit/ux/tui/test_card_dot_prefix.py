"""Card prefix dot helpers (Claude Code-style ⏺ headers)."""

from __future__ import annotations

from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.theme import DARK_COLORS
from soothe_cli.tui.widgets.messages._helpers import (
    _assemble_card_header,
    _card_dot_glyph,
    _card_dot_tone,
)


def test_card_dot_glyph_uses_tool_prefix_by_default() -> None:
    g = get_glyphs()
    assert _card_dot_glyph("pending") == g.tool_prefix
    assert _card_dot_glyph("success") == g.tool_prefix
    assert _card_dot_glyph("running", spinner_position=3, animate_running=True) == g.tool_prefix


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
