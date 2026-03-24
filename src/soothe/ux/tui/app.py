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
from rich.markdown import Markdown
from rich.panel import Panel
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container

from soothe.config import SOOTHE_HOME, SootheConfig
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
        max-height: 10;
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
        self._history_loaded_thread_id: str | None = None
        self._last_activity_count = 0
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
            yield PlanTree(id="plan-tree", classes="visible" if self._state.plan_visible else "")
            yield InfoBar("Thread: -  Events: 0  Idle", id="info-bar")
            with Container(id="chat-input-row"):
                from textual.widgets import Static

                yield Static(">", id="chat-prompt")
                yield ChatInput(id="chat-input")

    async def on_mount(self) -> None:
        """Connect to daemon on startup."""
        with contextlib.suppress(Exception):
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.focus()

        # Don't render history here - wait for daemon connection and thread_resumed event
        # to ensure the widget tree is fully ready.
        if self._thread_id:
            self._state.thread_id = self._thread_id
            self._load_thread_history(self._thread_id)
            self._history_loaded_thread_id = self._thread_id
            # Rendering will happen when daemon sends thread_resumed=True
            self._update_status_bar("Idle")

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

                tid_raw = event.get("thread_id", self._state.thread_id)
                tid = self._state.thread_id if tid_raw in (None, "") else str(tid_raw)
                previous_thread_id = self._thread_id

                # Clear local history only on explicit new-thread signal.
                if event.get("new_thread", False):
                    # Starting a fresh thread, clear previous conversation
                    self._thread_id = tid or None
                    self._history_loaded_thread_id = tid or None
                    self._conversation_history.clear()
                    self._message_history.clear()
                    self._state.full_response.clear()
                    self._state.activity_lines.clear()
                    # Don't load old input history for new threads
                    with contextlib.suppress(Exception):
                        panel = self.query_one("#conversation", ConversationPanel)
                        panel.clear()
                elif tid and (tid != previous_thread_id or thread_resumed or tid != self._history_loaded_thread_id):
                    # Thread switch or resume - load input history
                    history = event.get("input_history", [])
                    if history:
                        chat_input = self.query_one("#chat-input", ChatInput)
                        chat_input.set_history(history)

                    # Thread switch or explicit resume - load history from disk
                    self._thread_id = tid

                    # Load history from disk when we have a thread_id (either resume or first assignment)
                    # Skip loading if this is a post-query thread change (was_running and not resumed)
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
                        self._history_loaded_thread_id = tid
                    else:
                        # Explicit thread switch (initial connect, resume):
                        # reload history from disk.
                        self._load_thread_history(tid)
                        self._history_loaded_thread_id = tid
                        self._render_history_to_conversation_panel()

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

    def _render_history_to_conversation_panel(self) -> None:
        """Render loaded conversation history into the conversation panel."""
        try:
            # Reuse the standard conversation repaint pipeline to keep
            # resume rendering consistent with normal turn-end rendering.
            self._state.full_response.clear()
            self._append_conversation()
            panel = self.query_one("#conversation", ConversationPanel)
            panel.refresh(layout=True)
            self.refresh(layout=True)
            self._flush_new_activity()
        except Exception:
            logger.exception("Failed to render thread history")

    def _load_thread_history(self, thread_id: str) -> None:
        """Load conversation and activity history for a thread.

        Searches both 'sessions' and 'threads' directories for backward compatibility.
        Falls back to extracting conversation from LangGraph checkpoint if conversation.jsonl doesn't exist.

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

        try:
            # Load recent conversation history
            conversations = self._thread_logger.recent_conversation(limit=50)

            # Fallback: Load from LangGraph checkpoint if conversation.jsonl is empty or missing
            if not conversations:
                conversations = self._load_conversation_from_checkpoint(thread_id)
            else:
                # Partial fallback: some legacy logs include user turns but miss assistant turns.
                has_assistant = any(
                    c.get("role") == "assistant" and str(c.get("text", "")).strip() for c in conversations
                )
                if not has_assistant:
                    checkpoint_conversations = self._load_conversation_from_checkpoint(thread_id)
                    conversations.extend([c for c in checkpoint_conversations if c.get("role") == "assistant"])

                    from soothe.core.events import CHITCHAT_RESPONSE, FINAL_REPORT
                    from soothe.ux.shared.message_processing import strip_internal_tags

                    # Recover assistant output from custom output events if needed.
                    for record in self._thread_logger.recent_actions(limit=300):
                        data = record.get("data", {})
                        if not isinstance(data, dict):
                            continue
                        event_type = str(data.get("type", ""))
                        recovered_text = ""
                        if event_type == CHITCHAT_RESPONSE:
                            recovered_text = strip_internal_tags(str(data.get("content", ""))).strip()
                        elif event_type == FINAL_REPORT:
                            recovered_text = strip_internal_tags(str(data.get("summary", ""))).strip()
                        if recovered_text:
                            conversations.append({"role": "assistant", "text": recovered_text})

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

    def _load_conversation_from_checkpoint(self, thread_id: str) -> list[dict[str, Any]]:
        """Load conversation history from LangGraph checkpoint as fallback.

        This method extracts user and assistant messages from the checkpoint.json file
        when conversation.jsonl is missing or empty.

        Args:
            thread_id: Thread ID to load checkpoint for.

        Returns:
            List of conversation records with 'role' and 'text' fields.
        """
        from pathlib import Path

        from soothe.config import SOOTHE_HOME

        checkpoint_path = Path(SOOTHE_HOME) / "runs" / thread_id / "checkpoint.json"
        if not checkpoint_path.exists():
            logger.debug("No checkpoint found at %s", checkpoint_path)
            return []

        try:
            import json

            with checkpoint_path.open(encoding="utf-8") as f:
                checkpoint_data = json.load(f)

            # Extract conversation from checkpoint structure
            conversations = []

            # Try to extract from 'last_query' and plan steps
            last_query = checkpoint_data.get("last_query", "")
            if last_query:
                conversations.append(
                    {
                        "role": "user",
                        "text": last_query,
                    }
                )

            # Extract assistant responses from completed plan steps
            plan = checkpoint_data.get("plan", {})
            steps = plan.get("steps", [])
            for step in steps:
                if step.get("status") == "completed" and step.get("result"):
                    result_text = step["result"]
                    if result_text.strip():
                        conversations.append(
                            {
                                "role": "assistant",
                                "text": result_text,
                            }
                        )

            logger.info(
                "Loaded %d conversations from checkpoint for thread %s",
                len(conversations),
                thread_id,
            )
        except Exception:
            logger.debug("Failed to load checkpoint for thread %s", thread_id, exc_info=True)
            return []
        else:
            return conversations

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
            with contextlib.suppress(Exception):
                conv_panel = self.query_one("#conversation", ConversationPanel)
                conv_panel.write(text)

    def _append_conversation(self) -> None:
        """Rewrite the conversation panel with history + accumulated streaming text."""
        try:
            panel = self.query_one("#conversation", ConversationPanel)
            response_text = "".join(self._state.full_response)

            # Clear panel only if it has content (skip clear on fresh panel to avoid init issues)
            # RichLog doesn't expose a direct way to check if empty, but clear() on empty is safe
            panel.clear()

            # Always show conversation history, even if response is empty
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
        except Exception:
            logger.exception("Failed to append conversation to panel")

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
