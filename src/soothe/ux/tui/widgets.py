"""Textual widgets for Soothe TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.geometry import Size
from textual.reactive import reactive
from textual.widgets import RichLog, Static, TextArea

if TYPE_CHECKING:
    from rich.console import RenderableType
    from textual.events import Key


class ConversationPanel(RichLog):
    """Scrollable chat history with markdown rendering.

    Supports Claude Code-style continuous event stream with colored dot prefixes.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create panel and initialize streaming line bookkeeping."""
        super().__init__(*args, **kwargs)
        # Index in ``lines`` where the last ``append_entry`` / streaming block began.
        # RichLog stores one Strip per terminal row; a single write() may add many rows.
        self._last_entry_line_start: int = 0

    def append_entry(self, renderable: RenderableType) -> None:
        """Append a new entry to the conversation log.

        Args:
            renderable: Rich renderable content to append (Text, Markdown, etc.).
        """
        if self._size_known:
            self._last_entry_line_start = len(self.lines)
        self.write(renderable)
        self.scroll_end(animate=False)

    def update_last_entry(self, renderable: RenderableType) -> None:
        """Update the last entry in the conversation log (for streaming updates).

        Removes every terminal row belonging to the last logical entry, then writes
        the new renderable. Required because ``RichLog.write`` expands one renderable
        to multiple internal lines.

        Args:
            renderable: Rich renderable content to replace the last entry with.
        """
        start = min(self._last_entry_line_start, len(self.lines))
        while len(self.lines) > start:
            self.lines.pop()
        self._line_cache.clear()
        self._widest_line_width = max((s.cell_length for s in self.lines), default=0)
        self.virtual_size = Size(self._widest_line_width, len(self.lines))
        self.refresh()
        self.write(renderable)
        self.scroll_end(animate=False)

    def clear(self) -> RichLog:
        """Clear log and streaming entry bookkeeping."""
        self._last_entry_line_start = 0
        return super().clear()

    def append_separator(self) -> None:
        """Append a blank line separator between conversation turns."""
        self.write(Text(""))
        self.scroll_end(animate=False)

    async def _on_key(self, event: Key) -> None:
        """Handle key events, allowing Ctrl+D to trigger detach."""
        if event.key == "ctrl+d":
            event.prevent_default()
            # Find the app and call its detach action
            from soothe.ux.tui.app import SootheApp

            app = self.app
            if isinstance(app, SootheApp):
                await app.action_detach()
            return
        # Let parent RichLog handle all other keys
        await super()._on_key(event)


class PlanTree(Static):
    """Plan tree display with merged activity info, toggleable."""

    async def _on_key(self, event: Key) -> None:
        """Handle key events, allowing Ctrl+D to trigger detach."""
        if event.key == "ctrl+d":
            event.prevent_default()
            # Find the app and call its detach action
            from soothe.ux.tui.app import SootheApp

            app = self.app
            if isinstance(app, SootheApp):
                await app.action_detach()
            return
        # Let parent Static handle all other keys
        await super()._on_key(event)


class InfoBar(Static):
    """Compact status bar showing thread, events, subagent status."""


class ChatInput(TextArea):
    """Chat input with UP/DOWN arrow key history navigation and multi-line support.

    Enter submits the message. Shift+Enter inserts a newline.
    Auto-expands from 1 line up to 50% of viewport height based on content.
    When content exceeds max height, scrollbar appears automatically.

    History Navigation:
    - UP arrow: Shows newest message first, then older messages on subsequent presses
    - DOWN arrow: Shows newer messages, returns to current input at newest
    """

    MAX_HEIGHT = 50  # Maximum height in lines (CSS max-height: 50vh handles actual limit)
    current_height: reactive[int] = reactive(1)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the chat input with history navigation.

        Args:
            **kwargs: Additional keyword arguments passed to TextArea.
        """
        # Override theme to ensure text visibility
        # Use 'vscode_dark' for dark mode compatibility, or no theme for plain text
        if "theme" not in kwargs:
            kwargs["theme"] = "vscode_dark"
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_index: int = -1
        self._saved_input: str = ""
        self._updating_height = False

    def _calculate_line_count(self) -> int:
        """Calculate the number of lines needed for current text.

        Returns:
            Number of lines (1 to MAX_HEIGHT) needed to display the current text.
        """
        if not self.text:
            return 1
        line_count = len(self.text.split("\n"))
        return min(max(1, line_count), self.MAX_HEIGHT)

    def watch_text(self) -> None:
        """React to text changes and adjust height."""
        if self._updating_height:
            return

        new_height = self._calculate_line_count()
        if new_height != self.current_height:
            self.current_height = new_height

    def watch_current_height(self, old_height: int, new_height: int) -> None:
        """Update CSS height when current_height changes.

        Args:
            old_height: Previous height value.
            new_height: New height value.
        """
        if old_height != new_height:
            self.styles.height = new_height

    @property
    def input_history(self) -> list[str]:
        """Get input history (oldest first).

        Returns:
            List of history entries.
        """
        return list(self._history)

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

    def clear(self) -> None:
        """Clear the input text and reset height."""
        self._updating_height = True
        try:
            self.text = ""
            self.current_height = 1
        finally:
            self._updating_height = False

    async def _on_key(self, event: Key) -> None:
        """Handle key events for history navigation and submission."""
        # Ctrl+D for detach
        if event.key == "ctrl+d":
            event.stop()
            event.prevent_default()
            from soothe.ux.tui.app import SootheApp

            app = self.app
            if isinstance(app, SootheApp):
                await app.action_detach()
            return

        # Ctrl+Enter handling - insert newline (works in most terminals)
        if event.key == "ctrl+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return

        # Shift+Enter handling - also insert newline (for terminals that support it)
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return

        # Ctrl+J handling - iTerm2 sends this for Shift+Enter (line feed character)
        if event.key == "ctrl+j":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return

        # Enter key handling (plain Enter only)
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            from soothe.ux.tui.app import SootheApp

            app = self.app
            if isinstance(app, SootheApp):
                await app.submit_chat_input()
            return

        # Up arrow for history navigation (newest first, then older).
        # Must stop propagation: TextArea binds "up" to cursor_up; if the event bubbles,
        # the binding runs after we set ``text`` and breaks history recall.
        if event.key == "up" and self.cursor_at_first_line:
            event.prevent_default()
            if not self._history:
                return
            if self._history_index == -1:
                # First press: save current input and start at newest message (index 0)
                self._saved_input = self.text
                self._history_index = 0
            elif self._history_index < len(self._history) - 1:
                # Navigate to older messages
                self._history_index += 1
            # Map index to reversed history: 0 = newest, 1 = second newest, etc.
            self.text = self._history[-(self._history_index + 1)]
            self.cursor_location = (0, 0)
            event.stop()
            return

        # Down arrow for history navigation (newer messages, then back to current)
        if event.key == "down" and self.cursor_at_last_line:
            event.prevent_default()
            if self._history_index == -1:
                # No history active, do nothing
                return
            if self._history_index > 0:
                # Navigate to newer messages
                self._history_index -= 1
                self.text = self._history[-(self._history_index + 1)]
            else:
                # At newest message, return to current input
                self._history_index = -1
                self.text = self._saved_input
            self.cursor_location = (0, 0)
            event.stop()
            return

        # Let parent TextArea handle all other keys
        await super()._on_key(event)
