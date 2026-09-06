"""Card-prefix glyph helpers for message headers."""

from __future__ import annotations

from textual.content import Content

from soothe_cli.display.card import (
    _assemble_card_header,
    _card_body_gutter,
    _card_dot_tone,
    _card_item_indent,
)
from soothe_cli.display.theme import DARK_COLORS, LIGHT_COLORS, ThemeColors
from soothe_cli.settings import ASCII_GLYPHS, UNICODE_GLYPHS, get_glyphs
from soothe_cli.tui.widgets.messages.assistant import AssistantMessage
from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage
from soothe_cli.tui.widgets.messages.structured_ask_user import StructuredAskUserWidget


def test_card_dot_tone_maps_lifecycle_phases() -> None:
    colors = DARK_COLORS
    assert _card_dot_tone("success", colors) == colors.card_success
    assert _card_dot_tone("error", colors) == colors.card_error
    assert _card_dot_tone("running", colors) == colors.card_running
    assert _card_dot_tone("pending", colors) == colors.muted


def test_card_dot_tone_flashes_running_dot() -> None:
    colors = DARK_COLORS
    bright = _card_dot_tone("running", colors, spinner_position=0, animate_running=True)
    dim = _card_dot_tone("running", colors, spinner_position=1, animate_running=True)
    assert bright == colors.card_running
    assert dim == colors.card_running_muted
    assert bright != dim


def test_assemble_card_header_includes_dot_and_body() -> None:
    content = _assemble_card_header(None, "Scan workspace", status="running")
    plain = content.plain
    assert plain.startswith(get_glyphs().tool_prefix)
    assert "Scan workspace" in plain


def test_assemble_card_header_allows_glyph_override() -> None:
    glyph = get_glyphs().subagent_prefix
    content = _assemble_card_header(
        None,
        "browser(Collect examples)",
        status="running",
        glyph_override=glyph,
    )
    plain = content.plain
    assert plain.startswith(glyph)
    assert "Collect examples" in plain


# ---------------------------------------------------------------------------
# _card_dot_tone — exhaustive lifecycle phase, accent, and edge cases
# ---------------------------------------------------------------------------


def test_card_dot_tone_success_aliases_all_return_card_success() -> None:
    """``success``, ``done``, ``completed`` all map to ``card_success``."""
    colors = DARK_COLORS
    for phase in ("success", "done", "completed"):
        assert _card_dot_tone(phase, colors) == colors.card_success, phase


def test_card_dot_tone_error_aliases_all_return_card_error() -> None:
    """``error``, ``failed``, ``interrupted`` all map to ``card_error``."""
    colors = DARK_COLORS
    for phase in ("error", "failed", "interrupted"):
        assert _card_dot_tone(phase, colors) == colors.card_error, phase


def test_card_dot_tone_queued_aliases_return_muted() -> None:
    """``queued``, ``pending``, ``continue``, ``replan`` map to ``muted``."""
    colors = DARK_COLORS
    for phase in ("queued", "pending", "continue", "replan"):
        assert _card_dot_tone(phase, colors) == colors.muted, phase


def test_card_dot_tone_light_theme_uses_light_palette() -> None:
    """Light theme colors are distinct from dark theme for each phase."""
    assert _card_dot_tone("success", LIGHT_COLORS) == LIGHT_COLORS.card_success
    assert _card_dot_tone("running", LIGHT_COLORS) == LIGHT_COLORS.card_running
    assert _card_dot_tone("error", LIGHT_COLORS) == LIGHT_COLORS.card_error
    assert _card_dot_tone("pending", LIGHT_COLORS) == LIGHT_COLORS.muted
    # Light and dark palettes differ for every phase
    assert LIGHT_COLORS.card_success != DARK_COLORS.card_success
    assert LIGHT_COLORS.card_running != DARK_COLORS.card_running
    assert LIGHT_COLORS.card_error != DARK_COLORS.card_error
    assert LIGHT_COLORS.muted != DARK_COLORS.muted


def test_card_dot_tone_running_animation_only_flashes_on_odd_positions() -> None:
    """With ``animate_running`` true, odd spinner positions flash muted."""
    colors = DARK_COLORS
    # Even positions stay bright
    for pos in (0, 2, 4, 10):
        assert (
            _card_dot_tone("running", colors, spinner_position=pos, animate_running=True)
            == colors.card_running
        ), pos
    # Odd positions flash to the muted running color
    for pos in (1, 3, 5, 11):
        assert (
            _card_dot_tone("running", colors, spinner_position=pos, animate_running=True)
            == colors.card_running_muted
        ), pos


