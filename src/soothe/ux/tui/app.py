"""Textual-based TUI for Soothe (RFC-0003 revised).

Full-viewport layout with footer stack:
  - Conversation panel (full height, borderless, native scrolling)
  - Footer stack (docked bottom):
    - Plan/Activity panel (compact, collapsible)
    - Info bar (thread, events, status)
    - Chat input with UP/DOWN history navigation

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
from pathlib import Path
from typing import Any, ClassVar

import pyperclip
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container

from soothe.config import SOOTHE_HOME, SootheConfig
from soothe.daemon import DaemonClient, SootheDaemon, socket_path
from soothe.daemon.thread_logger import ThreadLogger
from soothe.ux.shared.rendering import render_plan_tree
from soothe.ux.shared.slash_commands import parse_autonomous_command
from soothe.ux.tui.event_processors import process_daemon_event
from soothe.ux.tui.modals import ThreadSelectionModal
from soothe.ux.tui.renderers import DOT_COLORS, make_dot_line, make_user_prompt_line
from soothe.ux.tui.state import TuiState
from soothe.ux.tui.widgets import ChatInput, ConversationPanel, InfoBar, PlanTree

logger = logging.getLogger(__name__)

_THREAD_ID_DISPLAY_LEN = 8


class SootheApp(App):
    """Textual application for the Soothe TUI."""

    TITLE = "Soothe"
    CSS = """
    #conversation {
        height: 1fr;
        border: none;
        padding: 0 1;
        background: transparent;
    }

    #footer-stack {
        dock: bottom;
        layout: vertical;
        height: auto;
        background: $surface;
        border-top: solid $primary;
    }

    #plan-tree {
        height: auto;
        max-height: 15;
        padding: 0 1;
        border: none;
        display: none;
    }
    #plan-tree.visible {
        display: block;
    }

    #info-bar {
        height: 1;
        padding: 0 1;
        background: $surface-darken-1;
        color: $text-muted;
    }

    #chat-input-row {
        layout: horizontal;
        height: auto;
        min-height: 1;
        max-height: 50vh;
        padding: 0 1;
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
        max-height: 50vh;
        padding: 0;
        color: $foreground;
        background: transparent;
        border: none;
        width: 1fr;
        overflow-y: auto;
    }
    #chat-input:focus {
        border: none;
    }
    #chat-input .text-area--cursor-line {
        background: transparent;
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
        logger.debug("__init__: thread_id=%r", self._thread_id)
        self._client: DaemonClient | None = None
        self._state = TuiState()
        self._connected = False
        # Clean cut: removed _conversation_history and _message_history
        # Display is now via direct panel writes only
        self._history_loaded_thread_id: str | None = None
        self._progress_verbosity = self._config.logging.progress_verbosity
        self._thread_logger: ThreadLogger | None = None
        self._was_running = False
        self._typing_indicator_task: asyncio.Task | None = None
        self._typing_frame = 0
        self._is_running = False

    def compose(self) -> ComposeResult:
        """Build the widget tree: simplified layout with footer stack."""
        yield ConversationPanel(
            id="conversation",
            highlight=True,
            markup=True,
            wrap=True,
        )

        with Container(id="footer-stack"):
            # Plan tree shown only when there's an active plan (Bug #2)
            yield PlanTree(id="plan-tree", classes="")
            with Container(id="chat-input-row"):
                from textual.widgets import Static

                yield Static(">", id="chat-prompt")
                yield ChatInput(id="chat-input")
            # InfoBar moved below chat-input-row (Bug #2)
            yield InfoBar("Thread: -  Events: 0  Idle", id="info-bar")

    async def on_mount(self) -> None:
        """Connect to daemon on startup."""
        with contextlib.suppress(Exception):
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.focus()

        if self._thread_id:
            self._state.thread_id = self._thread_id
            logger.debug("on_mount: state.thread_id=%r", self._state.thread_id)
            self._update_status_bar("Idle")

        self._refresh_plan()
        self.run_worker(self._connect_and_listen(), exclusive=True)

    def _on_panel_write(self, renderable: Any) -> None:
        """Append a renderable to the conversation panel.

        Args:
            renderable: Rich renderable content to append.
        """
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            panel.append_entry(renderable)
        except Exception:
            logger.debug("Failed to write to panel", exc_info=True)

    def _on_panel_update_last(self, renderable: Any) -> None:
        """Update the last entry in the conversation panel.

        Args:
            renderable: Rich renderable content to replace the last entry with.
        """
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            panel.update_last_entry(renderable)
        except Exception:
            logger.debug("Failed to update panel", exc_info=True)

    def _display_conversation_history(self, history: list[dict[str, Any]]) -> None:
        """Display conversation history in the conversation panel.

        Args:
            history: List of conversation records from ThreadLogger.
                Each record has: timestamp, kind, role, text
        """
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            # Clear existing content before showing history
            panel.clear()

            # Add header to indicate this is resumed conversation
            self._on_panel_write(make_dot_line(DOT_COLORS["protocol"], "Resuming conversation..."))

            for record in history:
                role = record.get("role", "")
                text = record.get("text", "")
                if not text:
                    continue

                if role == "user":
                    self._on_panel_write(make_user_prompt_line(text))
                elif role == "assistant":
                    self._on_panel_write(make_dot_line(DOT_COLORS["assistant"], text))

            # Add separator after history
            self._on_panel_write(make_dot_line(DOT_COLORS["protocol"], "---"))
        except Exception:
            logger.debug("Failed to display conversation history", exc_info=True)

    async def _connect_and_listen(self) -> None:
        """Connect to daemon and process events."""
        self._client = DaemonClient()
        max_retries = 40
        for attempt in range(max_retries):
            try:
                await self._client.connect()
                self._connected = True
                logger.debug("Connected to daemon, thread_id=%r", self._state.thread_id)
                self._update_status("Connected")
                break
            except (OSError, ConnectionRefusedError):
                if attempt == max_retries - 1:
                    self._on_panel_write(
                        make_dot_line(
                            DOT_COLORS["error"],
                            f"Failed to connect to daemon after retries. Is the socket at {socket_path()} available?",
                        )
                    )
                    return
                await asyncio.sleep(0.25)

        # Request thread resumption if thread_id was provided, otherwise request new thread
        requested_resume = False
        if self._thread_id:
            await self._client.send_resume_thread(self._thread_id)
            requested_resume = True
        else:
            await self._client.send_new_thread()

        # Wait for status message with thread_id
        try:
            status_event = await asyncio.wait_for(self._client.read_event(), timeout=5.0)
            logger.debug("Received initial event: %r", status_event)

            # Handle error response for thread resumption (thread not found)
            if status_event and status_event.get("type") == "error":
                error_code = status_event.get("code", "")
                error_message = status_event.get("message", "Unknown error")
                if error_code == "THREAD_NOT_FOUND" and requested_resume:
                    # Thread doesn't exist anymore - fall back to new thread
                    logger.warning(
                        "Thread %s not found, creating new thread: %s",
                        self._thread_id,
                        error_message,
                    )
                    # Request new thread instead
                    await self._client.send_new_thread()
                    status_event = await asyncio.wait_for(self._client.read_event(), timeout=5.0)
                    logger.debug("Received new thread event: %r", status_event)
                else:
                    # Other error - report and return
                    self._on_panel_write(make_dot_line(DOT_COLORS["error"], f"Daemon error: {error_message}"))
                    return

            if not status_event or status_event.get("type") != "status":
                self._on_panel_write(
                    make_dot_line(DOT_COLORS["error"], f"Expected status message from daemon, got: {status_event}")
                )
                return

            # Extract thread_id and client_id
            thread_id = status_event.get("thread_id")
            client_id = status_event.get("client_id")
            if not thread_id:
                self._on_panel_write(make_dot_line(DOT_COLORS["error"], "No thread_id in status message"))
                return

            self._state.thread_id = thread_id
            self._state.client_id = client_id
            logger.info("Connected to daemon, thread=%s, client=%s", thread_id, client_id)

            # Subscribe to thread (RFC-0013)
            await self._client.subscribe_thread(thread_id)
            await self._client.wait_for_subscription_confirmed(thread_id)
            logger.info("Subscribed to thread %s", thread_id)

        except TimeoutError:
            self._on_panel_write(make_dot_line(DOT_COLORS["error"], "Timeout waiting for status from daemon"))
            return
        except ValueError as e:
            self._on_panel_write(make_dot_line(DOT_COLORS["error"], f"Subscription failed: {e}"))
            return

        while self._connected:
            try:
                # Use timeout to prevent indefinite blocking and allow UI updates
                event = await asyncio.wait_for(self._client.read_event(), timeout=5.0)
                if event is None:
                    logger.warning("read_event returned None, connection closed")
                    self._connected = False
                    self._on_panel_write(make_dot_line(DOT_COLORS["protocol"], "Daemon connection closed."))
                    break
            except TimeoutError:
                # No event received for 5 seconds - connection is still alive
                # This timeout allows the UI to remain responsive
                continue

            # Capture thread_id BEFORE process_daemon_event updates it
            # This is critical for detecting thread changes correctly
            pre_event_thread_id = self._state.thread_id

            process_daemon_event(
                event,
                self._state,
                verbosity=self._progress_verbosity,
                on_status_update=self._update_status,
                on_plan_refresh=self._refresh_plan,
                on_panel_write=self._on_panel_write,
                on_panel_update_last=self._on_panel_update_last,
            )
            if event.get("type") == "status":
                logger.debug("after process: state.thread_id=%r", self._state.thread_id)

            # Update activity display after processing event
            self._flush_new_activity()

            # Handle TUI-specific actions for status events
            if event.get("type") == "status":
                state_str = event.get("state", "")
                thread_resumed = event.get("thread_resumed", False)
                current_tid = self._state.thread_id

                # Clear panel on explicit new-thread signal
                if event.get("new_thread", False):
                    self._thread_id = current_tid or None
                    self._history_loaded_thread_id = current_tid or None
                    self._state.streaming_text_buffer = ""
                    self._state.streaming_active = False
                    self._state.current_tool_calls.clear()
                    with contextlib.suppress(Exception):
                        panel = self.query_one("#conversation", ConversationPanel)
                        panel.clear()
                elif current_tid and (
                    current_tid != pre_event_thread_id
                    or thread_resumed
                    or current_tid != self._history_loaded_thread_id
                ):
                    # Thread switch or resume - load input history for chat navigation
                    history = event.get("input_history", [])
                    if history:
                        chat_input = self.query_one("#chat-input", ChatInput)
                        chat_input.set_history(history)
                    self._thread_id = current_tid
                    self._history_loaded_thread_id = current_tid
                    # Initialize thread logger for future persistence
                    self._thread_logger = ThreadLogger(
                        thread_id=current_tid,
                        retention_days=self._config.logging.thread_logging.retention_days,
                        max_size_mb=self._config.logging.thread_logging.max_size_mb,
                    )

                    # Display conversation history when resuming a thread
                    if thread_resumed:
                        conversation_history = event.get("conversation_history", [])
                        if conversation_history:
                            self._display_conversation_history(conversation_history)

                if state_str == "running":
                    self._was_running = True
                elif state_str in ("idle", "stopped"):
                    self._was_running = False

            # Handle command_response
            if event.get("type") == "command_response":
                content = event.get("content", "")
                if content:
                    # Display command output in panel
                    self._on_panel_write(make_dot_line(DOT_COLORS["protocol"], content[:200]))

            # Handle clear event
            if event.get("type") == "clear":
                self._handle_clear()

            await asyncio.sleep(0)

    def _flush_new_activity(self) -> None:
        """Update plan tree display."""
        self._refresh_plan()

    def _refresh_plan(self) -> None:
        """Update plan tree display."""
        try:
            plan_tree = self.query_one("#plan-tree", PlanTree)

            # Only show plan tree when there's an active plan AND user hasn't hidden it (Bug #2)
            if self._state.current_plan:
                tree = render_plan_tree(self._state.current_plan)
                # Render Tree to string using Console
                from io import StringIO

                from rich.console import Console

                console = Console(file=StringIO(), force_terminal=True)
                console.print(tree)
                plan_content = console.file.getvalue()
                plan_tree.update(plan_content)
                # Show plan tree if user hasn't manually hidden it
                if self._state.plan_visible:
                    plan_tree.add_class("visible")
                else:
                    plan_tree.remove_class("visible")
            else:
                # Hide plan panel completely when no active plan (Bug #2)
                plan_tree.update("")
                plan_tree.remove_class("visible")
        except Exception:
            logger.debug("Failed to refresh plan tree", exc_info=True)

    def _handle_clear(self) -> None:
        """Clear all TUI panels."""
        try:
            # Clear conversation panel
            conv_panel = self.query_one("#conversation", ConversationPanel)
            conv_panel.clear()

            # Clear plan tree and hide it
            plan_tree = self.query_one("#plan-tree", PlanTree)
            plan_tree.update("")
            plan_tree.remove_class("visible")
            self._state.current_plan = None

            # Clear streaming state
            self._state.streaming_text_buffer = ""
            self._state.streaming_active = False
            self._state.current_tool_calls.clear()
            self._state.seen_message_ids.clear()
            self._state.errors.clear()

            logger.info("TUI panels cleared")
        except Exception:
            logger.exception("Failed to clear TUI panels")

    def _update_status(self, state: str) -> None:
        logger.debug("_update_status(%r): thread_id=%r", state, self._state.thread_id)
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
            logger.debug("_update_status_bar(%r): thread_id=%r", status_text, self._state.thread_id)
            bar = self.query_one("#info-bar", InfoBar)
            # Ensure thread_id is a proper string and truncate for display (Bug #1)
            raw_tid = self._state.thread_id
            if raw_tid:
                tid_str = str(raw_tid)
                # Truncate long UUIDs for display (show first 8 chars)
                tid = tid_str[:_THREAD_ID_DISPLAY_LEN] if len(tid_str) > _THREAD_ID_DISPLAY_LEN else tid_str
            else:
                tid = "-"
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

        # Display user input in conversation panel with Claude Code style
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            panel.append_separator()
            panel.append_entry(make_user_prompt_line(text))
        except Exception:
            logger.debug("Failed to write user input to panel", exc_info=True)

        # Reset streaming state for new turn
        self._state.streaming_text_buffer = ""
        self._state.streaming_active = False
        self._state.seen_message_ids.clear()
        self._state.last_user_input = text

        if not self._client or not self._connected:
            self._on_panel_write(make_dot_line(DOT_COLORS["error"], "Not connected to daemon."))
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
            self._on_panel_write(make_dot_line(DOT_COLORS["error"], "Not connected to daemon."))
            return

        # Create a runner instance for the modal
        from soothe.core.runner import SootheRunner

        runner = SootheRunner(self._config)

        # Show the modal
        selected_thread_id = await self.app.push_screen_wait(ThreadSelectionModal(runner))

        if selected_thread_id:
            # Resume the selected thread
            self._on_panel_write(make_dot_line(DOT_COLORS["protocol"], f"Resuming thread {selected_thread_id}..."))
            await self._client.send_resume_thread(selected_thread_id)

    async def action_detach(self) -> None:
        """Detach from daemon, keep it running."""
        self._stop_typing_indicator()
        if self._client:
            await self._client.send_detach()
            await self._client.close()
        self._connected = False
        self.exit(message="Detached from Soothe daemon. Use 'soothe thread continue --daemon' to reconnect.")

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
        """Copy the last streamed text to clipboard."""
        # In clean-cut mode, we copy from the streaming buffer or show a message
        content = self._state.last_assistant_output.strip()
        if not content:
            # Show dim message in panel
            try:
                panel = self.query_one("#conversation", ConversationPanel)
                panel.append_entry(make_dot_line(DOT_COLORS["protocol"], "No recent content to copy"))
            except Exception:
                logger.debug("Failed to show no-content message")
            return

        try:
            pyperclip.copy(content)
            # Show confirmation in panel
            panel = self.query_one("#conversation", ConversationPanel)
            panel.append_entry(make_dot_line(DOT_COLORS["success"], "Copied to clipboard"))
        except Exception as e:
            logger.exception("Failed to copy to clipboard")
            error_msg = str(e) or "Unknown error"
            try:
                panel = self.query_one("#conversation", ConversationPanel)
                panel.append_entry(make_dot_line(DOT_COLORS["error"], f"Failed to copy: {error_msg}"))
            except Exception:
                logger.debug("Failed to show copy error message")

    async def action_focus_input(self) -> None:
        """Focus the chat input field."""
        with contextlib.suppress(Exception):
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.focus()

    async def action_toggle_plan(self) -> None:
        """Toggle plan tree visibility."""
        try:
            plan_tree = self.query_one("#plan-tree", PlanTree)
            # Only allow toggling if there's an active plan (Bug #2)
            if not self._state.current_plan:
                return
            plan_tree.toggle_class("visible")
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

    cmd = [sys.executable, "-m", "soothe.daemon", "--detached"]
    if config_path:
        cmd.extend(["--config", config_path])
    log_file = Path(SOOTHE_HOME).expanduser() / "logs" / "daemon.stderr"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stderr_file = log_file.open("a", encoding="utf-8")
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        start_new_session=True,
    )
    stderr_file.close()

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
