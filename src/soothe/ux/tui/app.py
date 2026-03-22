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

import pyperclip
from rich.markdown import Markdown
from rich.panel import Panel
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header

from soothe.config import SootheConfig
from soothe.daemon import DaemonClient, SootheDaemon, socket_path
from soothe.daemon.thread_logger import ThreadLogger
from soothe.ux.shared.progress_verbosity import should_show
from soothe.ux.shared.rendering import render_plan_tree
from soothe.ux.shared.slash_commands import parse_autonomous_command
from soothe.ux.tui.event_processors import process_daemon_event
from soothe.ux.tui.modals import ThreadSelectionModal
from soothe.ux.tui.state import TuiState
from soothe.ux.tui.widgets import ChatInput, ConversationPanel, InfoBar, PlanTree

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
    #info-row {
        layout: vertical;
        height: auto;
        margin-bottom: 1;
    }
    #plan-tree {
        height: auto;
        max-height: 20;
        padding: 0 1;
        border: none;
        overflow: hidden;
    }
    #plan-tree.hidden {
        display: none;
    }
    #chat-input-container {
        dock: bottom;
        layout: vertical;
        height: auto;
        background: $surface;
        padding: 1 2 0 2;
        border-top: solid $primary;
    }
    #chat-input-row {
        layout: horizontal;
        height: auto;
        min-height: 3;
        max-height: 8;
        margin-bottom: 0;
    }
    #chat-prompt {
        color: $accent;
        text-style: bold;
        width: auto;
        content-align: left middle;
        padding-right: 1;
    }
    #chat-input {
        height: auto;
        min-height: 1;
        max-height: 6;
        padding: 0;
        color: $foreground;
        background: transparent;
        border: none;
        width: 1fr;
    }
    #chat-input:focus {
        border: none;
    }
    #chat-input .text-area--cursor-line {
        background: transparent;
    }
    #info-bar-wrapper {
        height: auto;
        margin-top: 0;
        padding: 0 0 1 0;
    }
    #info-bar {
        height: 1;
        background: transparent;
        color: $text-muted;
        padding: 0;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+d", "detach", "Detach"),
        Binding("ctrl+q", "quit_app", "Quit"),
        Binding("ctrl+c", "cancel_job", "Cancel Job"),
        Binding("ctrl+e", "focus_input", "Focus Input"),
        Binding("ctrl+y", "copy_last", "Copy Last Message"),
        Binding("ctrl+t", "toggle_plan", "Toggle Plan"),
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
        self._conversation_history: list[str | Panel] = []
        self._message_history: list[dict[str, str]] = []
        self._last_activity_count = 0
        self._progress_verbosity = self._config.logging.progress_verbosity
        self._thread_logger: ThreadLogger | None = None
        self._was_running = False
        self._typing_indicator_task: asyncio.Task | None = None
        self._typing_frame = 0
        self._is_running = False

    def compose(self) -> ComposeResult:
        """Build the widget tree: 3-row layout."""
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
            # Row 2: Plan tree (merged with activity info)
            with Container(id="info-row"):
                yield PlanTree(id="plan-tree", classes="" if self._state.plan_visible else "hidden")
        # Chat input with prompt character (outside main-layout, docked at bottom)
        with Container(id="chat-input-container"):
            # Input row
            with Container(id="chat-input-row"):
                from textual.widgets import Static

                yield Static(">", id="chat-prompt")
                yield ChatInput(id="chat-input")
            # Info bar under input (thread, events, subagent status)
            with Container(id="info-bar-wrapper"):
                yield InfoBar("Thread: -  Events: 0  Idle", id="info-bar")

    async def on_mount(self) -> None:
        """Connect to daemon on startup."""
        with contextlib.suppress(Exception):
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.focus()

        self._refresh_plan()
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

        # Request thread resumption if thread_id was provided, otherwise request new thread
        if self._thread_id:
            await self._client.send_resume_thread(self._thread_id)
        else:
            await self._client.send_new_thread()

        while self._connected:
            event = await self._client.read_event()
            if event is None:
                self._connected = False
                self._log_conversation("[dim]Daemon connection closed.[/dim]")
                break

            process_daemon_event(
                event,
                self._state,
                verbosity=self._progress_verbosity,
                on_status_update=self._update_status,
                on_conversation_append=self._append_conversation,
                on_plan_refresh=self._refresh_plan,
            )

            # Update activity display after processing event
            self._flush_new_activity()

            # Handle thread ID changes
            if event.get("type") == "status":
                state_str = event.get("state", "")
                thread_resumed = event.get("thread_resumed", False)

                tid = event.get("thread_id", self._state.thread_id)
                # Ensure thread_id is always a string (JSON deserialization may preserve integers)
                if tid is not None:
                    tid = str(tid)
                previous_thread_id = self._thread_id

                # Handle new thread (empty thread_id) - clear conversation
                if tid == "" and previous_thread_id is not None:
                    # Starting a fresh thread, clear previous conversation
                    self._thread_id = None
                    self._conversation_history.clear()
                    self._message_history.clear()
                    self._state.full_response.clear()
                    self._state.activity_lines.clear()
                    # Don't load old input history for new threads
                    with contextlib.suppress(Exception):
                        panel = self.query_one("#conversation", ConversationPanel)
                        panel.clear()
                elif tid and (tid != previous_thread_id or thread_resumed):
                    # Thread switch or resume - load input history
                    history = event.get("input_history", [])
                    if history:
                        chat_input = self.query_one("#chat-input", ChatInput)
                        chat_input.set_history(history)
                    # Thread switch or explicit resume - load history from disk
                    self._thread_id = tid
                    if self._was_running and not thread_resumed:
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

            # Handle clear event
            if event.get("type") == "clear":
                self._handle_clear()

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
        self._message_history.clear()

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
                    # Create panel with cyan border for user messages
                    panel = Panel(text, title="👤 User", border_style="cyan", padding=(0, 1))
                    self._conversation_history.append(panel)
                    self._message_history.append({"role": "user", "content": text, "index": len(self._message_history)})
                elif role == "assistant":
                    # Create panel with green border for assistant messages
                    # Use Markdown renderer for proper formatting
                    markdown_content = Markdown(text)
                    panel = Panel(markdown_content, title="🤖 Assistant", border_style="green", padding=(0, 1))
                    self._conversation_history.append(panel)
                    self._message_history.append(
                        {"role": "assistant", "content": text, "index": len(self._message_history)}
                    )

            # Load recent activity
            events = self._thread_logger.recent_actions(limit=100)
            for record in events:
                namespace = record.get("namespace", [])
                data = record.get("data", {})
                if isinstance(data, dict):
                    # Re-render the event using existing handlers
                    from soothe.ux.shared.progress_verbosity import classify_custom_event

                    category = classify_custom_event(tuple(namespace), data)
                    if should_show(category, self._progress_verbosity):
                        from soothe.ux.tui.renderers import _handle_generic_custom_activity

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
        # Check if this is a user message
        if "👤 User:" in text:
            # Extract the raw message content
            raw_content = text.split("👤 User:", 1)[-1].strip()
            # Remove Rich markup tags
            import re

            raw_content = re.sub(r"\[/?[^\]]+\]", "", raw_content)

            # Store for copying
            self._message_history.append({"role": "user", "content": raw_content, "index": len(self._message_history)})

            # Create panel with cyan border
            panel_widget = Panel(
                raw_content,
                title="👤 User",
                border_style="cyan",
                padding=(0, 1),
            )
            self._conversation_history.append(panel_widget)
            logger.info("Conversation: User message - %s", raw_content[:200])

            with contextlib.suppress(Exception):
                conv_panel = self.query_one("#conversation", ConversationPanel)
                conv_panel.write(panel_widget)
        else:
            # Non-user messages (system messages, etc.) - keep as plain text
            self._conversation_history.append(text)
            logger.info("Conversation: %s", text.replace("\n", " ")[:200])
            with contextlib.suppress(Exception):
                conv_panel = self.query_one("#conversation", ConversationPanel)
                conv_panel.write(text)

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
                # Remove Rich markup for raw storage
                import re

                raw_content = re.sub(r"\[/?[^\]]+\]", "", response_text)

                # Check if we already have this assistant message stored
                # (streaming continues on the same message)
                if self._message_history and self._message_history[-1]["role"] == "assistant":
                    # Update the last assistant message content
                    self._message_history[-1]["content"] = raw_content
                else:
                    # New assistant message - add to history
                    self._message_history.append(
                        {"role": "assistant", "content": raw_content, "index": len(self._message_history)}
                    )

                # Convert to Markdown for proper formatting (headings, spacing, etc.)
                markdown_content = Markdown(response_text)

                # Create panel with green border (always create fresh for streaming)
                assistant_panel = Panel(
                    markdown_content,
                    title="🤖 Assistant",
                    border_style="green",
                    padding=(0, 1),
                )
                panel.write(assistant_panel, scroll_end=True)

    def _flush_new_activity(self) -> None:
        """Update plan tree with activity info (merged display)."""
        self._refresh_plan()

    def _refresh_plan(self) -> None:
        """Update plan tree display."""
        try:
            plan_tree = self.query_one("#plan-tree", PlanTree)

            # Only show plan tree, not recent activity
            if self._state.current_plan:
                tree = render_plan_tree(self._state.current_plan)
                # Render Tree to string using Console
                from io import StringIO

                from rich.console import Console

                console = Console(file=StringIO(), force_terminal=True)
                console.print(tree)
                plan_content = console.file.getvalue()
                plan_tree.update(plan_content)
            else:
                plan_tree.update("[dim]No active plan.[/dim]")
        except Exception:
            logger.debug("Failed to refresh plan tree", exc_info=True)

    def _handle_clear(self) -> None:
        """Clear all TUI panels."""
        try:
            # Clear conversation panel
            conv_panel = self.query_one("#conversation", ConversationPanel)
            conv_panel.clear()

            # Clear plan tree
            plan_tree = self.query_one("#plan-tree", PlanTree)
            plan_tree.update("[dim]No active plan.[/dim]")

            # Clear internal state
            self._conversation_history.clear()
            self._message_history.clear()
            self._state.full_response.clear()
            self._state.activity_lines.clear()
            self._state.tool_call_buffers.clear()
            self._state.errors.clear()
            self._state.seen_message_ids.clear()
            self._last_activity_count = 0

            logger.info("TUI panels cleared")
        except Exception:
            logger.exception("Failed to clear TUI panels")

    def _update_status(self, state: str) -> None:
        # Start/stop typing indicator based on state
        if state == "running":
            self._is_running = True
            self._start_typing_indicator()
        else:
            self._is_running = False
            self._stop_typing_indicator()
            # Update status bar when not running
            self._update_status_bar(state.title())

    def _start_typing_indicator(self) -> None:
        """Start the animated typing indicator."""
        if self._typing_indicator_task is None or self._typing_indicator_task.done():
            self._typing_indicator_task = asyncio.create_task(self._animate_typing_indicator())

    def _stop_typing_indicator(self) -> None:
        """Stop the animated typing indicator."""
        if self._typing_indicator_task and not self._typing_indicator_task.done():
            self._typing_indicator_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                pass
            self._typing_indicator_task = None

    async def _animate_typing_indicator(self) -> None:
        """Animate typing indicator in the info bar."""
        # Spinner frames
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        messages = ["Thinking", "Processing", "Working", "Analyzing"]
        msg_idx = 0

        try:
            while self._is_running:
                frame = frames[self._typing_frame % len(frames)]
                message = messages[msg_idx % len(messages)]
                indicator = f"[bold cyan]{frame} {message}...[/bold cyan]"

                # Update info bar with indicator
                self._update_status_bar(indicator)

                self._typing_frame += 1
                if self._typing_frame % 10 == 0:  # Change message every 10 frames
                    msg_idx += 1

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            self._typing_indicator_task = None

    def _update_status_bar(self, status_text: str) -> None:
        """Update the info bar with current status."""
        with contextlib.suppress(Exception):
            bar = self.query_one("#info-bar", InfoBar)
            tid = self._state.thread_id or "-"
            events = len(self._state.activity_lines)
            subagent_lines = self._state.subagent_tracker.render()
            sub_summary = ""
            if subagent_lines:
                last = subagent_lines[-1]
                sub_summary = f"  |  {last.plain}" if hasattr(last, "plain") else ""
            bar.update(f"Thread: {tid}  Events: {events}  {status_text}{sub_summary}")

    # -- input handling -----------------------------------------------------

    async def submit_chat_input(self) -> None:
        """Handle chat input submission."""
        chat_input = self.query_one("#chat-input", ChatInput)
        text = chat_input.text.strip()
        if not text:
            return
        chat_input.clear()

        with contextlib.suppress(Exception):
            chat_input.add_to_history(text)

        if self._state.full_response:
            # Store the previous assistant response in conversation history
            response_text = "".join(self._state.full_response)

            # Convert to Markdown for proper formatting
            markdown_content = Markdown(response_text)

            # Create and store panel
            assistant_panel = Panel(
                markdown_content,
                title="🤖 Assistant",
                border_style="green",
                padding=(0, 1),
            )
            self._conversation_history.append(assistant_panel)
            # Note: _message_history is already updated during streaming in _append_conversation

        self._log_conversation(f"\n[bold cyan]👤 User:[/bold cyan] {text}")
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
            if text.strip() == "/resume":
                await self._show_thread_selection()
                return
            parsed_auto = parse_autonomous_command(text.strip())
            if parsed_auto is not None:
                max_iterations, prompt = parsed_auto
                await self._client.send_input(prompt, autonomous=True, max_iterations=max_iterations)
                # Don't return - let the user input be logged above
                return
            # Check for subagent subcommands
            from soothe.ux.cli.commands.subagent_names import parse_subagent_from_input

            subagent_name, cleaned_text = parse_subagent_from_input(text)
            if subagent_name:
                # Route to subagent
                await self._client.send_input(
                    cleaned_text,
                    autonomous=self._config.autonomous.enabled_by_default,
                    subagent=subagent_name,
                )
                return
            await self._client.send_command(text.strip())
        else:
            await self._client.send_input(
                text,
                autonomous=self._config.autonomous.enabled_by_default,
            )

    # -- actions ------------------------------------------------------------

    async def _show_thread_selection(self) -> None:
        """Show thread selection modal and resume selected thread."""
        if not self._client or not self._connected:
            self._log_conversation("[red]Not connected to daemon.[/red]")
            return

        # Create a runner instance for the modal
        from soothe.core.runner import SootheRunner

        runner = SootheRunner(self._config)

        # Show the modal
        selected_thread_id = await self.app.push_screen_wait(ThreadSelectionModal(runner))

        if selected_thread_id:
            # Resume the selected thread
            self._log_conversation(f"[dim]Resuming thread {selected_thread_id}...[/dim]")
            await self._client.send_resume_thread(selected_thread_id)

    async def action_detach(self) -> None:
        """Detach from daemon, keep it running."""
        self._stop_typing_indicator()
        if self._client:
            await self._client.send_detach()
            await self._client.close()
        self._connected = False
        self.exit(message="Detached from Soothe daemon. Use 'soothe server attach' to reconnect.")

    async def action_quit_app(self) -> None:
        """Stop daemon and quit."""
        self._stop_typing_indicator()
        if self._client:
            try:
                await self._client.send_command("/exit")
                await self._client.close()
            except (ConnectionResetError, ConnectionError, BrokenPipeError):
                # Connection already closed or lost, just exit gracefully
                pass
        self._connected = False
        self.exit()

    async def action_cancel_job(self) -> None:
        """Cancel the currently running job."""
        if self._client and self._connected:
            await self._client.send_command("/cancel")

    async def action_copy_last(self) -> None:
        """Copy the last message to clipboard."""
        if not self._message_history:
            self._log_conversation("[dim]No messages to copy.[/dim]")
            return

        last_msg = self._message_history[-1]
        try:
            pyperclip.copy(last_msg["content"])
            role = last_msg["role"].title()
            self._log_conversation(f"[dim]✓ Copied {role} message to clipboard[/dim]")
        except Exception:
            logger.exception("Failed to copy to clipboard")
            self._log_conversation("[red]Failed to copy to clipboard[/red]")

    async def action_focus_input(self) -> None:
        """Focus the chat input field."""
        with contextlib.suppress(Exception):
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.focus()

    async def action_toggle_plan(self) -> None:
        """Toggle plan tree visibility."""
        try:
            plan_tree = self.query_one("#plan-tree", PlanTree)
            plan_tree.toggle_class("hidden")
            self._state.plan_visible = not self._state.plan_visible
        except Exception:
            logger.debug("Failed to toggle plan tree", exc_info=True)


# ---------------------------------------------------------------------------
# Daemon process bootstrap
# ---------------------------------------------------------------------------


def _start_daemon_in_background(_config: SootheConfig, *, config_path: str | None = None) -> None:
    """Start daemon as an external process when not already running."""
    if SootheDaemon.is_running():
        return

    cmd = [sys.executable, "-m", "soothe.daemon"]
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
