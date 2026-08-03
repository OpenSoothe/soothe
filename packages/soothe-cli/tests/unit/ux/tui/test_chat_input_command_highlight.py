"""Tests for slash-command token highlighting inside the chat input box."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from textual.app import App, ComposeResult

from soothe_cli.tui import theme
from soothe_cli.tui.input import command_token_span
from soothe_cli.tui.widgets.chat_input import ChatInput, ChatTextArea

if TYPE_CHECKING:
    from pathlib import Path


class _ChatInputHarnessApp(App[None]):
    """Minimal app hosting a single `ChatInput`."""

    def __init__(self, cwd: Path) -> None:
        super().__init__()
        self._cwd = cwd

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Supply the app-specific CSS variables `ChatInput` styling needs."""
        return theme.get_css_variable_defaults(colors=theme.get_theme_colors(self))

    def compose(self) -> ComposeResult:
        yield ChatInput(cwd=self._cwd, history_file=self._cwd / "history.jsonl")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("help", (0, 4)),
        ("/help", (0, 5)),
        ("skill:diagnose-soothe run", (0, 21)),
        ("model gpt-5", (0, 5)),
        ("", (0, 0)),
        ("/", (0, 0)),
        ("  leading", (0, 0)),
    ],
)
def test_command_token_span(line: str, expected: tuple[int, int]) -> None:
    """The span covers the first token, including a transient leading slash."""
    assert command_token_span(line) == expected


@pytest.mark.asyncio
async def test_command_mode_highlights_only_the_command_token(tmp_path: Path) -> None:
    """Command mode paints the leading token in the command accent color."""
    async with _ChatInputHarnessApp(tmp_path).run_test() as pilot:
        chat = pilot.app.query_one(ChatInput)
        text_area = pilot.app.query_one(ChatTextArea)
        chat.mode = "command"
        text_area.text = "help me now"
        await pilot.pause()

        expected_style = f"bold {theme.get_theme_colors(chat).mode_command}"
        assert [(s.start, s.end, s.style) for s in text_area.get_line(0).spans] == [
            (0, 4, expected_style)
        ]


@pytest.mark.asyncio
async def test_normal_mode_leaves_input_unstyled(tmp_path: Path) -> None:
    """Plain prose must not pick up the command accent."""
    async with _ChatInputHarnessApp(tmp_path).run_test() as pilot:
        text_area = pilot.app.query_one(ChatTextArea)
        text_area.text = "help me now"
        await pilot.pause()

        assert text_area.get_line(0).spans == []


@pytest.mark.asyncio
async def test_leaving_command_mode_clears_the_highlight(tmp_path: Path) -> None:
    """Exiting command mode repaints even though the text did not change."""
    async with _ChatInputHarnessApp(tmp_path).run_test() as pilot:
        chat = pilot.app.query_one(ChatInput)
        text_area = pilot.app.query_one(ChatTextArea)
        chat.mode = "command"
        text_area.text = "help"
        await pilot.pause()
        assert text_area.get_line(0).spans

        chat.mode = "normal"
        await pilot.pause()

        assert text_area.get_line(0).spans == []


@pytest.mark.asyncio
async def test_highlight_skips_continuation_lines(tmp_path: Path) -> None:
    """Only the first line carries the command token."""
    async with _ChatInputHarnessApp(tmp_path).run_test() as pilot:
        chat = pilot.app.query_one(ChatInput)
        text_area = pilot.app.query_one(ChatTextArea)
        chat.mode = "command"
        text_area.text = "help\nmore"
        await pilot.pause()

        assert text_area.get_line(1).spans == []