def test_card_dot_tone_running_animation_disabled_ignores_spinner_position() -> None:
    """When ``animate_running`` is False, spinner_position has no effect."""
    colors = DARK_COLORS
    for pos in (0, 1, 2, 99):
        assert (
            _card_dot_tone("running", colors, spinner_position=pos, animate_running=False)
            == colors.card_running
        ), pos


def test_card_dot_tone_accent_only_applies_to_unrecognized_phases() -> None:
    """``accent`` is a fallback for unknown statuses; known phases ignore it."""
    colors = DARK_COLORS
    accent = "#ABCDEF"
    # Known phases ignore accent
    assert _card_dot_tone("success", colors, accent=accent) == colors.card_success
    assert _card_dot_tone("running", colors, accent=accent) == colors.card_running
    assert _card_dot_tone("error", colors, accent=accent) == colors.card_error
    assert _card_dot_tone("pending", colors, accent=accent) == colors.muted
    # Unknown phase falls back to accent
    assert _card_dot_tone("custom-phase", colors, accent=accent) == accent


def test_card_dot_tone_unknown_phase_without_accent_returns_muted() -> None:
    """An unrecognized phase with no accent falls back to ``muted``."""
    colors = DARK_COLORS
    assert _card_dot_tone("nonexistent", colors) == colors.muted


def test_card_dot_tone_normalizes_whitespace_and_case() -> None:
    """Status is stripped and lowercased before matching."""
    colors = DARK_COLORS
    assert _card_dot_tone("  Success  ", colors) == colors.card_success
    assert _card_dot_tone("RUNNING", colors) == colors.card_running
    assert _card_dot_tone("\tError\n", colors) == colors.card_error


def test_card_dot_tone_empty_and_none_status_default_to_pending() -> None:
    """Empty string and ``None`` status both resolve to the pending (muted) tone."""
    colors = DARK_COLORS
    assert _card_dot_tone("", colors) == colors.muted
    assert _card_dot_tone(None, colors) == colors.muted  # type: ignore[arg-type]


def test_card_dot_tone_returns_style_string_not_theme_object() -> None:
    """The return value is a plain string (a Textual style/hex), not a ThemeColors."""
    result = _card_dot_tone("success", DARK_COLORS)
    assert isinstance(result, str)
    assert result.startswith("#")


# ---------------------------------------------------------------------------
# _card_body_gutter — alignment padding for body/tree-branch lines
# ---------------------------------------------------------------------------


def test_card_body_gutter_unicode_prefix_pads_to_two_columns() -> None:
    """Unicode ``⎿`` (1 col) + 1 pad = prefix width of 2 (● + space)."""
    gutter = _card_body_gutter(UNICODE_GLYPHS.tool_prefix)
    assert gutter == "⎿ "
    assert len(gutter) == 2


def test_card_body_gutter_ascii_prefix_width_pads_to_four_columns() -> None:
    """An ASCII-width prefix (``[*]``) pads the gutter to 4 columns.

    The tree glyph itself (``⎿``) always comes from the *detected* glyphs set,
    so only the padding width tracks ``glyph_override`` — here 3 spaces follow
    the 1-column ``⎿`` to reach the ASCII prefix width of 4.
    """
    gutter = _card_body_gutter(ASCII_GLYPHS.tool_prefix)
    assert gutter == "⎿   "
    assert len(gutter) == 4


def test_card_body_gutter_starts_with_output_prefix_glyph() -> None:
    """Gutter always begins with the detected ``output_prefix`` tree glyph."""
    gutter = _card_body_gutter()
    assert gutter.startswith(UNICODE_GLYPHS.output_prefix)


def test_card_body_gutter_custom_single_char_glyph_pads_to_two() -> None:
    """A 1-col custom glyph yields prefix width 2, so 1 pad space follows."""
    assert _card_body_gutter("X") == "⎿ "


def test_card_body_gutter_custom_three_char_glyph_pads_to_four() -> None:
    """A 3-col custom glyph yields prefix width 4, so 3 pad spaces follow."""
    assert _card_body_gutter("ABC") == "⎿   "


def test_card_body_gutter_width_matches_prefix_width() -> None:
    """Gutter display width always equals the card prefix width."""
    from soothe_cli.display.card import _card_prefix_width
    from soothe_cli.display.tool_display import display_width

    for glyph in (None, UNICODE_GLYPHS.tool_prefix, ASCII_GLYPHS.tool_prefix, "X", "ABC"):
        gutter = _card_body_gutter(glyph)
        assert display_width(gutter) == _card_prefix_width(glyph)


# ---------------------------------------------------------------------------
# _card_item_indent — plain-space indent for activity item rows
# ---------------------------------------------------------------------------


def test_card_item_indent_unicode_prefix_returns_two_spaces() -> None:
    """Unicode prefix width is 2 (● + space); default indent is 2 spaces."""
    assert _card_item_indent(glyph_override=UNICODE_GLYPHS.tool_prefix) == "  "


