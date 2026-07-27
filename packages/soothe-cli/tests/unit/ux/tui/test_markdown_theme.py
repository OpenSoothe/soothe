"""Tests for TUI markdown theme registry and rendering."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe_cli.tui import theme
from soothe_cli.tui.markdown_theme import (
    DEFAULT_MARKDOWN_THEME,
    REGISTRY,
    ThemedMarkdownRenderer,
    _markdown_styles_from_colors,
    build_markdown,
    load_markdown_theme_preference,
    resolve_markdown_theme,
    resolve_markdown_theme_name,
)


def test_registry_contains_user_friendly_presets() -> None:
    assert set(REGISTRY) == {
        "match-app",
        "langchain",
        "langchain-light",
        "standard",
        "minimal",
    }
    assert REGISTRY["match-app"].label == "Match App Theme"
    assert REGISTRY["minimal"].label == "Minimal"


def test_resolve_markdown_theme_name_falls_back_to_default() -> None:
    assert resolve_markdown_theme_name("not-a-theme") == DEFAULT_MARKDOWN_THEME


def test_resolve_markdown_theme_name_uses_runtime_config() -> None:
    from soothe_cli.config.cli_config import CLIConfig
    from soothe_cli.config.loader import reset_runtime_config, set_runtime_config

    reset_runtime_config()
    set_runtime_config(CLIConfig(markdown_theme="minimal"))
    assert resolve_markdown_theme_name() == "minimal"
    reset_runtime_config()


def test_accent_recipe_uses_rainbow_headings() -> None:
    styles = _markdown_styles_from_colors(theme.DARK_COLORS, recipe="accent")
    from rich.color import Color

    expected = {
        "markdown.h1": theme.LC_BLUE,
        "markdown.h2": theme.LC_CYAN,
        "markdown.h3": theme.LC_PURPLE,
        "markdown.h4": theme.LC_GREEN,
        "markdown.h5": theme.LC_AMBER,
        "markdown.h6": theme.LC_PINK,
    }
    for key, hex_color in expected.items():
        color = styles[key].color
        assert color is not None
        assert color.triplet == Color.parse(hex_color).triplet

    link_color = styles["markdown.link"].color
    assert link_color is not None
    assert link_color.triplet == Color.parse(theme.LC_BLUE).triplet
    url_color = styles["markdown.link_url"].color
    assert url_color is not None
    assert url_color.triplet == Color.parse(theme.LC_CYAN).triplet


def test_accent_recipe_light_uses_darkened_rainbow() -> None:
    styles = _markdown_styles_from_colors(theme.LIGHT_COLORS, recipe="accent")
    from rich.color import Color

    h2 = styles["markdown.h2"].color
    assert h2 is not None
    assert h2.triplet == Color.parse(theme.LC_LIGHT_CYAN).triplet
    h3 = styles["markdown.h3"].color
    assert h3 is not None
    assert h3.triplet == Color.parse(theme.LC_LIGHT_PURPLE).triplet


def test_minimal_recipe_subdues_links() -> None:
    styles = _markdown_styles_from_colors(theme.DARK_COLORS, recipe="minimal")
    fg = theme.DARK_COLORS.foreground
    from rich.color import Color

    expected = Color.parse(fg)
    assert styles["markdown.link"].color is not None
    assert styles["markdown.link"].color.triplet == expected.triplet
    assert styles["markdown.h1"].color is not None
    assert styles["markdown.h1"].color.triplet == expected.triplet


def test_build_markdown_returns_themed_renderer() -> None:
    renderable = build_markdown("# Title\n\nBody")
    assert isinstance(renderable, ThemedMarkdownRenderer)


def test_load_markdown_theme_preference_missing_file() -> None:
    with patch(
        "soothe_cli.tui.model_config.DEFAULT_CONFIG_PATH",
        MagicMock(exists=lambda: False),
    ):
        assert load_markdown_theme_preference() == DEFAULT_MARKDOWN_THEME


def test_match_app_entry_has_no_fixed_colors() -> None:
    entry = resolve_markdown_theme("match-app")
    assert entry.colors is None
    assert entry.recipe == "accent"
