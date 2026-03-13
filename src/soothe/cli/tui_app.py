"""Textual-based TUI for Soothe (RFC-0003 revised).

Always-on two-column layout with integrated chat input, conversation history,
plan/activity/subagent panels.  Connects to the Soothe daemon over a Unix
domain socket for event streaming and user input.

When the daemon is not already running, ``run_textual_tui`` starts it
in-process on a background thread so no external ``soothe`` binary is needed.
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
    """Recent action lines."""


class SubagentPanel(RichLog):
    """Active subagent status."""


class StatusBar(Static):
    """Bottom status line."""


# ---------------------------------------------------------------------------
# SootheApp
# ---------------------------------------------------------------------------


class SootheApp(App):
    """Textual application for the Soothe TUI.

    Args:
        config: Soothe configuration.
        thread_id: Optional thread ID to resume.
    """

    TITLE = "Soothe"
    CSS = """
    #main-layout {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 3fr 2fr;
        grid-rows: 3fr 2fr;
    }
    #conversation {
        row-span: 1;
        column-span: 2;
        border: solid $primary;
    }
    #left-sidebar {
        border: solid $accent;
    }
    #right-sidebar {
        border: solid $accent;
    }
    #plan-panel {
        height: 1fr;
        border-bottom: dashed $surface;
    }
    #subagent-panel {
        height: 1fr;
    }
    #activity-panel {
        height: 1fr;
    }
    #status-bar {
        dock: bottom;
        height: 1;
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

    def compose(self) -> ComposeResult:
        """Build the widget tree."""
        yield Header()
        with Container(id="main-layout"):
            yield ConversationPanel(id="conversation", highlight=True, markup=True, wrap=True)
            with Vertical(id="left-sidebar"):
                yield PlanPanel(id="plan-panel", highlight=True, markup=True, wrap=True)
                yield SubagentPanel(id="subagent-panel", highlight=True, markup=True, wrap=True)
            yield ActivityPanel(id="right-sidebar", highlight=True, markup=True, wrap=True)
        yield StatusBar("Thread: -  Events: 0  Idle", id="status-bar")
        yield Input(placeholder="soothe> Type a message or /help", id="chat-input")
        yield Footer()

    async def on_mount(self) -> None:
        """Connect to daemon on startup."""
        # Focus the chat input so users can start typing immediately
        try:
            chat_input = self.query_one("#chat-input", Input)
            chat_input.focus()
        except Exception:
            pass

        self.run_worker(self._connect_and_listen(), exclusive=True)

    async def _connect_and_listen(self) -> None:
        """Connect to daemon and process events.

        Retries a few times to allow the daemon (which may have been started
        on a background thread) to bind its socket.
        """
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
                        self._refresh_activity()
                        if "plan" in etype:
                            self._refresh_plan()
                    elif not is_main:
                        _handle_subagent_custom(namespace, data, self._state)
                        self._refresh_subagents()
                        self._refresh_activity()

    def _handle_messages_event(self, data: Any) -> None:
        # Data may be a tuple/list after JSON deserialization
        if isinstance(data, (list, tuple)) and len(data) == _MSG_PAIR_LEN:
            msg, metadata = data
        elif isinstance(data, dict):
            # Handle dict case
            return
        else:
            return

        # Check metadata for summarization
        if metadata and isinstance(metadata, dict) and metadata.get("lc_source") == "summarization":
            return

        # Handle LangChain objects (when running in same process)
        if isinstance(msg, AIMessage) and hasattr(msg, "content_blocks"):
            msg_id = msg.id or ""
            if not isinstance(msg, AIMessageChunk):
                if msg_id in self._state.seen_message_ids:
                    return
                self._state.seen_message_ids.add(msg_id)
            elif msg_id:
                self._state.seen_message_ids.add(msg_id)

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
                        self._refresh_activity()

        # Handle deserialized dict (after JSON transport)
        elif isinstance(msg, dict):
            msg_id = msg.get("id", "")
            content_blocks = msg.get("content_blocks", [])

            # Track seen messages
            chunks = msg.get("chunks", [])
            is_chunk = isinstance(chunks, list) and len(chunks) > 0
            if not is_chunk:
                if msg_id and msg_id in self._state.seen_message_ids:
                    return
                if msg_id:
                    self._state.seen_message_ids.add(msg_id)
            elif msg_id:
                self._state.seen_message_ids.add(msg_id)

            # Extract text from content blocks
            for block in content_blocks:
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
                        self._refresh_activity()

        # Handle ToolMessage objects
        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "tool")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            brief = content.replace("\n", " ")[:80]
            _add_activity(
                self._state, Text.assemble(("  > ", "dim green"), (tool_name, "green"), ("  ", ""), (brief, "dim"))
            )
            self._refresh_activity()

    # -- UI helpers ---------------------------------------------------------

    def _log_conversation(self, text: str) -> None:
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            panel.write(text)
        except Exception:
            pass

    def _append_conversation(self, text: str) -> None:
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            panel.write(text, scroll_end=True)
        except Exception:
            pass

    def _refresh_activity(self) -> None:
        try:
            panel = self.query_one("#right-sidebar", ActivityPanel)
            panel.clear()
            for line in self._state.activity_lines[-15:]:
                panel.write(line)
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

    def _refresh_subagents(self) -> None:
        try:
            panel = self.query_one("#subagent-panel", SubagentPanel)
            panel.clear()
            lines = self._state.subagent_tracker.render()
            if lines:
                for line in lines[-5:]:
                    panel.write(line)
            else:
                panel.write("[dim]No active subagents.[/dim]")
        except Exception:
            pass

    def _update_status(self, state: str) -> None:
        try:
            bar = self.query_one("#status-bar", StatusBar)
            tid = self._state.thread_id or "-"
            events = len(self._state.activity_lines)
            bar.update(f"Thread: {tid}  Events: {events}  {state.title()}")
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
    """Start the daemon on a background thread if not already running.

    Uses an in-process asyncio event loop on a daemon thread so no external
    ``soothe`` binary needs to be installed on PATH.
    """
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

    Starts the Soothe daemon in-process on a background thread if not
    already running, then launches the Textual app.

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
