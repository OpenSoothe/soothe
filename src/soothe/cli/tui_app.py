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
from typing import TYPE_CHECKING, Any, ClassVar

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from soothe.cli.commands import parse_autonomous_command
from soothe.cli.daemon import DaemonClient, SootheDaemon, socket_path
from soothe.cli.progress_verbosity import classify_custom_event, should_show
from soothe.cli.thread_logger import ThreadLogger
from soothe.cli.tui_shared import (
    TuiState,
    _handle_generic_custom_activity,
    _handle_protocol_event,
    _handle_subagent_custom,
    _handle_subagent_text_activity,
    _handle_tool_call_activity,
    _handle_tool_result_activity,
    _resolve_namespace_label,
    _update_name_map_from_ai_message,
    render_plan_tree,
)
from soothe.config import SootheConfig

if TYPE_CHECKING:
    from textual.events import Key

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2


# ---------------------------------------------------------------------------
# Textual widgets
# ---------------------------------------------------------------------------


class ConversationPanel(RichLog):
    """Scrollable chat history with markdown rendering."""


class PlanPanel(RichLog):
    """Plan tree display."""


class ActivityPanel(RichLog):
    """Scrollable activity log with configurable max lines."""


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


# ---------------------------------------------------------------------------
# SootheApp
# ---------------------------------------------------------------------------