def test_card_item_indent_ascii_prefix_returns_four_spaces() -> None:
    """ASCII prefix width is 4 ([*] + space); default indent is 4 spaces."""
    assert _card_item_indent(glyph_override=ASCII_GLYPHS.tool_prefix) == "    "


def test_card_item_indent_extra_indent_adds_columns() -> None:
    """``extra_indent`` columns are appended beyond the prefix width."""
    # Unicode prefix width 2 + extra 2 = 4 spaces
    assert _card_item_indent(2, glyph_override=UNICODE_GLYPHS.tool_prefix) == "    "
    # ASCII prefix width 4 + extra 3 = 7 spaces
    assert _card_item_indent(3, glyph_override=ASCII_GLYPHS.tool_prefix) == "       "


def test_card_item_indent_zero_extra_equals_default() -> None:
    """``extra_indent=0`` produces the same indent as the default."""
    assert _card_item_indent(0, glyph_override=UNICODE_GLYPHS.tool_prefix) == "  "
    assert _card_item_indent(0, glyph_override=ASCII_GLYPHS.tool_prefix) == "    "


def test_card_item_indent_negative_extra_clamps_to_zero_total() -> None:
    """A negative ``extra_indent`` is clamped via ``max(0, ...)`` so the
    result is never shorter than zero spaces (here prefix_width-1)."""
    # Unicode prefix width 2 + (-1) -> max(0, 1) = 1 space
    assert _card_item_indent(-1, glyph_override=UNICODE_GLYPHS.tool_prefix) == " "
    # A large negative clamps fully to 0 spaces
    assert _card_item_indent(-100, glyph_override=UNICODE_GLYPHS.tool_prefix) == ""


def test_card_item_indent_default_no_args_matches_detected_glyphs() -> None:
    """With no overrides, indent width tracks the detected glyphs prefix width."""
    from soothe_cli.display.card import _card_prefix_width

    indent = _card_item_indent()
    assert len(indent) == _card_prefix_width()


def test_card_item_indent_returns_only_spaces_no_tree_glyph() -> None:
    """Item indent is plain spaces (unlike the gutter which includes ``⎿``)."""
    indent = _card_item_indent(glyph_override=ASCII_GLYPHS.tool_prefix)
    assert indent == "    "
    assert set(indent) == {" "}


# ---------------------------------------------------------------------------
# _assemble_card_header — full header Content assembly with styles
# ---------------------------------------------------------------------------


def test_assemble_card_header_running_status_uses_running_tone() -> None:
    """Running header prefix is styled with ``card_running`` and body with foreground."""
    content = _assemble_card_header(None, "Working", status="running")
    assert isinstance(content, Content)
    assert content.plain == f"{get_glyphs().tool_prefix} Working"
    styles = [str(span.style) for span in content.spans]
    assert DARK_COLORS.card_running in styles
    assert DARK_COLORS.foreground in styles


def test_assemble_card_header_success_status_uses_success_tone() -> None:
    """Success header prefix is styled with ``card_success``."""
    content = _assemble_card_header(None, "Done", status="success")
    styles = [str(span.style) for span in content.spans]
    assert DARK_COLORS.card_success in styles
    assert DARK_COLORS.foreground in styles


def test_assemble_card_header_error_status_uses_error_tone() -> None:
    """Error header prefix is styled with ``card_error``."""
    content = _assemble_card_header(None, "Failed step", status="error")
    styles = [str(span.style) for span in content.spans]
    assert DARK_COLORS.card_error in styles


def test_assemble_card_header_pending_status_uses_muted_tone() -> None:
    """Pending header prefix is styled with ``muted``."""
    content = _assemble_card_header(None, "Queued", status="pending")
    styles = [str(span.style) for span in content.spans]
    assert DARK_COLORS.muted in styles


def test_assemble_card_header_accent_applied_for_unknown_status() -> None:
    """An unrecognized status with an accent uses the accent for the prefix."""
    accent = "#A78BFA"
    content = _assemble_card_header(None, "Skill run", status="skill", accent=accent)
    styles = [str(span.style) for span in content.spans]
    assert accent in styles
    assert DARK_COLORS.foreground in styles


def test_assemble_card_header_accent_ignored_for_known_status() -> None:
    """A known status (success) ignores the accent override."""
    accent = "#A78BFA"
    content = _assemble_card_header(None, "Done", status="success", accent=accent)
    styles = [str(span.style) for span in content.spans]
    assert accent not in styles
    assert DARK_COLORS.card_success in styles


