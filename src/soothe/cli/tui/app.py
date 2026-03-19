"""Textual-based TUI for Soothe (RFC-0003 revised).

Three-row layout:
  Row 1 -- Conversation (left) | Plan + Activity (right)
  Row 2 -- Info bar (thread, events, subagent status)
  Row 3 -- Chat input with UP/DOWN history navigation

Connects to the Soothe daemon over a Unix domain socket for event
streaming and user input. When the daemon is not already running,
``run_textual_tui`` starts it as an external process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import sys
from typing import Any, ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header, Input

from soothe.cli.daemon import DaemonClient, SootheDaemon, socket_path
from soothe.cli.progress_verbosity import should_show
from soothe.cli.slash_commands import parse_autonomous_command
from soothe.cli.thread_logger import ThreadLogger
from soothe.cli.tui.event_processors import process_daemon_event
from soothe.cli.tui.state import TuiState
from soothe.cli.tui.widgets import ActivityPanel, ChatInput, ConversationPanel, InfoBar, PlanPanel
from soothe.cli.tui_shared import render_plan_tree
from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class SootheApp(App):
    """Textual application for the Soothe TUI."""

    TITLE = "Soothe"
    CSS = """
    #main-layout {
        layout: vertical;
        height: 1fr;
    }
    #conversation-row {
        height: 4fr;
        margin-bottom: 1;
    }
    #conversation {
        border: solid $primary;
        height: 100%;
    }
    #panels-row {
        layout: horizontal;
        height: 1fr;
        margin-bottom: 1;
    }
    #plan-panel {
        width: 1fr;
        border: solid $accent;
        margin-right: 1;
    }
    #activity-panel {
        width: 1fr;
        border: solid $accent;
    }
    #info-bar {
        dock: bottom;
        height: 2;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    #chat-input {
        height: 3;
        padding: 0 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+d", "detach", "Detach"),
        Binding("ctrl+q", "quit_app", "Quit"),
    ]

    def __init__(
        self,
        config: SootheConfig | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Soothe TUI application.

        Args:
            config: Soothe configuration.
            thread_id: Optional thread ID to resume.
            **kwargs: Additional keyword arguments passed to App.
        """
        super().__init__(**kwargs)
        self._config = config or SootheConfig()
        self._thread_id = thread_id
        self._client: DaemonClient | None = None
        self._state = TuiState()
        self._connected = False
        self._conversation_history: list[str] = []
        self._last_activity_count = 0
        self._progress_verbosity = self._config.logging.progress_verbosity
        self._thread_logger: ThreadLogger | None = None
        self._was_running = False

    def compose(self) -> ComposeResult:
        """Build the widget tree: 3-row layout."""
        max_lines = self._config.activity_max_lines
        yield Header()
        with Container(id="main-layout"):
            # Row 1: Conversation panel (largest height)
            with Container(id="conversation-row"):
                yield ConversationPanel(
                    id="conversation",
                    highlight=True,
                    markup=True,
                    wrap=True,
                )
            # Row 2: Plan and Activity panels (equal width, side by side)
            with Container(id="panels-row"):
                yield PlanPanel(
                    id="plan-panel",
                    highlight=True,
                    markup=True,
                    wrap=True,
                )
                yield ActivityPanel(
                    id="activity-panel",
                    highlight=True,
                    markup=True,
                    wrap=True,
                    max_lines=max_lines,
                )
            # Row 3: Chat input
            yield ChatInput(placeholder="soothe> Type a message or /help", id="chat-input")
        yield InfoBar("Thread: -  Events: 0  Idle", id="info-bar")

    async def on_mount(self) -> None:
        """Connect to daemon on startup."""
        with contextlib.suppress(Exception):
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.focus()

        self.run_worker(self._connect_and_listen(), exclusive=True)

    async def _connect_and_listen(self) -> None:
        """Connect to daemon and process events."""
        self._client = DaemonClient()
        max_retries = 40
        for attempt in range(max_retries):
            try:
                await self._client.connect()
                self._connected = True
                self._update_status("Connected")
                break
            except (OSError, ConnectionRefusedError):
                if attempt == max_retries - 1:
                    self._log_conversation(
                        "[red]Failed to connect to daemon after retries. "
                        "Is the socket at " + str(socket_path()) + " available?[/red]"
                    )
                    return
                await asyncio.sleep(0.25)

        # Request thread resumption if thread_id was provided
        if self._thread_id:
            await self._client.send_resume_thread(self._thread_id)

        while self._connected:
            event = await self._client.read_event()
            if event is None:
                self._connected = False
                self._log_conversation("[dim]Daemon connection closed.[/dim]")
                break

            activity_panel = self.query_one("#activity-panel", ActivityPanel)
            activity_panel._last_activity_count = self._last_activity_count

            process_daemon_event(
                event,
                self._state,
                activity_panel,
                verbosity=self._progress_verbosity,
                on_status_update=self._update_status,
                on_conversation_append=self._append_conversation,
                on_plan_refresh=self._refresh_plan,
            )

            self._last_activity_count = getattr(activity_panel, "_last_activity_count", len(self._state.activity_lines))

            # Handle thread ID changes
            if event.get("type") == "status":
                state_str = event.get("state", "")

                # Load input history
                history = event.get("input_history", [])
                if history:
                    chat_input = self.query_one("#chat-input", ChatInput)
                    chat_input.set_history(history)

                tid = event.get("thread_id", self._state.thread_id)
                previous_thread_id = self._thread_id
                if tid and tid != previous_thread_id:
                    self._thread_id = tid
                    if self._was_running:
                        # Post-query thread change: the runner assigned a new
                        # thread_id during execution.  Preserve the in-memory
                        # conversation (already rendered) and just update the
                        # thread logger so future persistence uses the right id.
                        self._thread_logger = ThreadLogger(
                            thread_id=tid,
                            retention_days=self._config.logging.thread_logging.retention_days,
                            max_size_mb=self._config.logging.thread_logging.max_size_mb,
                        )
                        logger.info("Thread logger initialized for thread %s", tid)
                    else:
                        # Explicit thread switch (initial connect, resume):
                        # reload history from disk.
                        self._load_thread_history(tid)
                        with contextlib.suppress(Exception):
                            panel = self.query_one("#conversation", ConversationPanel)
                            panel.clear()
                            for entry in self._conversation_history:
                                panel.write(entry)
                            self._flush_new_activity()

                if state_str == "running":
                    self._was_running = True
                elif state_str in ("idle", "stopped"):
                    self._was_running = False

            # Handle command_response
            if event.get("type") == "command_response":
                content = event.get("content", "")
                if content:
                    self._log_conversation(content)

            await asyncio.sleep(0)

    def _load_thread_history(self, thread_id: str) -> None:
        """Load conversation and activity history for a thread.

        Searches both 'sessions' and 'threads' directories for backward compatibility.

        Args:
            thread_id: Thread ID to load history for.
        """
        if not thread_id:
            return

        # Clear previous history to prevent unbounded memory growth
        self._conversation_history.clear()

        # Use runs/{thread_id}/ directory (RFC-0010)
        self._thread_logger = ThreadLogger(
            thread_id=thread_id,
            retention_days=self._config.logging.thread_logging.retention_days,
            max_size_mb=self._config.logging.thread_logging.max_size_mb,
        )
        logger.info("Thread logger initialized for thread %s", thread_id)

        try:
            # Load recent conversation history
            conversations = self._thread_logger.recent_conversation(limit=50)
            for record in conversations:
                role = record.get("role", "unknown")
                text = record.get("text", "")
                if role == "user":
                    self._conversation_history.append(f"\n[bold cyan]User:[/bold cyan] {text}")
                elif role == "assistant":
                    self._conversation_history.append(f"\n[bold green]Assistant:[/bold green] {text}")

            # Load recent activity
            events = self._thread_logger.recent_actions(limit=100)
            for record in events:
                namespace = record.get("namespace", [])
                data = record.get("data", {})
                if isinstance(data, dict):
                    # Re-render the event using existing handlers
                    from soothe.cli.progress_verbosity import classify_custom_event

                    category = classify_custom_event(tuple(namespace), data)
                    if should_show(category, self._progress_verbosity):
                        from soothe.cli.tui.renderers import _handle_generic_custom_activity

                        _handle_generic_custom_activity(
                            tuple(namespace),
                            data,
                            self._state,
                            verbosity=self._progress_verbosity,
                        )

            logger.info(
                "Loaded thread history: %d conversations, %d events for thread %s",
                len(conversations),
                len(events),
                thread_id,
            )
        except Exception:
            logger.debug("Failed to load thread history", exc_info=True)

    def _log_conversation(self, text: str) -> None:
        self._conversation_history.append(text)
        logger.info("Conversation: %s", text.replace("\n", " ")[:200])
        with contextlib.suppress(Exception):
            panel = self.query_one("#conversation", ConversationPanel)
            panel.write(text)

    def _append_conversation(self) -> None:
        """Rewrite the conversation panel with history + accumulated streaming text."""
        with contextlib.suppress(Exception):
            panel = self.query_one("#conversation", ConversationPanel)
            response_text = "".join(self._state.full_response)

            # Always show conversation history, even if response is empty
            panel.clear()
            for entry in self._conversation_history:
                panel.write(entry)

            # Append response if available
            if response_text:
                panel.write(response_text, scroll_end=True)

    def _flush_new_activity(self) -> None:
        """Append only new activity lines (append-only, no clear)."""
        with contextlib.suppress(Exception):
            panel = self.query_one("#activity-panel", ActivityPanel)
            new_lines = self._state.activity_lines[self._last_activity_count :]
            for line in new_lines:
                panel.write(line)
            self._last_activity_count = len(self._state.activity_lines)

    def _refresh_plan(self) -> None:
        with contextlib.suppress(Exception):
            panel = self.query_one("#plan-panel", PlanPanel)
            panel.clear()
            if self._state.current_plan:
                tree = render_plan_tree(self._state.current_plan)
                panel.write(tree)
            else:
                panel.write("[dim]No active plan.[/dim]")

    def _update_status(self, state: str) -> None:
        with contextlib.suppress(Exception):
            bar = self.query_one("#info-bar", InfoBar)
            tid = self._state.thread_id or "-"
            events = len(self._state.activity_lines)
            subagent_lines = self._state.subagent_tracker.render()
            sub_summary = ""
            if subagent_lines:
                last = subagent_lines[-1]
                sub_summary = f"  |  {last.plain}" if hasattr(last, "plain") else ""
            bar.update(f"Thread: {tid}  Events: {events}  {state.title()}{sub_summary}")

    # -- input handling -----------------------------------------------------

    @on(Input.Submitted, "#chat-input")
    async def on_chat_submit(self, event: Input.Submitted) -> None:
        """Handle chat input submission."""
        text = event.value.strip()
        if not text:
            return
        event.input.clear()

        with contextlib.suppress(Exception):
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.add_to_history(text)

        if self._state.full_response:
            self._conversation_history.append("".join(self._state.full_response))

        self._log_conversation(f"\n[bold cyan]User:[/bold cyan] {text}")
        self._state.full_response.clear()
        self._state.seen_message_ids.clear()
        self._state.last_user_input = text

        if not self._client or not self._connected:
            self._log_conversation("[red]Not connected to daemon.[/red]")
            return

        if text.startswith("/"):
            if text.strip() in ("/exit", "/quit"):
                await self._client.send_command(text.strip())
                self.exit()
                return
            if text.strip() == "/detach":
                await self.action_detach()
                return
            parsed_auto = parse_autonomous_command(text.strip())
            if parsed_auto is not None:
                max_iterations, prompt = parsed_auto
                self._log_conversation("[bold green]Assistant:[/bold green] ")
                await self._client.send_input(prompt, autonomous=True, max_iterations=max_iterations)
                # Don't return - let the user input be logged above
                return
            await self._client.send_command(text.strip())
        else:
            self._log_conversation("[bold green]Assistant:[/bold green] ")
            await self._client.send_input(
                text,
                autonomous=self._config.autonomous.enabled_by_default,
            )

    # -- actions ------------------------------------------------------------

    async def action_detach(self) -> None:
        """Detach from daemon, keep it running."""
        if self._client:
            await self._client.send_detach()
            await self._client.close()
        self._connected = False
        self.exit(message="Detached from Soothe daemon. Use 'soothe attach' to reconnect.")

    async def action_quit_app(self) -> None:
        """Stop daemon and quit."""
        if self._client:
            await self._client.send_command("/exit")
            await self._client.close()
        self._connected = False
        self.exit()


# ---------------------------------------------------------------------------
# Daemon process bootstrap
# ---------------------------------------------------------------------------


def _start_daemon_in_background(_config: SootheConfig, *, config_path: str | None = None) -> None:
    """Start daemon as an external process when not already running."""
    if SootheDaemon.is_running():
        return

    cmd = [sys.executable, "-m", "soothe.cli.daemon"]
    if config_path:
        cmd.extend(["--config", config_path])
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    import time

    for _ in range(40):
        time.sleep(0.25)
        if socket_path().exists():
            break


def _stop_background_daemon() -> None:
    """No-op: daemon lifecycle is externally managed."""
    return


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_textual_tui(
    config: SootheConfig | None = None,
    *,
    thread_id: str | None = None,
    config_path: str | None = None,
) -> None:
    """Launch the Textual-based TUI.

    Args:
        config: Soothe configuration.
        thread_id: Optional thread ID to resume.
        config_path: Optional config file path passed to daemon process.
    """
    cfg = config or SootheConfig()
    _start_daemon_in_background(cfg, config_path=config_path)
    try:
        app = SootheApp(config=cfg, thread_id=thread_id)
        app.run()
    finally:
        _stop_background_daemon()