class SootheApp(App):
    """Textual application for the Soothe TUI."""

    TITLE = "Soothe"
    CSS = """
    #main-layout {
        layout: grid;
        grid-size: 2 1;
        grid-columns: 3fr 2fr;
        grid-rows: 1fr;
        height: 1fr;
    }
    #conversation {
        border: solid $primary;
    }
    #right-col {
        height: 100%;
    }
    #plan-panel {
        height: 2fr;
        border: solid $accent;
        border-bottom: dashed $surface;
    }
    #activity-panel {
        height: 3fr;
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
        dock: bottom;
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

    def compose(self) -> ComposeResult:
        """Build the widget tree: 3-row layout."""
        max_lines = self._config.activity_max_lines
        yield Header()
        with Container(id="main-layout"):
            yield ConversationPanel(
                id="conversation",
                highlight=True,
                markup=True,
                wrap=True,
            )
            with Vertical(id="right-col"):
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
        yield InfoBar("Thread: -  Events: 0  Idle", id="info-bar")
        yield ChatInput(placeholder="soothe> Type a message or /help", id="chat-input")
        yield Footer()

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
            self._process_daemon_event(event)
            await asyncio.sleep(0)

    # -- event processing ---------------------------------------------------

    def _process_daemon_event(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type", "")

        if msg_type == "status":
            state = msg.get("state", "unknown")
            tid = msg.get("thread_id", self._state.thread_id)
            previous_thread_id = self._state.thread_id
            self._state.thread_id = tid

            # Load thread history when thread_id is first received or changes
            if tid and tid != previous_thread_id:
                self._load_thread_history(tid)
                # Refresh the conversation panel with loaded history
                with contextlib.suppress(Exception):
                    panel = self.query_one("#conversation", ConversationPanel)
                    panel.clear()
                    for entry in self._conversation_history:
                        panel.write(entry)
                    # Also refresh activity panel
                    self._flush_new_activity()

            self._update_status(state)
            # Only render assistant output in conversation at turn end.
            if state in {"idle", "stopped"} and self._state.full_response:
                self._append_conversation()

        elif msg_type == "command_response":
            # Display command output in conversation panel
            content = msg.get("content", "")
            if content:
                self._log_conversation(content)

        elif msg_type == "event":
            namespace = tuple(msg.get("namespace", []))
            mode = msg.get("mode", "")
            data = msg.get("data", {})
            is_main = not namespace

            if mode == "messages":
                self._handle_messages_event(data, namespace=namespace)
            elif mode == "custom" and isinstance(data, dict):
                category = classify_custom_event(namespace, data)
                if category == "protocol" and should_show(category, self._progress_verbosity):
                    _handle_protocol_event(data, self._state, verbosity=self._progress_verbosity)
                    self._flush_new_activity()
                    etype = data.get("type", "")
                    if "plan" in etype:
                        self._refresh_plan()
                elif category == "subagent_custom" and not is_main:
                    _handle_subagent_custom(
                        namespace,
                        data,
                        self._state,
                        verbosity=self._progress_verbosity,
                    )
                    self._flush_new_activity()
                    self._update_status("Running")
                elif category == "error" and should_show("error", self._progress_verbosity):
                    _handle_protocol_event(data, self._state, verbosity="normal")
                    self._flush_new_activity()
                elif should_show(category, self._progress_verbosity):
                    _handle_generic_custom_activity(
                        namespace,
                        data,
                        self._state,
                        verbosity=self._progress_verbosity,
                    )
                    self._flush_new_activity()

    def _handle_messages_event(self, data: Any, *, namespace: tuple[str, ...]) -> None:
        if isinstance(data, (list, tuple)) and len(data) == _MSG_PAIR_LEN:
            msg, metadata = data
        elif isinstance(data, dict):
            return
        else:
            return

        if metadata and isinstance(metadata, dict) and metadata.get("lc_source") == "summarization":
            return

        is_main = not namespace
        prefix = _resolve_namespace_label(namespace, self._state) if namespace else None

        # Handle LangChain objects (in-process)
        if isinstance(msg, AIMessage):
            _update_name_map_from_ai_message(self._state, msg)
            msg_id = msg.id or ""
            if not isinstance(msg, AIMessageChunk):
                if msg_id in self._state.seen_message_ids:
                    return
                self._state.seen_message_ids.add(msg_id)
            elif msg_id:
                self._state.seen_message_ids.add(msg_id)

            if hasattr(msg, "content_blocks") and msg.content_blocks:
                for block in msg.content_blocks:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text = block.get("text", "")
                        if text and should_show("assistant_text", self._progress_verbosity):
                            if is_main:
                                self._state.full_response.append(text)
                            else:
                                _handle_subagent_text_activity(
                                    namespace,
                                    text,
                                    self._state,
                                    verbosity=self._progress_verbosity,
                                )
                                self._flush_new_activity()
                    elif btype in ("tool_call_chunk", "tool_call"):
                        name = block.get("name", "")
                        _handle_tool_call_activity(
                            self._state,
                            name,
                            prefix=prefix,
                            verbosity=self._progress_verbosity,
                        )
                        self._flush_new_activity()
            elif (
                is_main
                and isinstance(msg.content, str)
                and msg.content
                and should_show("assistant_text", self._progress_verbosity)
            ):
                self._state.full_response.append(msg.content)

        # Handle deserialized dict (after JSON transport)
        elif isinstance(msg, dict):
            msg_id = msg.get("id", "")
            is_chunk = msg.get("type") == "AIMessageChunk"

            if not is_chunk:
                if msg_id and msg_id in self._state.seen_message_ids:
                    return
                if msg_id:
                    self._state.seen_message_ids.add(msg_id)
            elif msg_id:
                self._state.seen_message_ids.add(msg_id)

            tool_call_chunks = msg.get("tool_call_chunks", [])
            has_tool_chunks = isinstance(tool_call_chunks, list) and len(tool_call_chunks) > 0

            blocks = msg.get("content_blocks") or []
            if not blocks:
                content = msg.get("content", "")
                if isinstance(content, list):
                    blocks = content
                elif (
                    is_main
                    and isinstance(content, str)
                    and content
                    and should_show("assistant_text", self._progress_verbosity)
                ):
                    self._state.full_response.append(content)

            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    if text and should_show("assistant_text", self._progress_verbosity):
                        if is_main:
                            self._state.full_response.append(text)
                        else:
                            _handle_subagent_text_activity(
                                namespace,
                                text,
                                self._state,
                                verbosity=self._progress_verbosity,
                            )
                            self._flush_new_activity()
                elif btype in ("tool_call_chunk", "tool_call"):
                    name = block.get("name", "")
                    _handle_tool_call_activity(
                        self._state,
                        name,
                        prefix=prefix,
                        verbosity=self._progress_verbosity,
                    )
                    self._flush_new_activity()

            if has_tool_chunks:
                for tc in tool_call_chunks:
                    if isinstance(tc, dict):
                        name = tc.get("name", "")
                        _handle_tool_call_activity(
                            self._state,
                            name,
                            prefix=prefix,
                            verbosity=self._progress_verbosity,
                        )
                        self._flush_new_activity()

        # Handle ToolMessage objects
        if isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "tool")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            _handle_tool_result_activity(
                self._state,
                tool_name,
                content,
                prefix=prefix,
                verbosity=self._progress_verbosity,
            )
            self._flush_new_activity()

    # -- UI helpers ---------------------------------------------------------

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

        # Try both directories for backward compatibility
        from pathlib import Path

        from soothe.config import SOOTHE_HOME

        sessions_dir = Path(SOOTHE_HOME) / "sessions"
        threads_dir = Path(SOOTHE_HOME) / "threads"

        # Try sessions first (preferred for backward compatibility), then threads
        # Use file existence check instead of reading the entire file
        for directory in [sessions_dir, threads_dir]:
            log_file = directory / f"{thread_id}.jsonl"
            if log_file.exists():
                try:
                    self._thread_logger = ThreadLogger(
                        thread_dir=str(directory),
                        thread_id=thread_id,
                        retention_days=self._config.logging.thread_logging.retention_days,
                        max_size_mb=self._config.logging.thread_logging.max_size_mb,
                    )
                    logger.info("Found thread history in %s for thread %s", directory, thread_id)
                    break
                except Exception:
                    logger.debug("Failed to load thread history from %s", directory, exc_info=True)
                    continue
        else:
            # No data found, use default directory
            self._thread_logger = ThreadLogger(
                thread_dir=self._config.logging.thread_logging.dir,
                thread_id=thread_id,
                retention_days=self._config.logging.thread_logging.retention_days,
                max_size_mb=self._config.logging.thread_logging.max_size_mb,
            )
            logger.info("No existing history found for thread %s, using default directory", thread_id)

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
                    category = classify_custom_event(tuple(namespace), data)
                    if should_show(category, self._progress_verbosity):
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
            if not response_text:
                return
            panel.clear()
            for entry in self._conversation_history:
                panel.write(entry)
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
