"""Regression tests for dynamic theme color resolution.

Covers ``get_theme_colors`` / ``_colors_from_textual_theme`` for the built-in
Textual themes (``custom=False``). These themes resolve colors dynamically from
the live Textual theme rather than returning a pre-built preset, so every
``ThemeColors`` field must be supplied at that construction site.

The original regression (loop e1b7): ``card_running`` and ``card_running_muted``
were added to the dataclass and the dark/light presets but omitted from the
dynamic constructor, raising ``TypeError`` on every call and breaking the
synthesis card's final markdown render — the "summary card still flashing,
not finished" symptom.
"""

from __future__ import annotations

import pytest
from textual.app import App

from soothe_cli.tui import theme
from soothe_cli.tui.theme import ThemeColors, ThemeEntry


class _HarnessApp(App[None]):
    """Minimal app whose theme can be swapped for dynamic resolution."""

    def __init__(self, theme_name: str) -> None:
        super().__init__()
        # Textual registers built-in themes by name on the App class.
        if theme_name not in self.available_themes:
            pytest.skip(f"theme {theme_name!r} not available in this Textual build")
        self._theme_name = theme_name

    def compose(self) -> None:  # pragma: no cover - nothing to render
        yield from ()

    def on_mount(self) -> None:
        self.theme = self._theme_name


def _builtin_theme_names() -> list[str]:
    """Names of registered themes that take the dynamic (non-custom) path."""
    return [name for name, entry in ThemeEntry.REGISTRY.items() if not entry.custom]


@pytest.mark.asyncio
@pytest.mark.parametrize("theme_name", _builtin_theme_names())
async def test_get_theme_colors_dynamic_path_supplies_all_fields(
    theme_name: str,
) -> None:
    """Every built-in theme must resolve a complete ``ThemeColors``.

    A ``TypeError`` here means a required field was added to ``ThemeColors``
    without updating ``_colors_from_textual_theme`` — the e1b7 regression.
    """
    async with _HarnessApp(theme_name).run_test() as pilot:
        colors = theme.get_theme_colors(pilot.app)

    assert isinstance(colors, ThemeColors)
    # The two fields missed in the original regression must be valid hex.
    assert colors.card_running.startswith("#")
    assert colors.card_running_muted.startswith("#")
    assert colors.card_running != colors.card_running_muted


def test_all_themecolors_constructor_sites_pass_required_fields() -> None:
    """Static guard: every ``ThemeColors(...)`` call passes all required fields.

    Catches the whole class of regression — a field added to the dataclass but
    missed at one constructor site — without needing a live Textual app.
    """
    import ast
    from pathlib import Path

    required = {f.name for f in ThemeColors.__dataclass_fields__.values()}
    theme_path = Path(theme.__file__)
    tree = ast.parse(theme_path.read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ThemeColors"):
            continue
        passed = {kw.arg for kw in node.keywords if kw.arg}
        missing = required - passed
        assert not missing, (
            f"ThemeColors() at {theme_path.name}:{node.lineno} is missing "
            f"required fields: {sorted(missing)}"
        )