def test_assemble_card_header_glyph_override_replaces_prefix_glyph() -> None:
    """``glyph_override`` swaps the prefix glyph (e.g. subagent ``◆``)."""
    glyph = UNICODE_GLYPHS.subagent_prefix
    content = _assemble_card_header(None, "Orchestrating", status="running", glyph_override=glyph)
    assert content.plain.startswith(glyph)
    assert "Orchestrating" in content.plain


def test_assemble_card_header_running_animation_flashes_prefix_tone() -> None:
    """Animating a running header flashes the prefix to ``card_running_muted``."""
    bright = _assemble_card_header(
        None, "Step", status="running", spinner_position=0, animate_running=True
    )
    dim = _assemble_card_header(
        None, "Step", status="running", spinner_position=1, animate_running=True
    )
    bright_styles = [str(s.style) for s in bright.spans]
    dim_styles = [str(s.style) for s in dim.spans]
    assert DARK_COLORS.card_running in bright_styles
    assert DARK_COLORS.card_running_muted in dim_styles


def test_assemble_card_header_empty_body_still_has_prefix() -> None:
    """An empty body string yields a prefix-only Content with one span."""
    content = _assemble_card_header(None, "", status="pending")
    assert content.plain == f"{get_glyphs().tool_prefix} "
    # Only the prefix span is present (empty body contributes no styled span)
    assert len(content.spans) == 1
    assert str(content.spans[0].style) == DARK_COLORS.muted


def test_assemble_card_header_default_status_is_running() -> None:
    """Omitting ``status`` defaults to ``running`` (the documented default)."""
    content = _assemble_card_header(None, "Task")
    styles = [str(span.style) for span in content.spans]
    assert DARK_COLORS.card_running in styles


def test_assemble_card_header_returns_content_instance() -> None:
    """The helper returns a Textual ``Content`` object."""
    assert isinstance(_assemble_card_header(None, "x", status="running"), Content)


def test_assemble_card_header_body_span_uses_foreground_style() -> None:
    """The body portion is styled with the theme ``foreground`` color."""
    content = _assemble_card_header(None, "Body text", status="success")
    # Second span (if present) covers the body and uses foreground
    body_spans = [s for s in content.spans if s.start > 0]
    assert body_spans, "expected a body span after the prefix"
    assert str(body_spans[0].style) == DARK_COLORS.foreground


def test_assemble_card_header_with_custom_theme_colors_object() -> None:
    """A hand-built ``ThemeColors`` (merged override) drives the prefix tone.

    Uses ``ThemeColors.merged`` to swap ``card_running`` while keeping the
    rest of the dark palette, then asserts the tone selection logic honors
    the override. ``_assemble_card_header`` resolves colors via
    ``get_theme_colors(widget)``; with ``widget=None`` and no active app it
    falls back to ``DARK_COLORS``, so we verify ``_card_dot_tone`` directly
    with the custom colors object.
    """
    custom_running = "#FF00FF"
    custom_colors = ThemeColors.merged(DARK_COLORS, {"card_running": custom_running})
    from soothe_cli.display.card import _card_dot_tone

    assert _card_dot_tone("running", custom_colors) == custom_running
    assert _card_dot_tone("running", custom_colors) != DARK_COLORS.card_running


def test_glyph_sets_define_distinct_card_prefix_symbols() -> None:
    assert UNICODE_GLYPHS.tool_prefix == "●"
    assert UNICODE_GLYPHS.file_edit_prefix == "■"
    assert UNICODE_GLYPHS.subagent_prefix == "◆"
    assert ASCII_GLYPHS.tool_prefix == "[*]"
    assert ASCII_GLYPHS.file_edit_prefix == "[#]"
    assert ASCII_GLYPHS.subagent_prefix == "[S]"


def test_stream_cards_use_horizontal_inset_padding() -> None:
    """Agent cards share one 1-col inset so their prefix dots line up.

    Step, assistant (AI message) and clarification cards all use ``padding: 0 1``
    from the chat edges, keeping the dot column identical across card types. All
    three remain borderless.
    """
    step_css = CognitionStepMessage.DEFAULT_CSS
    assistant_css = AssistantMessage.DEFAULT_CSS
    clarification_css = StructuredAskUserWidget.DEFAULT_CSS
    assert "padding: 0 1;" in step_css
    assert "padding: 0 1;" in assistant_css
    assert "padding: 0 1;" in clarification_css
    assert "border-left:" not in step_css
    assert "border-left:" not in assistant_css
    assert "border-left:" not in clarification_css


def test_step_status_footer_uses_same_muted_base_as_tool_activity() -> None:
    """Footer status line shares $text-muted with tool/subagent activity panels."""
    step_css = CognitionStepMessage.DEFAULT_CSS
    assert "CognitionStepMessage .step-status" in step_css
    assert "color: $text-muted;" in step_css
