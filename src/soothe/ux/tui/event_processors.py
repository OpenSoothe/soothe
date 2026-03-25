"""TUI event processing functions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from rich.console import RenderableType

from soothe.ux.shared.message_processing import (
    extract_tool_brief,
    format_tool_call_args,
    strip_internal_tags,
)
from soothe.ux.shared.progress_verbosity import classify_custom_event, should_show
from soothe.ux.shared.rendering import update_name_map_from_tool_calls
from soothe.ux.tui.renderers import (
    DOT_COLORS,
    _handle_generic_custom_activity,
    _handle_protocol_event,
    _handle_subagent_custom,
    _handle_subagent_progress,
    make_dot_line,
    make_tool_block,
)
from soothe.ux.tui.state import TuiState

# Type alias for panel write callbacks
PanelWriteCallback = Callable[[RenderableType], None] | None

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2


def _finalize_streaming_text(
    state: TuiState,
    on_panel_write: PanelWriteCallback,  # noqa: ARG001
    on_panel_update_last: PanelWriteCallback,  # noqa: ARG001
) -> None:
    """Finalize any active streaming text buffer.

    Resets streaming state when a turn ends.
    The text is already in full_response, so we just clean up state.

    Args:
        state: TUI state
        on_panel_write: Panel write callback (unused, text already written)
        on_panel_update_last: Panel update callback (unused)
    """
    if state.streaming_active:
        state.streaming_active = False
        state.last_assistant_output = state.streaming_text_buffer  # Stash for copy-last
        state.streaming_text_buffer = ""
        # Current tool calls should be cleared at turn end
        state.current_tool_calls.clear()


def _emit_custom_event_to_panel(
    data: dict[str, Any],
    state: TuiState,  # noqa: ARG001
    on_panel_write: PanelWriteCallback,
    *,
    category: str = "protocol",
) -> None:
    """Emit a custom event to the conversation panel with colored dot.

    Args:
        data: Event data dict
        state: TUI state
        on_panel_write: Panel write callback
        category: Event category for color selection
    """
    if not on_panel_write:
        return

    etype = data.get("type", "")
    # Build a summary line based on event type
    summary = _build_event_summary(data, etype)
    if not summary:
        return

    # Select color based on category
    color = DOT_COLORS.get(category, DOT_COLORS["protocol"])
    on_panel_write(make_dot_line(color, summary))


def _build_event_summary(data: dict[str, Any], etype: str) -> str:
    """Build a summary string for an event.

    Args:
        data: Event data dict
        etype: Event type string

    Returns:
        Human-readable summary string or empty string if not summarizable.
    """
    # Agentic events
    if "agentic" in etype:
        if "loop.started" in etype:
            return f"Agentic loop started (max {data.get('max_iterations', 3)} iterations)"
        if "loop.completed" in etype:
            return f"Agentic loop completed ({data.get('total_iterations', 0)} iterations)"
        if "iteration.started" in etype:
            return f"Iteration {data.get('iteration', 0) + 1}"
        return ""

    # Subagent events - show brief summary
    if "subagent" in etype or "browser" in etype:
        if "step" in etype.lower():
            step = data.get("step", "?")
            action = str(data.get("action", ""))[:40]
            return f"Step {step}: {action}" if action else f"Step {step}"
        return etype.rsplit(".", maxsplit=1)[-1].replace("_", " ").title()[:50]

    return ""


def _handle_agentic_event(
    data: dict[str, Any],
    state: TuiState,  # noqa: ARG001
    event_type: str,
    on_panel_write: PanelWriteCallback,
) -> None:
    """Handle agentic loop events (RFC-0008).

    Args:
        data: Event data
        state: TUI state (unused in clean cut, kept for signature)
        event_type: Event type string
        on_panel_write: Panel write callback
    """
    summary = ""
    color = DOT_COLORS["protocol"]

    if event_type == "soothe.agentic.loop.started":
        summary = f"Agentic loop started (max {data.get('max_iterations', 3)} iterations)"
        color = DOT_COLORS["progress"]
    elif event_type == "soothe.agentic.iteration.started":
        iteration = data.get("iteration", 0)
        strategy = data.get("planning_strategy", "unknown")
        summary = f"Iteration {iteration + 1} ({strategy} planning)"
        color = DOT_COLORS["progress"]
    elif event_type == "soothe.agentic.observation.completed":
        context = data.get("context_entries", 0)
        memories = data.get("memories_recalled", 0)
        strategy = data.get("planning_strategy", "unknown")
        summary = f"Observed: {context} context, {memories} memories → {strategy}"
    elif event_type == "soothe.agentic.verification.completed":
        should_continue = data.get("should_continue", False)
        outcome = "→ continuing" if should_continue else "✓ complete"
        summary = f"Verified: {outcome}"
        color = DOT_COLORS["success"] if not should_continue else DOT_COLORS["progress"]
    elif event_type == "soothe.agentic.loop.completed":
        iterations = data.get("total_iterations", 0)
        outcome = data.get("outcome", "unknown")
        summary = f"Agentic loop completed ({iterations} iterations, {outcome})"
        color = DOT_COLORS["success"]

    if summary and on_panel_write:
        on_panel_write(make_dot_line(color, summary))


class _TuiOutputFormatter:
    """TUI output formatter for direct panel writes (clean cut - no activity_lines/full_response)."""

    def __init__(
        self,
        state: TuiState,
        on_panel_write: PanelWriteCallback = None,
        on_panel_update_last: PanelWriteCallback = None,
    ) -> None:
        """Initialize TUI output formatter.

        Args:
            state: TUI state for tracking streaming state and tool calls.
            on_panel_write: Callback to append to conversation panel.
            on_panel_update_last: Callback to update last entry in panel.
        """
        self.state = state
        self.on_panel_write = on_panel_write
        self.on_panel_update_last = on_panel_update_last

    def emit_assistant_text(self, text: str, *, is_main: bool) -> None:
        """Emit assistant text directly to the conversation panel.

        Args:
            text: The assistant text to emit.
            is_main: Whether this is from the main agent.
        """
        logger.debug(
            "emit_assistant_text: text_len=%d, is_main=%s, on_panel_write=%s, on_panel_update_last=%s",
            len(text),
            is_main,
            self.on_panel_write is not None,
            self.on_panel_update_last is not None,
        )
        if is_main:
            # Stream main agent text to panel in real time
            self._stream_assistant_text(text)
        else:
            # Subagent text also goes to panel with subagent styling
            brief = text.replace("\n", " ")[:80]
            if self.on_panel_write:
                self.on_panel_write(make_dot_line(DOT_COLORS["subagent"], f"[subagent] {brief}"))
            else:
                logger.warning("emit_assistant_text: on_panel_write is None for subagent text")

    def _stream_assistant_text(self, text: str) -> None:
        """Stream assistant text to the conversation panel with live updates.

        Args:
            text: The text chunk to stream.
        """
        # Accumulate text in streaming buffer
        self.state.streaming_text_buffer += text

        # Create the dot-prefixed line for display
        display_text = make_dot_line(DOT_COLORS["assistant"], self.state.streaming_text_buffer)

        if not self.state.streaming_active:
            # First chunk - append new entry
            self.state.streaming_active = True
            logger.debug(
                "_stream_assistant_text: first chunk, buffer_len=%d, on_panel_write=%s",
                len(self.state.streaming_text_buffer),
                self.on_panel_write is not None,
            )
            if self.on_panel_write:
                self.on_panel_write(display_text)
            else:
                logger.warning("_stream_assistant_text: on_panel_write is None, cannot write first chunk")
        else:
            # Subsequent chunks - update the last entry
            logger.debug(
                "_stream_assistant_text: subsequent chunk, buffer_len=%d, on_panel_update_last=%s",
                len(self.state.streaming_text_buffer),
                self.on_panel_update_last is not None,
            )
            if self.on_panel_update_last:
                self.on_panel_update_last(display_text)
            else:
                # Fallback: if on_panel_update_last is not available, use on_panel_write
                # This ensures text is still displayed even if callbacks aren't fully configured
                logger.warning("_stream_assistant_text: on_panel_update_last is None, falling back to on_panel_write")
                if self.on_panel_write:
                    self.on_panel_write(display_text)

    def emit_tool_call(
        self,
        name: str,
        *,
        tool_call: dict[str, Any] | None = None,
    ) -> None:
        """Emit a tool call notification to the panel.

        Args:
            name: The tool name being called.
            tool_call: Optional tool call dict with args for display.
        """
        if not self.on_panel_write:
            return

        from soothe.tools.display_names import get_tool_display_name

        display_name = get_tool_display_name(name)
        args_summary = format_tool_call_args(name, tool_call or {})

        # Store tool call info for when result arrives
        if tool_call:
            tool_call_id = tool_call.get("id", "")
            if tool_call_id:
                self.state.current_tool_calls[tool_call_id] = {
                    "name": display_name,
                    "args_summary": args_summary,
                }

        # Finalize any streaming text before showing tool call
        if self.state.streaming_active:
            self.state.streaming_active = False
            self.state.streaming_text_buffer = ""

        # Write tool block with running status
        self.on_panel_write(make_tool_block(display_name, args_summary, status="running"))


def process_daemon_event(
    msg: dict[str, Any],
    state: TuiState,
    *,
    verbosity: str = "normal",
    on_status_update: callable | None = None,
    on_plan_refresh: callable | None = None,
    on_panel_write: PanelWriteCallback = None,
    on_panel_update_last: PanelWriteCallback = None,
) -> None:
    """Process a daemon event and update state.

    Args:
        msg: Daemon event message.
        state: TUI state to update.
        verbosity: Progress verbosity level.
        on_status_update: Callback for status updates.
        on_plan_refresh: Callback for plan refresh.
        on_panel_write: Callback to append a renderable to conversation panel.
        on_panel_update_last: Callback to update the last entry in conversation panel.
    """
    logger.debug(
        "process_daemon_event: type=%s mode=%s has_on_panel_write=%s has_on_panel_update_last=%s",
        msg.get("type"),
        msg.get("mode"),
        on_panel_write is not None,
        on_panel_update_last is not None,
    )
    msg_type = msg.get("type", "")

    if msg_type == "status":
        state_str = msg.get("state", "unknown")
        tid_raw = msg.get("thread_id", state.thread_id)
        # Keep existing thread_id when daemon sends empty handshake thread_id ("").
        tid = state.thread_id if tid_raw in (None, "") else str(tid_raw)
        previous_thread_id = state.thread_id
        state.thread_id = tid

        if tid and tid != previous_thread_id:
            # Thread ID changed - caller should handle loading history
            pass

        if on_status_update:
            on_status_update(state_str)

        # On turn end, finalize streaming text
        if state_str in {"idle", "stopped"}:
            _finalize_streaming_text(state, on_panel_write, on_panel_update_last)

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
            handle_messages_event(
                data,
                state,
                namespace=namespace,
                verbosity=verbosity,
                on_panel_write=on_panel_write,
                on_panel_update_last=on_panel_update_last,
            )
        elif mode == "custom" and isinstance(data, dict):
            category = classify_custom_event(namespace, data)
            etype = data.get("type", "")

            # Check for multi-step plan creation
            from soothe.core.event_catalog import PLAN_CREATED

            if etype == PLAN_CREATED and len(data.get("steps", [])) > 1:
                state.multi_step_active = True

            # Route agentic events (RFC-0008)
            if etype.startswith("soothe.agentic."):
                _handle_agentic_event(data, state, etype, on_panel_write)
            # Plan state must always be updated regardless of verbosity
            elif category == "protocol" and "plan" in etype:
                _handle_protocol_event(data, state, verbosity="normal", on_panel_write=on_panel_write)
                if on_plan_refresh:
                    on_plan_refresh()
            elif category == "protocol" and should_show(category, verbosity):
                _handle_protocol_event(data, state, verbosity=verbosity, on_panel_write=on_panel_write)
                if "plan" in etype and on_plan_refresh:
                    on_plan_refresh()
            elif category == "subagent_progress" and should_show(category, verbosity):
                _handle_subagent_progress(namespace, data, state, verbosity=verbosity)
                _emit_custom_event_to_panel(data, state, on_panel_write, category="subagent")
                if on_status_update:
                    on_status_update("Running")
            elif category == "subagent_custom" and not is_main:
                _handle_subagent_custom(namespace, data, state, verbosity=verbosity)
                _emit_custom_event_to_panel(data, state, on_panel_write, category="subagent")
                if on_status_update:
                    on_status_update("Running")
            elif category == "assistant_text":
                _handle_protocol_event(data, state, verbosity=verbosity, on_panel_write=on_panel_write)
            elif category == "error" and should_show("error", verbosity):
                _handle_protocol_event(data, state, verbosity="normal", on_panel_write=on_panel_write)
                # Always emit errors to panel
                if on_panel_write:
                    error_text = data.get("error", data.get("message", str(data.get("type", "Error"))))
                    on_panel_write(make_dot_line(DOT_COLORS["error"], f"Error: {error_text[:80]}"))
            elif should_show(category, verbosity):
                _handle_generic_custom_activity(namespace, data, state, verbosity=verbosity)


def handle_messages_event(
    data: Any,
    state: TuiState,
    *,
    namespace: tuple[str, ...],
    verbosity: str = "normal",
    on_panel_write: PanelWriteCallback = None,
    on_panel_update_last: PanelWriteCallback = None,
) -> None:
    """Handle messages event and update state (clean cut - direct panel writes only).

    Args:
        data: Event data (message and metadata).
        state: TUI state to update.
        namespace: Event namespace tuple.
        verbosity: Progress verbosity level.
        on_panel_write: Callback to append to conversation panel.
        on_panel_update_last: Callback to update last entry in panel.
    """
    logger.debug(
        "handle_messages_event: namespace=%s verbosity=%s has_on_panel_write=%s has_on_panel_update_last=%s",
        namespace,
        verbosity,
        on_panel_write is not None,
        on_panel_update_last is not None,
    )
    if isinstance(data, (list, tuple)) and len(data) == _MSG_PAIR_LEN:
        msg, metadata = data
    elif isinstance(data, dict):
        return
    else:
        return

    if metadata and isinstance(metadata, dict) and metadata.get("lc_source") == "summarization":
        return

    is_main = not namespace
    formatter = _TuiOutputFormatter(state, on_panel_write, on_panel_update_last)

    # Handle AIMessage objects directly (no MessageProcessor)
    if isinstance(msg, AIMessage):
        # Update name_map from tool calls
        update_name_map_from_tool_calls(msg, state.name_map)

        # Track seen message IDs
        from langchain_core.messages import AIMessageChunk

        msg_id = msg.id or ""
        if not isinstance(msg, AIMessageChunk):
            if msg_id in state.seen_message_ids:
                return
            state.seen_message_ids.add(msg_id)
        elif msg_id:
            state.seen_message_ids.add(msg_id)

        # Process content blocks
        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    if text and should_show("assistant_text", verbosity):
                        cleaned = strip_internal_tags(text)
                        if cleaned:
                            formatter.emit_assistant_text(cleaned, is_main=is_main)
                elif btype in ("tool_call", "tool_call_chunk"):
                    name = block.get("name", "")
                    if name and should_show("protocol", verbosity):
                        tool_call = {"args": block.get("args", {}), "id": block.get("id", "")}
                        formatter.emit_tool_call(name, tool_call=tool_call)
        elif is_main and isinstance(msg.content, str) and msg.content and should_show("assistant_text", verbosity):
            cleaned = strip_internal_tags(msg.content)
            if cleaned:
                formatter.emit_assistant_text(cleaned, is_main=is_main)

        # Handle tool_calls attribute
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("name", "")
                    if name and should_show("protocol", verbosity):
                        formatter.emit_tool_call(name, tool_call=tc)
        return

    # Handle ToolMessage objects
    if isinstance(msg, ToolMessage):
        tool_name = getattr(msg, "name", "tool")
        tool_call_id = getattr(msg, "tool_call_id", None)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        brief = extract_tool_brief(tool_name, content)

        # Write tool result to panel with status
        if on_panel_write:
            # Look up tool call info if available
            tool_info = state.current_tool_calls.pop(str(tool_call_id), {}) if tool_call_id else {}
            args_summary = tool_info.get("args_summary", "")
            # Determine status: check for error indicators
            is_error = any(indicator in content.lower() for indicator in ["error", "failed", "exception", "traceback"])
            status = "error" if is_error else "success"
            # Build output preview
            output_preview = brief[:200] if brief else None
            from soothe.tools.display_names import get_tool_display_name

            display_name = get_tool_display_name(tool_name)
            on_panel_write(make_tool_block(display_name, args_summary, output_preview, status=status))
        return

    # Handle deserialized dict (after JSON transport)
    if isinstance(msg, dict):
        msg_id = msg.get("id", "")
        is_chunk = msg.get("type") == "AIMessageChunk"
        msg_type = msg.get("type", "unknown")
        logger.debug(
            "handle_messages_event: dict msg type=%s msg_id=%s is_chunk=%s",
            msg_type,
            msg_id,
            is_chunk,
        )

        if not is_chunk:
            if msg_id and msg_id in state.seen_message_ids:
                logger.debug("handle_messages_event: skipping seen msg_id=%s", msg_id)
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
            logger.debug(
                "handle_messages_event: no blocks, content type=%s content_len=%d is_main=%s",
                type(content).__name__,
                len(content) if isinstance(content, (str, list)) else 0,
                is_main,
            )
            if isinstance(content, list):
                blocks = content
            elif is_main and isinstance(content, str) and content and should_show("assistant_text", verbosity):
                cleaned = strip_internal_tags(content)
                logger.debug(
                    "handle_messages_event: string content, cleaned_len=%d, emitting",
                    len(cleaned),
                )
                if cleaned:
                    formatter.emit_assistant_text(cleaned, is_main=is_main)

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                if text and should_show("assistant_text", verbosity):
                    cleaned = strip_internal_tags(text)
                    if cleaned:
                        formatter.emit_assistant_text(cleaned, is_main=is_main)
            elif btype in ("tool_call_chunk", "tool_call"):
                name = block.get("name", "")
                if name and should_show("protocol", verbosity):
                    tool_call = {"args": block.get("args", {}), "id": block.get("id", "")}
                    formatter.emit_tool_call(name, tool_call=tool_call)

        if has_tool_chunks:
            for tc in tool_call_chunks:
                if isinstance(tc, dict):
                    name = tc.get("name", "")
                    if name and should_show("protocol", verbosity):
                        tool_call = {"args": tc.get("args", {}), "id": tc.get("id", "")}
                        formatter.emit_tool_call(name, tool_call=tool_call)
