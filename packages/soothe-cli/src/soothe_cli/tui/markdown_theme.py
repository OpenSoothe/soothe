"""Named markdown appearance presets for TUI Rich rendering.

Display labels and stable IDs follow the same pattern as ``theme.ThemeEntry``.
Users configure via ``--markdown-theme`` or ``ui.markdown_theme`` in the
**CLI client** preferences file ``~/SOOTHE_HOME/config/cli.yml`` (TUI only —
not the daemon ``nano.yml`` / ``soothe.yml``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from soothe_cli.tui import theme

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

DEFAULT_MARKDOWN_THEME = "match-app"
"""Registry key used when no preference is saved."""

StyleRecipe = Literal["accent", "standard", "minimal"]

# TUI theme name → Pygments theme (internal; not user-facing).
_TUI_TO_PYGMENTS: dict[str, str] = {
    "langchain": "monokai",
    "langchain-light": "default",
    "textual-dark": "monokai",
    "textual-light": "default",
    "textual-ansi": "default",
    "atom-one-dark": "one-dark",
    "atom-one-light": "default",
    "catppuccin-frappe": "monokai",
    "catppuccin-latte": "default",
    "catppuccin-macchiato": "monokai",
    "catppuccin-mocha": "monokai",
    "dracula": "dracula",
    "flexoki": "monokai",
    "gruvbox": "gruvbox-dark",
    "monokai": "monokai",
    "nord": "nord",
    "rose-pine": "monokai",
    "rose-pine-dawn": "default",
    "rose-pine-moon": "monokai",
    "solarized-dark": "solarized-dark",
    "solarized-light": "solarized-light",
    "tokyo-night": "monokai",
}
_DEFAULT_DARK_CODE_THEME = "monokai"
_DEFAULT_LIGHT_CODE_THEME = "default"


@dataclass(frozen=True, slots=True)
class MarkdownThemeEntry:
    """Metadata for a registered markdown appearance preset."""

    label: str
    """Human-readable label for CLI help."""

    description: str
    """One-line description."""

    dark: bool
    """Default polarity for fixed palettes and code highlighting."""

    code_theme: str
    """Pygments theme for fenced code blocks (internal)."""

    recipe: StyleRecipe
    """Element style recipe."""

    colors: theme.ThemeColors | None = None
    """Fixed palette; ``None`` means resolve from the active TUI theme at render time."""


def _builtin_markdown_themes() -> dict[str, MarkdownThemeEntry]:
    return {
        "match-app": MarkdownThemeEntry(
            label="Match App Theme",
            description="Markdown colors follow your current terminal theme",
            dark=True,
            code_theme=_DEFAULT_DARK_CODE_THEME,
            recipe="accent",
            colors=None,
        ),
        "langchain": MarkdownThemeEntry(
            label="LangChain",
            description="LangChain brand colors (dark)",
            dark=True,
            code_theme="monokai",
            recipe="accent",
            colors=theme.DARK_COLORS,
        ),
        "langchain-light": MarkdownThemeEntry(
            label="LangChain Light",
            description="LangChain brand colors (light)",
            dark=False,
            code_theme="default",
            recipe="accent",
            colors=theme.LIGHT_COLORS,
        ),
        "standard": MarkdownThemeEntry(
            label="Standard",
            description="Balanced default markdown styling",
            dark=True,
            code_theme=_DEFAULT_DARK_CODE_THEME,
            recipe="standard",
            colors=theme.DARK_COLORS,
        ),
        "minimal": MarkdownThemeEntry(
            label="Minimal",
            description="Low visual noise; body text first",
            dark=True,
            code_theme=_DEFAULT_DARK_CODE_THEME,
            recipe="minimal",
            colors=theme.DARK_COLORS,
        ),
    }


REGISTRY: Mapping[str, MarkdownThemeEntry] = MappingProxyType(_builtin_markdown_themes())


def markdown_theme_help() -> str:
    """Comma-separated preset IDs for CLI help text."""
    return ", ".join(sorted(REGISTRY))


def load_markdown_theme_preference() -> str:
    """Load saved markdown theme from the CLI TUI preferences file."""
    import yaml

    from soothe_cli.tui.model_config import resolve_cli_config_path

    try:
        config_path = resolve_cli_config_path()
        if not config_path.exists():
            return DEFAULT_MARKDOWN_THEME
        with config_path.open("rb") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, PermissionError, OSError) as exc:
        logger.warning("Could not read config for markdown theme preference: %s", exc)
        return DEFAULT_MARKDOWN_THEME

    name = (data or {}).get("ui", {}).get("markdown_theme")
    if isinstance(name, str) and name in REGISTRY:
        return name
    if isinstance(name, str):
        logger.warning(
            "Unknown markdown theme '%s' in config; falling back to default",
            name,
        )
    return DEFAULT_MARKDOWN_THEME


def resolve_markdown_theme_name(name: str | None = None) -> str:
    """Resolve a registry key from explicit name, runtime config, or disk preference."""
    if name is not None:
        candidate = name
    else:
        try:
            from soothe_cli.config.loader import load_config

            candidate = load_config().markdown_theme
        except Exception:  # noqa: BLE001
            candidate = load_markdown_theme_preference()

    if candidate in REGISTRY:
        return candidate
    logger.warning(
        "Unknown markdown theme '%s'; falling back to %s",
        candidate,
        DEFAULT_MARKDOWN_THEME,
    )
    return DEFAULT_MARKDOWN_THEME


def resolve_markdown_theme(name: str | None = None) -> MarkdownThemeEntry:
    """Return the resolved ``MarkdownThemeEntry`` for ``name`` or runtime config."""
    return REGISTRY[resolve_markdown_theme_name(name)]


def _resolve_app_theme_name(widget_or_app: object | None) -> str | None:
    try:
        app = (
            widget_or_app.app  # type: ignore[attr-defined]
            if hasattr(type(widget_or_app), "app")
            else widget_or_app
        )
        theme_name = getattr(app, "theme", None)
        return theme_name if isinstance(theme_name, str) else None
    except Exception:  # noqa: BLE001
        return None


def _code_theme_for_entry(
    entry: MarkdownThemeEntry,
    widget_or_app: object | None,
    colors: theme.ThemeColors,
) -> str:
    if entry.colors is None:
        tui_name = _resolve_app_theme_name(widget_or_app)
        if tui_name and tui_name in _TUI_TO_PYGMENTS:
            return _TUI_TO_PYGMENTS[tui_name]
        return (
            _DEFAULT_DARK_CODE_THEME if colors.background < "#888888" else _DEFAULT_LIGHT_CODE_THEME
        )
    return entry.code_theme


def _colors_for_entry(
    entry: MarkdownThemeEntry,
    widget_or_app: object | None,
) -> theme.ThemeColors:
    if entry.colors is None:
        try:
            return theme.get_theme_colors(widget_or_app)
        except Exception:  # noqa: BLE001
            return theme.DARK_COLORS if entry.dark else theme.LIGHT_COLORS
    return entry.colors


def _is_dark_palette(colors: theme.ThemeColors) -> bool:
    """Heuristic: dark themes use a background darker than mid-gray."""
    return colors.background < "#888888"


def _heading_rainbow(colors: theme.ThemeColors) -> tuple[str, str, str, str, str, str]:
    """Return H1–H6 colors as a soft rainbow ladder.

    Order mirrors the Tokyo Night–inspired brand palette visible in card
    chrome (blue title → cyan identity → purple subtext), then continues
    through green / amber / pink so deeper heading levels stay distinct.
    """
    cyan = theme.LC_CYAN if _is_dark_palette(colors) else theme.LC_LIGHT_CYAN
    return (
        colors.primary,  # H1 — blue
        cyan,  # H2 — cyan
        colors.secondary,  # H3 — purple
        colors.accent,  # H4 — green
        colors.warning,  # H5 — amber
        colors.error,  # H6 — pink
    )


def _markdown_styles_from_colors(
    colors: theme.ThemeColors,
    *,
    recipe: StyleRecipe,
) -> dict[str, Any]:
    from rich.style import Style

    if recipe == "minimal":
        return {
            "markdown.paragraph": Style(color=colors.foreground),
            "markdown.h1": Style(color=colors.foreground, bold=True),
            "markdown.h2": Style(color=colors.foreground, bold=True),
            "markdown.h3": Style(color=colors.foreground, bold=True),
            "markdown.h4": Style(color=colors.foreground, bold=True),
            "markdown.h5": Style(color=colors.foreground, bold=True),
            "markdown.h6": Style(color=colors.muted, bold=True),
            "markdown.em": Style(color=colors.foreground, italic=True),
            "markdown.strong": Style(color=colors.foreground, bold=True),
            "markdown.s": Style(color=colors.muted, strike=True),
            "markdown.code_inline": Style(color=colors.muted),
            "markdown.code_block": Style(color=colors.foreground),
            "markdown.block_quote": Style(color=colors.muted),
            "markdown.hr": Style(color=colors.card_border),
            "markdown.link": Style(color=colors.foreground),
            "markdown.link_url": Style(color=colors.foreground),
            "markdown.list": Style(color=colors.foreground),
            "markdown.item": Style(color=colors.foreground),
            "markdown.item.bullet": Style(color=colors.muted),
            "markdown.item.number": Style(color=colors.muted),
            "markdown.table.border": Style(color=colors.card_border),
            "markdown.table.header": Style(color=colors.foreground, bold=True),
            "markdown.table.cell": Style(color=colors.foreground),
        }

    h1, h2, h3, h4, h5, h6 = _heading_rainbow(colors)
    cyan = h2

    if recipe == "standard":
        return {
            "markdown.paragraph": Style(color=colors.foreground),
            "markdown.h1": Style(color=h1, bold=True),
            "markdown.h2": Style(color=h2, bold=True),
            "markdown.h3": Style(color=h3, bold=True),
            "markdown.h4": Style(color=h4, bold=True),
            "markdown.h5": Style(color=h5, bold=True),
            "markdown.h6": Style(color=h6, bold=True),
            "markdown.em": Style(color=colors.foreground, italic=True),
            "markdown.strong": Style(color=colors.foreground, bold=True),
            "markdown.s": Style(color=colors.muted, strike=True),
            "markdown.code_inline": Style(color=colors.secondary, bgcolor=colors.panel),
            "markdown.code_block": Style(color=colors.foreground),
            "markdown.block_quote": Style(color=colors.muted, italic=True),
            "markdown.hr": Style(color=colors.card_border),
            "markdown.link": Style(color=colors.primary, underline=True),
            "markdown.link_url": Style(color=cyan, underline=True),
            "markdown.list": Style(color=colors.foreground),
            "markdown.item": Style(color=colors.foreground),
            "markdown.item.bullet": Style(color=cyan),
            "markdown.item.number": Style(color=colors.secondary),
            "markdown.table.border": Style(color=colors.card_border),
            "markdown.table.header": Style(color=colors.primary, bold=True),
            "markdown.table.cell": Style(color=colors.foreground),
        }

    # accent (match-app, langchain*) — full rainbow headings + soft accents
    return {
        "markdown.paragraph": Style(color=colors.foreground),
        "markdown.h1": Style(color=h1, bold=True),
        "markdown.h2": Style(color=h2, bold=True),
        "markdown.h3": Style(color=h3, bold=True),
        "markdown.h4": Style(color=h4, bold=True),
        "markdown.h5": Style(color=h5, bold=True),
        "markdown.h6": Style(color=h6, bold=True),
        "markdown.em": Style(color=colors.secondary, italic=True),
        "markdown.strong": Style(color=colors.foreground, bold=True),
        "markdown.s": Style(color=colors.muted, strike=True),
        "markdown.code_inline": Style(color=cyan, bgcolor=colors.panel),
        "markdown.code_block": Style(color=colors.foreground),
        "markdown.block_quote": Style(color=colors.secondary, italic=True),
        "markdown.hr": Style(color=colors.card_border),
        "markdown.link": Style(color=colors.primary, underline=True),
        "markdown.link_url": Style(color=cyan, underline=True),
        "markdown.list": Style(color=colors.foreground),
        "markdown.item": Style(color=colors.foreground),
        "markdown.item.bullet": Style(color=cyan),
        "markdown.item.number": Style(color=colors.secondary),
        "markdown.table.border": Style(color=colors.card_border),
        "markdown.table.header": Style(color=h1, bold=True),
        "markdown.table.cell": Style(color=colors.foreground),
    }


class ThemedMarkdownRenderer:
    """Rich ``Markdown`` wrapper that applies a ``MarkdownThemeEntry`` at render time."""

    def __init__(
        self,
        markup: str,
        *,
        entry: MarkdownThemeEntry,
        colors: theme.ThemeColors,
        code_theme: str,
    ) -> None:
        from rich.markdown import Markdown as RichMarkdown

        self._markdown = RichMarkdown(markup, code_theme=code_theme)
        self._entry = entry
        self._colors = colors

    def __rich_console__(self, console: Any, options: Any) -> Any:
        from rich.console import Console as RichConsole
        from rich.theme import Theme as RichTheme

        width = options.max_width or console.width
        themed_console = RichConsole(
            theme=RichTheme(
                styles=_markdown_styles_from_colors(self._colors, recipe=self._entry.recipe)
            ),
            width=width if width else None,
            legacy_windows=console.legacy_windows,
            color_system=console.color_system,
        )
        yield from self._markdown.__rich_console__(themed_console, options)


def build_markdown(content: str, widget_or_app: object | None = None) -> ThemedMarkdownRenderer:
    """Build markdown styled with the active markdown theme preset."""
    entry = resolve_markdown_theme()
    colors = _colors_for_entry(entry, widget_or_app)
    code_theme = _code_theme_for_entry(entry, widget_or_app, colors)
    return ThemedMarkdownRenderer(
        content,
        entry=entry,
        colors=colors,
        code_theme=code_theme,
    )
