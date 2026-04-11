"""Modal screens for Soothe TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual import on
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static

from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from soothe.core.runner import SootheRunner


class ThreadSelectionModal(ModalScreen[str | None]):
    """Modal screen for selecting a thread to resume.

    Returns:
        Selected thread ID, or None if cancelled.
    """

    CSS = """
    ThreadSelectionModal {
        align: center middle;
    }

    #modal-container {
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        width: 80;
        height: 30;
    }

    #modal-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #thread-list {
        height: 20;
        margin-bottom: 1;
    }

    #button-row {
        align: center middle;
        height: 3;
    }

    Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        runner: SootheRunner,
        **kwargs: Any,
    ) -> None:
        """Initialize the thread selection modal.

        Args:
            runner: SootheRunner instance for fetching threads.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(**kwargs)
        self._runner = runner
        self._threads: list[dict] = []

    def compose(self) -> ComposeResult:
        """Build the modal layout."""
        with Container(id="modal-container"):
            yield Static("Resume Thread", id="modal-title")
            from textual.widgets import OptionList

            yield OptionList(id="thread-list")
            with Container(id="button-row"):
                yield Button("Cancel", variant="default", id="cancel-btn")

    async def on_mount(self) -> None:
        """Load threads when modal mounts."""
        try:
            threads = await self._runner.list_threads()
            # Filter to active threads only and sort by most recent
            self._threads = sorted(
                [t for t in threads if t.get("status") == "active"],
                key=lambda x: x.get("updated_at", ""),
                reverse=True,
            )

            thread_list = self.query_one("#thread-list", OptionList)
            thread_list.clear_options()

            if not self._threads:
                thread_list.add_option("No active threads found")
                return

            # Add thread options with metadata
            for thread in self._threads[:20]:  # Limit to 20 most recent
                tid = thread.get("thread_id", "?")
                created = preview_first(str(thread.get("created_at", "?")), 10)
                updated = preview_first(str(thread.get("updated_at", "?")), 19)

                option_text = f"{tid}  |  {updated}  |  Created: {created}"
                thread_list.add_option(option_text)

        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("Failed to load threads")
            thread_list = self.query_one("#thread-list", OptionList)
            thread_list.clear_options()
            thread_list.add_option(f"Error loading threads: {exc}")

    @on(OptionList.OptionSelected, "#thread-list")
    def on_thread_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle thread selection."""
        if not self._threads or event.option_index >= len(self._threads):
            return

        selected_thread = self._threads[event.option_index]
        thread_id = selected_thread.get("thread_id")
        if thread_id:
            self.dismiss(thread_id)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        """Handle cancel button press."""
        self.dismiss(None)
