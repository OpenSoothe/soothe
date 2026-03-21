"""TUI event processing functions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, ToolMessage

from soothe.cli.message_processing import (
    MessageProcessor,
    OutputFormatter,
    extract_tool_brief,
    strip_internal_tags,
)
from soothe.cli.progress_verbosity import classify_custom_event, should_show
from soothe.cli.tui.renderers import (
    _handle_generic_custom_activity,
    _handle_protocol_event,
    _handle_subagent_custom,
    _handle_subagent_progress,
    _handle_subagent_text_activity,
    _handle_tool_call_activity,
    _handle_tool_result_activity,
)
from soothe.cli.tui.state import TuiState
from soothe.cli.tui_shared import _resolve_namespace_label

if TYPE_CHECKING:
    from soothe.cli.tui.widgets import ActivityInfo

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2


class _TuiOutputFormatter(OutputFormatter):
    """TUI output formatter for activity panel."""

    def __init__(self, state: TuiState) -> None:
        """Initialize TUI output formatter.

        Args:
            state: TUI state for accessing activity lines.
        """
        self.state = state

    def emit_assistant_text(self, text: str, *, is_main: bool) -> None:
        """Emit assistant text.

        For TUI, main agent text goes to full_response (handled by MessageProcessor),
        and subagent text gets added to activity panel.

        Args:
            text: The assistant text to emit.
            is_main: Whether this is from the main agent.
        """
        # For main agent, text is already in full_response (handled by MessageProcessor)
        # For subagents, add to activity panel as brief summary
        if not is_main:
            brief = text.replace("\n", " ")[:80]
            from rich.text import Text

            from soothe.cli.tui.renderers import _add_activity_from_event

            _add_activity_from_event(
                self.state,
                Text.assemble(("  ", ""), ("[subagent] ", "magenta"), (f"Text: {brief}", "dim")),
                {},
            )

    def emit_tool_call(
        self,
        name: str,
        *,
        prefix: str | None,
        is_main: bool,  # noqa: FBT001, ARG002
        tool_call: dict[str, Any] | None = None,
    ) -> None:
        """Emit a tool call notification.

        Args:
            name: The tool name being called.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent (unused in TUI).
            tool_call: Optional tool call dict with args for display.
        """
        _handle_tool_call_activity(self.state, name, prefix=prefix, verbosity="normal", tool_call=tool_call)

    def emit_tool_result(self, tool_name: str, brief: str, *, prefix: str | None, is_main: bool) -> None:  # noqa: ARG002
        """Emit a tool result notification.

        Args:
            tool_name: The tool name that produced the result.
            brief: Brief summary of the result.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent (unused in TUI).
        """
        _handle_tool_result_activity(self.state, tool_name, brief, prefix=prefix, verbosity="normal")


def process_daemon_event(
    msg: dict[str, Any],
    state: TuiState,
    activity_panel: ActivityInfo | None = None,  # noqa: ARG001
    *,
    verbosity: str = "normal",
    on_status_update: callable | None = None,
    on_conversation_append: callable | None = None,
    on_plan_refresh: callable | None = None,
) -> None:
    """Process a daemon event and update state.

    Args:
        msg: Daemon event message.
        state: TUI state to update.
        activity_panel: Activity info widget (optional, for backward compatibility).
        verbosity: Progress verbosity level.
        on_status_update: Callback for status updates.
        on_conversation_append: Callback for conversation append.
        on_plan_refresh: Callback for plan refresh.
    """
    msg_type = msg.get("type", "")

    if msg_type == "status":
        state_str = msg.get("state", "unknown")
        tid = msg.get("thread_id", state.thread_id)
        previous_thread_id = state.thread_id
        state.thread_id = tid

        if tid and tid != previous_thread_id:
            # Thread ID changed - caller should handle loading history
            pass

        if on_status_update:
            on_status_update(state_str)

        # Only render assistant output in conversation at turn end.
        if state_str in {"idle", "stopped"} and state.full_response and on_conversation_append:
            on_conversation_append()

    elif msg_type == "command_response":
        # Display command output in conversation panel
        msg.get("content", "")
        # Caller handles displaying command response

    elif msg_type == "event":
        namespace = tuple(msg.get("namespace", []))
        mode = msg.get("mode", "")
        data = msg.get("data", {})
        is_main = not namespace

        if mode == "messages":
            handle_messages_event(data, state, namespace=namespace, verbosity=verbosity)
        elif mode == "custom" and isinstance(data, dict):
            category = classify_custom_event(namespace, data)
            etype = data.get("type", "")

            # Check for multi-step plan creation
            from soothe.core.events import PLAN_CREATED

            if etype == PLAN_CREATED and len(data.get("steps", [])) > 1:
                state.multi_step_active = True

            # Plan state must always be updated regardless of verbosity
            if category == "protocol" and "plan" in etype:
                _handle_protocol_event(data, state, verbosity="normal")
                if on_plan_refresh:
                    on_plan_refresh()
            elif category == "protocol" and should_show(category, verbosity):
                _handle_protocol_event(data, state, verbosity=verbosity)
                if "plan" in etype and on_plan_refresh:
                    on_plan_refresh()
            elif category == "subagent_progress" and should_show(category, verbosity):
                _handle_subagent_progress(namespace, data, state, verbosity=verbosity)
                if on_status_update:
                    on_status_update("Running")
            elif category == "subagent_custom" and not is_main:
                _handle_subagent_custom(namespace, data, state, verbosity=verbosity)
                if on_status_update:
                    on_status_update("Running")
            elif category == "assistant_text":
                _handle_protocol_event(data, state, verbosity=verbosity)
                if on_conversation_append:
                    on_conversation_append()
            elif category == "error" and should_show("error", verbosity):
                _handle_protocol_event(data, state, verbosity="normal")
            elif should_show(category, verbosity):
                _handle_generic_custom_activity(namespace, data, state, verbosity=verbosity)


def handle_messages_event(
    data: Any,
    state: TuiState,
    *,
    namespace: tuple[str, ...],
    verbosity: str = "normal",
) -> None:
    """Handle messages event and update state.

    Args:
        data: Event data (message and metadata).
        state: TUI state to update.
        namespace: Event namespace tuple.
        verbosity: Progress verbosity level.
    """
    if isinstance(data, (list, tuple)) and len(data) == _MSG_PAIR_LEN:
        msg, metadata = data
    elif isinstance(data, dict):
        return
    else:
        return

    if metadata and isinstance(metadata, dict) and metadata.get("lc_source") == "summarization":
        return

    is_main = not namespace
    prefix = _resolve_namespace_label(namespace, state) if namespace else None

    # Use shared MessageProcessor for LangChain objects
    if isinstance(msg, AIMessage):
        formatter = _TuiOutputFormatter(state)
        processor = MessageProcessor(state.shared, formatter)
        processor.process_ai_message(msg, is_main=is_main, verbosity=verbosity)
        return

    # Handle ToolMessage objects
    if isinstance(msg, ToolMessage):
        tool_name = getattr(msg, "name", "tool")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        brief = extract_tool_brief(tool_name, content)
        _handle_tool_result_activity(state, tool_name, brief, prefix=prefix, verbosity=verbosity)
        return

    # Handle deserialized dict (after JSON transport)
    # This path is kept for backward compatibility with daemon events
    if isinstance(msg, dict):
        msg_id = msg.get("id", "")
        is_chunk = msg.get("type") == "AIMessageChunk"

        if not is_chunk:
            if msg_id and msg_id in state.seen_message_ids:
                return
            if msg_id:
                state.seen_message_ids.add(msg_id)
        elif msg_id:
            state.seen_message_ids.add(msg_id)

        tool_call_chunks = msg.get("tool_call_chunks", [])
        has_tool_chunks = isinstance(tool_call_chunks, list) and len(tool_call_chunks) > 0

        blocks = msg.get("content_blocks") or []
        if not blocks:
            content = msg.get("content", "")
            if isinstance(content, list):
                blocks = content
            elif is_main and isinstance(content, str) and content and should_show("assistant_text", verbosity):
                cleaned = strip_internal_tags(content)
                if cleaned:
                    state.full_response.append(cleaned)

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                if text and should_show("assistant_text", verbosity):
                    if is_main:
                        # Suppress intermediate AI text in multi-step plans; final report only
                        if not state.multi_step_active:
                            cleaned = strip_internal_tags(text)
                            if cleaned:
                                state.full_response.append(cleaned)
                    else:
                        _handle_subagent_text_activity(namespace, text, state, verbosity=verbosity)
            elif btype in ("tool_call_chunk", "tool_call"):
                name = block.get("name", "")
                # Extract tool call with args for display
                tool_call = {"args": block.get("args", {})}
                _handle_tool_call_activity(state, name, prefix=prefix, verbosity=verbosity, tool_call=tool_call)

        if has_tool_chunks:
            for tc in tool_call_chunks:
                if isinstance(tc, dict):
                    name = tc.get("name", "")
                    # Extract tool call with args for display
                    tool_call = {"args": tc.get("args", {})}
                    _handle_tool_call_activity(state, name, prefix=prefix, verbosity=verbosity, tool_call=tool_call)
