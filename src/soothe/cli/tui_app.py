"""Textual-based TUI for Soothe (RFC-0003 revised).

Three-row layout:
  Row 1 -- Conversation (left) | Plan + Activity (right)
  Row 2 -- Info bar (thread, events, subagent status)
  Row 3 -- Chat input with UP/DOWN history navigation

Connects to the Soothe daemon over a Unix domain socket for event
streaming and user input.  When the daemon is not already running,
``run_textual_tui`` starts it in-process on a background thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.events import Key
from textual.widgets import Footer, Header, Input, RichLog, Static

from soothe.cli.daemon import DaemonClient, SootheDaemon, socket_path
from soothe.cli.tui import (
    TuiState,
    _add_activity,
    _handle_protocol_event,
    _handle_subagent_custom,
    render_plan_tree,
)
from soothe.config import SootheConfig

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

    BINDINGS = [
        Binding("ctrl+d", "detach", "Detach"),
        Binding("ctrl+q", "quit_app", "Quit"),
    ]

    def __init__(
        self,
        config: SootheConfig | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._config = config or SootheConfig()
        self._thread_id = thread_id
        self._client: DaemonClient | None = None
        self._state = TuiState()
        self._connected = False
        self._conversation_history: list[str] = []
        self._last_activity_count = 0

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
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.focus()
        except Exception:
            pass

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
            self._state.thread_id = tid
            self._update_status(state)

        elif msg_type == "event":
            namespace = tuple(msg.get("namespace", []))
            mode = msg.get("mode", "")
            data = msg.get("data", {})
            is_main = not namespace

            if mode == "messages" and is_main:
                self._handle_messages_event(data)
            elif mode == "custom":
                if isinstance(data, dict):
                    etype = data.get("type", "")
                    if etype.startswith("soothe."):
                        _handle_protocol_event(data, self._state)
                        self._flush_new_activity()
                        if "plan" in etype:
                            self._refresh_plan()
                    elif not is_main:
                        _handle_subagent_custom(namespace, data, self._state)
                        self._flush_new_activity()
                        self._update_status("Running")

    def _handle_messages_event(self, data: Any) -> None:
        if isinstance(data, (list, tuple)) and len(data) == _MSG_PAIR_LEN:
            msg, metadata = data
        elif isinstance(data, dict):
            return
        else:
            return

        if metadata and isinstance(metadata, dict) and metadata.get("lc_source") == "summarization":
            return

        # Handle LangChain objects (in-process)
        if isinstance(msg, AIMessage):
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
                        if text:
                            self._state.full_response.append(text)
                            self._append_conversation(text)
                    elif btype in ("tool_call_chunk", "tool_call"):
                        name = block.get("name", "")
                        if name:
                            _add_activity(self._state, Text.assemble(("  . ", "dim"), (f"Calling {name}", "blue")))
                            self._flush_new_activity()
            elif isinstance(msg.content, str) and msg.content:
                self._state.full_response.append(msg.content)
                self._append_conversation(msg.content)

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
                elif isinstance(content, str) and content:
                    self._state.full_response.append(content)
                    self._append_conversation(content)

            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    if text:
                        self._state.full_response.append(text)
                        self._append_conversation(text)
                elif btype in ("tool_call_chunk", "tool_call"):
                    name = block.get("name", "")
                    if name:
                        _add_activity(self._state, Text.assemble(("  . ", "dim"), (f"Calling {name}", "blue")))
                        self._flush_new_activity()

            if has_tool_chunks:
                for tc in tool_call_chunks:
                    if isinstance(tc, dict):
                        name = tc.get("name", "")
                        if name:
                            _add_activity(self._state, Text.assemble(("  . ", "dim"), (f"Calling {name}", "blue")))
                            self._flush_new_activity()

        # Handle ToolMessage objects
        if isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "tool")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            brief = content.replace("\n", " ")[:80]
            _add_activity(
                self._state, Text.assemble(("  > ", "dim green"), (tool_name, "green"), ("  ", ""), (brief, "dim"))
            )
            self._flush_new_activity()

    # -- UI helpers ---------------------------------------------------------

    def _log_conversation(self, text: str) -> None:
        self._conversation_history.append(text)
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            panel.write(text)
        except Exception:
            pass

    def _append_conversation(self, text: str) -> None:
        """Rewrite the conversation panel with history + accumulated streaming text."""
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            response_text = "".join(self._state.full_response)
            if not response_text:
                return
            panel.clear()
            for entry in self._conversation_history:
                panel.write(entry)
            panel.write(response_text, scroll_end=True)
        except Exception:
            pass

    def _flush_new_activity(self) -> None:
        """Append only new activity lines (append-only, no clear)."""
        try:
            panel = self.query_one("#activity-panel", ActivityPanel)
            new_lines = self._state.activity_lines[self._last_activity_count :]
            for line in new_lines:
                panel.write(line)
            self._last_activity_count = len(self._state.activity_lines)
        except Exception:
            pass

    def _refresh_plan(self) -> None:
        try:
            panel = self.query_one("#plan-panel", PlanPanel)
            panel.clear()
            if self._state.current_plan:
                tree = render_plan_tree(self._state.current_plan)
                panel.write(tree)
            else:
                panel.write("[dim]No active plan.[/dim]")
        except Exception:
            pass

    def _update_status(self, state: str) -> None:
        try:
            bar = self.query_one("#info-bar", InfoBar)
            tid = self._state.thread_id or "-"
            events = len(self._state.activity_lines)
            subagent_lines = self._state.subagent_tracker.render()
            sub_summary = ""
            if subagent_lines:
                last = subagent_lines[-1]
                sub_summary = f"  |  {last.plain}" if hasattr(last, "plain") else ""
            bar.update(f"Thread: {tid}  Events: {events}  {state.title()}{sub_summary}")
        except Exception:
            pass

    # -- input handling -----------------------------------------------------

    @on(Input.Submitted, "#chat-input")
    async def on_chat_submit(self, event: Input.Submitted) -> None:
        """Handle chat input submission."""
        text = event.value.strip()
        if not text:
            return
        event.input.clear()

        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.add_to_history(text)
        except Exception:
            pass

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
            await self._client.send_command(text.strip())
        else:
            self._log_conversation("[bold green]Assistant:[/bold green] ")
            await self._client.send_input(text)

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
# In-process daemon thread
# ---------------------------------------------------------------------------

_daemon_thread: threading.Thread | None = None
_daemon_instance: SootheDaemon | None = None


def _start_daemon_in_background(config: SootheConfig) -> None:
    """Start the daemon on a background thread if not already running."""
    global _daemon_thread, _daemon_instance  # noqa: PLW0603

    if SootheDaemon.is_running():
        return
    if _daemon_thread is not None and _daemon_thread.is_alive():
        return

    _daemon_instance = SootheDaemon(config)

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_daemon_instance.start())
            loop.run_until_complete(_daemon_instance.serve_forever())
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except Exception:
            logger.exception("Daemon thread error")
        finally:
            try:
                loop.run_until_complete(_daemon_instance.stop())
            except Exception:
                pass
            loop.close()

    _daemon_thread = threading.Thread(target=_run, daemon=True, name="soothe-daemon")
    _daemon_thread.start()

    import time

    for _ in range(40):
        time.sleep(0.25)
        if socket_path().exists():
            break


def _stop_background_daemon() -> None:
    """Stop the in-process daemon if we started one."""
    global _daemon_thread, _daemon_instance  # noqa: PLW0603
    if _daemon_instance is not None:
        _daemon_instance.request_stop()
        _daemon_instance = None
    if _daemon_thread is not None:
        _daemon_thread.join(timeout=5)
        _daemon_thread = None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_textual_tui(
    config: SootheConfig | None = None,
    *,
    thread_id: str | None = None,
) -> None:
    """Launch the Textual-based TUI.

    Args:
        config: Soothe configuration.
        thread_id: Optional thread ID to resume.
    """
    cfg = config or SootheConfig()
    _start_daemon_in_background(cfg)
    try:
        app = SootheApp(config=cfg, thread_id=thread_id)
        app.run()
    finally:
        _stop_background_daemon()
