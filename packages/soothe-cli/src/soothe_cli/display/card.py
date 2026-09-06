"""Card prefix glyph, header assembly, and body gutter alignment shared by TUI card widgets.

These helpers encode card *appearance* (prefix tone, glyph prefix, gutter
alignment, header assembly). They are intentionally free of Textual widget
lifecycle concerns; refresh throttling and animation visibility stay in the
TUI layer (``tui/widgets/messages/_helpers.py``).
"""

from __future__ import annotations

from textual.content import Content

from soothe_cli.display import theme
from soothe_cli.display.preview_limits import STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD
from soothe_cli.display.tool_display import display_width
from soothe_cli.settings import get_glyphs

# Preview limits imported from preview_limits module
_STEP_TOOL_PREVIEW_ROWS = STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD
"""Collapsed step/task activity preview shows this many rows."""


def _card_dot_tone(
    status: str,
    colors: theme.ThemeColors,
    *,
    accent: str | None = None,
    spinner_position: int = 0,
    animate_running: bool = False,
) -> str:
    """Return a Textual style string for a card prefix dot from lifecycle status."""
    phase = (status or "pending").strip().lower()
    if phase in ("success", "done", "completed"):
        return colors.card_success
    if phase in ("error", "failed", "interrupted"):
        return colors.card_error
    if phase == "running":
        # Yellow flash on every other spinner tick; dim amber in between.
        if animate_running and spinner_position % 2:
            return colors.card_running_muted
        return colors.card_running
    if phase in ("queued", "pending", "continue", "replan"):
        return colors.muted
    if accent:
        return accent
    return colors.muted


def _card_dot_prefix_content(
    widget: object,
    status: str,
    *,
    accent: str | None = None,
    glyph_override: str | None = None,
    spinner_position: int = 0,
    animate_running: bool = False,
) -> Content:
    """Build a stateful colored card-prefix glyph."""
    try:
        colors = theme.get_theme_colors(widget)
    except Exception:  # noqa: BLE001
        colors = theme.DARK_COLORS
    glyph = glyph_override or get_glyphs().tool_prefix
    tone = _card_dot_tone(
        status,
        colors,
        accent=accent,
        spinner_position=spinner_position,
        animate_running=animate_running,
    )
    return Content.styled(f"{glyph} ", tone)


def _card_prefix_width(glyph_override: str | None = None) -> int:
    """Display width of the card header prefix (the dot/glyph plus one space).

    Every body line and tree-branch line must left-align at the right side of
    this prefix, so card content never extends left of the header text. In
    ASCII mode the prefix is ``"[*] "`` (4 cols) while the tree gutter glyph
    ``"L"`` is only 1 col; the body gutter is padded to close that gap.
    """
    glyph = glyph_override or get_glyphs().tool_prefix
    return display_width(glyph) + 1  # +1 for the trailing space


def _card_body_gutter(glyph_override: str | None = None) -> str:
    """Body/tree-branch gutter aligned to the right of the card prefix dot.

    The tree glyph (``⎿`` / ``L``) stays at the left edge of the prefix column;
    trailing spaces pad the gutter so its display width equals the header
    prefix width (``glyph + " "``). That makes every card line and tree branch
    start at the right side of the dot space.
    """
    g = get_glyphs()
    prefix_width = _card_prefix_width(glyph_override)
    glyph_w = display_width(g.output_prefix)
    pad = max(0, prefix_width - glyph_w)
    return f"{g.output_prefix}{' ' * pad}"


def _card_item_indent(
    extra_indent: int = 0,
    *,
    glyph_override: str | None = None,
) -> str:
    """Plain-space indent for activity item rows (no tree glyph).

    Item rows under a section (tool rows, todo items, notes, "+N more") sit at
    the card header prefix width plus ``extra_indent`` columns — aligned with
    the right side of the dot space so they never extend left of the title
    text, and indented under the section's ``⎿`` label.
    """
    prefix_width = _card_prefix_width(glyph_override)
    return f"{' ' * max(0, prefix_width + extra_indent)}"


def _assemble_card_header(
    widget: object,
    body_part: str,
    *,
    status: str = "running",
    accent: str | None = None,
    glyph_override: str | None = None,
    spinner_position: int = 0,
    animate_running: bool = False,
) -> Content:
    """Build a card title: stateful prefix glyph plus foreground body (no bold).

    Used for Goal, Plan, Step, and tool (including Task) headers. The glyph color
    reflects lifecycle status; body lines below use the tree gutter returned by
    :func:`_card_body_gutter`, which aligns to the right of the card prefix dot.

    Args:
        widget: Mounted widget (or any object accepted by ``get_theme_colors``).
        body_part: Header text (goal, step description, etc.).
        status: Card lifecycle phase for glyph color/shape.
        accent: Optional override tone for the glyph (e.g. skill/error accent).
        spinner_position: Toggles gray flash while ``animate_running`` is true.
        animate_running: Flash the glyph gray while running (step/task/assistant cards).

    Returns:
        Assembled ``Content`` for a ``Static`` header.
    """
    try:
        colors = theme.get_theme_colors(widget)
    except Exception:  # noqa: BLE001
        colors = theme.DARK_COLORS
    return Content.assemble(
        _card_dot_prefix_content(
            widget,
            status,
            accent=accent,
            glyph_override=glyph_override,
            spinner_position=spinner_position,
            animate_running=animate_running,
        ),
        Content.styled(body_part, colors.foreground),
    )
