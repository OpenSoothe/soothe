"""Tests for slash-command Enter one-stage vs two-stage autocomplete."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe_cli.tui.command_registry import (
    COMMANDS,
    SLASH_COMMANDS,
    EnterAction,
    enter_action_for,
)
from soothe_cli.tui.widgets.autocomplete import CompletionResult, SlashCommandController


class _FakeView:
    """Minimal CompletionView that records replacements."""

    def __init__(self) -> None:
        self.replacements: list[tuple[int, int, str]] = []
        self.cleared = False
        self.rendered: list[tuple[str, str]] = []

    def render_completion_suggestions(
        self, suggestions: list[tuple[str, str]], selected_index: int
    ) -> None:
        del selected_index
        self.rendered = list(suggestions)

    def clear_completion_suggestions(self) -> None:
        self.cleared = True

    def replace_completion_range(self, start: int, end: int, replacement: str) -> None:
        self.replacements.append((start, end, replacement))


def _key(name: str) -> SimpleNamespace:
    return SimpleNamespace(key=name)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("/clear", EnterAction.EXECUTE),
        ("/quit", EnterAction.EXECUTE),
        ("/exit", EnterAction.EXECUTE),
        ("/help", EnterAction.EXECUTE),
        ("/model", EnterAction.EXECUTE),
        ("/tokens", EnterAction.EXECUTE),
        ("/autopilot", EnterAction.COMPLETE),
        ("/cron", EnterAction.COMPLETE),
        ("/plan", EnterAction.COMPLETE),
        ("/deep_research", EnterAction.COMPLETE),
        ("/browser_use", EnterAction.COMPLETE),
        ("/skill:weather", EnterAction.COMPLETE),
        ("/skills:weather", EnterAction.COMPLETE),
    ],
)
def test_enter_action_for_classification(command: str, expected: EnterAction) -> None:
    assert enter_action_for(command) == expected


def test_static_complete_commands_are_explicit() -> None:
    complete = {cmd.name for cmd in COMMANDS if cmd.enter_action == EnterAction.COMPLETE}
    assert complete == {
        "/academic_research",
        "/autopilot",
        "/browser_use",
        "/cron",
        "/deep_research",
        "/plan",
    }


def test_enter_on_clear_submits() -> None:
    view = _FakeView()
    controller = SlashCommandController(list(SLASH_COMMANDS), view)
    controller.on_text_changed("/cle", 4)
    assert controller.on_key(_key("enter"), "/cle", 4) == CompletionResult.SUBMIT
    assert view.replacements
    assert view.replacements[-1][2] == "/clear"


def test_enter_on_autopilot_completes_only() -> None:
    view = _FakeView()
    controller = SlashCommandController(list(SLASH_COMMANDS), view)
    controller.on_text_changed("/auto", 5)
    assert controller.on_key(_key("enter"), "/auto", 5) == CompletionResult.HANDLED
    assert view.replacements[-1][2] == "/autopilot"


def test_enter_on_skill_completes_only() -> None:
    view = _FakeView()
    commands = [("/skill:weather", "Weather skill", "weather"), *SLASH_COMMANDS]
    controller = SlashCommandController(commands, view)
    controller.on_text_changed("/skill:we", 9)
    assert controller.on_key(_key("enter"), "/skill:we", 9) == CompletionResult.HANDLED
    assert view.replacements[-1][2] == "/skill:weather"


def test_tab_never_submits_even_for_execute_commands() -> None:
    view = _FakeView()
    controller = SlashCommandController(list(SLASH_COMMANDS), view)
    controller.on_text_changed("/cle", 4)
    assert controller.on_key(_key("tab"), "/cle", 4) == CompletionResult.HANDLED
    assert view.replacements[-1][2] == "/clear"
