"""Textual widgets for Soothe TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Input, RichLog, Static

if TYPE_CHECKING:
    from textual.events import Key


class ConversationPanel(RichLog):
    """Scrollable chat history with markdown rendering."""


class PlanTree(Static):
    """Plan tree display with merged activity info, toggleable."""


class InfoBar(Static):
    """Compact status bar showing thread, events, subagent status."""


class ChatInput(Input):
    """Chat input with UP/DOWN arrow key history navigation."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the chat input with history navigation.

        Args:
            **kwargs: Additional keyword arguments passed to Input.
        """
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_index: int = -1
        self._saved_input: str = ""

    def set_history(self, history: list[str]) -> None:
        """Load input history (oldest first)."""
        self._history = list(history)
        self._history_index = -1

    def add_to_history(self, text: str) -> None:
        """Append a new entry to the input history."""
        stripped = text.strip()
        if stripped and (not self._history or self._history[-1] != stripped):
            self._history.append(stripped)
        self._history_index = -1

    async def _on_key(self, event: Key) -> None:
        if event.key == "up":
            event.prevent_default()
            if not self._history:
                return
            if self._history_index == -1:
                self._saved_input = self.value
                self._history_index = len(self._history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            self.value = self._history[self._history_index]
            self.cursor_position = len(self.value)
        elif event.key == "down":
            event.prevent_default()
            if self._history_index == -1:
                return
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                self.value = self._history[self._history_index]
            else:
                self._history_index = -1
                self.value = self._saved_input
            self.cursor_position = len(self.value)
        elif event.key == "ctrl+d":
            # Let the app-level binding handle detach by not preventing default
            await super()._on_key(event)
        else:
            # Let parent Input handle all other keys normally
            await super()._on_key(event)
