"""TUI event processing functions."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.cli.progress_verbosity import classify_custom_event, should_show
from soothe.cli.tui.renderers import (
    _handle_generic_custom_activity,
    _handle_protocol_event,
    _handle_subagent_custom,
    _handle_subagent_progress,
    _handle_subagent_text_activity,
    _handle_tool_call_activity,
    _handle_tool_result_activity,
    strip_internal_tags,
)
from soothe.cli.tui.state import TuiState
from soothe.cli.tui_shared import _resolve_namespace_label, _update_name_map_from_ai_message

if TYPE_CHECKING:
    from soothe.cli.tui.widgets import ActivityPanel

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2


def process_daemon_event(
    msg: dict[str, Any],
    state: TuiState,
    activity_panel: ActivityPanel,
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
        activity_panel: Activity panel widget.
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
            handle_messages_event(data, state, namespace=namespace, activity_panel=activity_panel, verbosity=verbosity)
        elif mode == "custom" and isinstance(data, dict):
            category = classify_custom_event(namespace, data)
            etype = data.get("type", "")

            # Plan state must always be updated regardless of verbosity
            if category == "protocol" and "plan" in etype:
                _handle_protocol_event(data, state, verbosity="normal")
                if should_show(category, verbosity):
                    _flush_new_activity(state, activity_panel)
                if on_plan_refresh:
                    on_plan_refresh()
            elif category == "protocol" and should_show(category, verbosity):
                _handle_protocol_event(data, state, verbosity=verbosity)
                _flush_new_activity(state, activity_panel)
                if "plan" in etype and on_plan_refresh:
                    on_plan_refresh()
            elif category == "subagent_progress" and should_show(category, verbosity):
                _handle_subagent_progress(namespace, data, state, verbosity=verbosity)
                _flush_new_activity(state, activity_panel)
                if on_status_update:
                    on_status_update("Running")
            elif category == "subagent_custom" and not is_main:
                _handle_subagent_custom(namespace, data, state, verbosity=verbosity)
                _flush_new_activity(state, activity_panel)
                if on_status_update:
                    on_status_update("Running")
            elif category == "error" and should_show("error", verbosity):
                _handle_protocol_event(data, state, verbosity="normal")
                _flush_new_activity(state, activity_panel)
            elif should_show(category, verbosity):
                _handle_generic_custom_activity(namespace, data, state, verbosity=verbosity)
                _flush_new_activity(state, activity_panel)


def handle_messages_event(
    data: Any,
    state: TuiState,
    *,
    namespace: tuple[str, ...],
    activity_panel: ActivityPanel,
    verbosity: str = "normal",
) -> None:
    """Handle messages event and update state.

    Args:
        data: Event data (message and metadata).
        state: TUI state to update.
        namespace: Event namespace tuple.
        activity_panel: Activity panel widget.
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

    # Handle LangChain objects (in-process)
    if isinstance(msg, AIMessage):
        _update_name_map_from_ai_message(state, msg)
        msg_id = msg.id or ""
        if not isinstance(msg, AIMessageChunk):
            if msg_id in state.seen_message_ids:
                return
            state.seen_message_ids.add(msg_id)
        elif msg_id:
            state.seen_message_ids.add(msg_id)

        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    if text and should_show("assistant_text", verbosity):
                        if is_main:
                            cleaned = strip_internal_tags(text)
                            if cleaned:
                                state.full_response.append(cleaned)
                        else:
                            _handle_subagent_text_activity(namespace, text, state, verbosity=verbosity)
                            _flush_new_activity(state, activity_panel)
                elif btype in ("tool_call_chunk", "tool_call"):
                    name = block.get("name", "")
                    _handle_tool_call_activity(state, name, prefix=prefix, verbosity=verbosity)
                    _flush_new_activity(state, activity_panel)
        elif is_main and isinstance(msg.content, str) and msg.content and should_show("assistant_text", verbosity):
            cleaned = strip_internal_tags(msg.content)
            if cleaned:
                state.full_response.append(cleaned)

    # Handle deserialized dict (after JSON transport)
    elif isinstance(msg, dict):
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
                        cleaned = strip_internal_tags(text)
                        if cleaned:
                            state.full_response.append(cleaned)
                    else:
                        _handle_subagent_text_activity(namespace, text, state, verbosity=verbosity)
                        _flush_new_activity(state, activity_panel)
            elif btype in ("tool_call_chunk", "tool_call"):
                name = block.get("name", "")
                _handle_tool_call_activity(state, name, prefix=prefix, verbosity=verbosity)
                _flush_new_activity(state, activity_panel)

        if has_tool_chunks:
            for tc in tool_call_chunks:
                if isinstance(tc, dict):
                    name = tc.get("name", "")
                    _handle_tool_call_activity(state, name, prefix=prefix, verbosity=verbosity)
                    _flush_new_activity(state, activity_panel)

    # Handle ToolMessage objects
    if isinstance(msg, ToolMessage):
        tool_name = getattr(msg, "name", "tool")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        _handle_tool_result_activity(state, tool_name, content, prefix=prefix, verbosity=verbosity)
        _flush_new_activity(state, activity_panel)


def _flush_new_activity(state: TuiState, activity_panel: ActivityPanel) -> None:
    """Append only new activity lines (append-only, no clear)."""
    with contextlib.suppress(Exception):
        last_activity_count = getattr(activity_panel, "_last_activity_count", 0)
        new_lines = state.activity_lines[last_activity_count:]
        for line in new_lines:
            activity_panel.write(line)
        activity_panel._last_activity_count = len(state.activity_lines)
