"""Unified daemon event processor with pluggable rendering.

This module implements RFC-0019's unified event processing architecture.
EventProcessor handles all event routing, state management, and filtering,
delegating display to RendererProtocol implementations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from soothe_sdk.client.protocol import preview_first
from soothe_sdk.core.events import (
    PLAN_CREATED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_STARTED,
)
from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux import classify_event_to_tier
from soothe_sdk.ux.output_events import extract_output_text, is_output_event

from soothe_cli.shared.display_policy import DisplayPolicy, VerbosityLevel, normalize_verbosity
from soothe_cli.shared.message_processing import (
    accumulate_tool_call_chunks,
    extract_tool_args_dict,
    extract_tool_brief,
    finalize_pending_tool_call,
    normalize_tool_calls_list,
    strip_internal_tags,
    tool_calls_have_any_arg_dict,
    try_parse_pending_tool_call_args,
)
from soothe_cli.shared.presentation_engine import PresentationEngine
from soothe_cli.shared.processor_state import ProcessorState
from soothe_cli.shared.rendering import update_name_map_from_tool_calls
from soothe_cli.shared.tool_card_payload import (
    extract_tool_result_card_payload,
    infer_tool_output_suggests_error,
)
from soothe_cli.shared.tui_trace_log import log_tui_trace

if TYPE_CHECKING:
    from soothe_sdk.client.schemas import Plan

    from soothe_cli.shared.renderer_protocol import RendererProtocol

logger = logging.getLogger(__name__)

_MSG_PAIR_LEN = 2


class EventProcessor:
    """Unified daemon event processor with pluggable rendering.

    Handles all event routing, state management, and filtering.
    Delegates display to RendererProtocol implementation.

    Usage:
        renderer = CliRenderer(verbosity="normal")
        processor = EventProcessor(renderer, verbosity="normal")

        # In event loop:
        processor.process_event(event)
    """

    def __init__(
        self,
        renderer: RendererProtocol,
        *,
        verbosity: VerbosityLevel = "normal",
        final_output_mode: str = "streaming",
        presentation_engine: PresentationEngine | None = None,
        tui_debug: bool = False,
    ) -> None:
        """Initialize processor with renderer and verbosity level.

        Args:
            renderer: Callback interface for display.
            verbosity: Progress visibility level.
            presentation_engine: Shared engine; if omitted, uses renderer's
                ``presentation_engine`` when present, else a new instance.
            tui_debug: When True, emit INFO logs on logger ``soothe.ux.tui.trace`` (IG-129).
        """
        self._renderer = renderer
        self._verbosity = normalize_verbosity(verbosity)
        self._final_output_mode = (
            final_output_mode if final_output_mode in {"streaming", "batch"} else "streaming"
        )
        self._tui_debug = tui_debug

        rebind = getattr(renderer, "_rebind_presentation", None)
        shared_from_renderer = getattr(renderer, "presentation_engine", None)
        if presentation_engine is not None:
            self._presentation = presentation_engine
            # Avoid rebuilding StreamDisplayPipeline when renderer already uses this engine.
            if callable(rebind) and shared_from_renderer is not presentation_engine:
                rebind(presentation_engine)
        elif isinstance(shared_from_renderer, PresentationEngine):
            self._presentation = shared_from_renderer
        else:
            self._presentation = PresentationEngine()

        self._policy = DisplayPolicy(verbosity=self._verbosity)
        self._state = ProcessorState()

    @property
    def current_plan(self) -> Plan | None:
        """Read-only access to current plan for renderers."""
        return self._state.current_plan

    @property
    def thread_id(self) -> str:
        """Current thread ID."""
        return self._state.thread_id

    @property
    def state(self) -> ProcessorState:
        """Read-only access to processor state."""
        return self._state

    @property
    def multi_step_active(self) -> bool:
        """Whether multi-step plan is active (suppress intermediate text)."""
        return self._state.multi_step_active

    def _emit_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,
    ) -> None:
        """Forward assistant text unless a custom final response already locked the stream."""
        if is_main and self._presentation.final_answer_locked:
            return
        payload = self._maybe_extract_quiet_answer(text)
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="processor.emit_assistant_text",
            is_main=is_main,
            is_streaming=is_streaming,
            chars=len(payload),
        )
        self._renderer.on_assistant_text(
            payload,
            is_main=is_main,
            is_streaming=is_streaming,
        )

    def process_event(self, event: dict[str, Any]) -> None:
        """Main entry point - routes event to appropriate handler.

        Args:
            event: Daemon event dictionary with 'type' key.
        """
        event_type = event.get("type", "")
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="processor.process_event",
            event_type=event_type,
        )

        if event_type == "status":
            self._handle_status(event)
        elif event_type == "event":
            self._handle_stream_event(event)
        elif event_type == "error":
            self._handle_error_event(event)
        elif event_type == "command_response":
            self._handle_command_response(event)
        elif event_type == "clear":
            self._handle_clear_event(event)

    def _handle_command_response(self, event: dict[str, Any]) -> None:
        """Handle command response from daemon (RFC-404)."""
        command = event.get("command")
        data = event.get("data")
        error = event.get("error")

        if error:
            self._renderer.on_error(error)
            return

        # Find rendering handler from registry
        from soothe_cli.shared.command_router import find_command_by_daemon_command

        entry = find_command_by_daemon_command(command)
        if entry and entry.get("handler") and data:
            handler = entry["handler"]
            handler(self._renderer.console, data)
        else:
            # Default: pretty print JSON
            import json

            from rich.panel import Panel

            self._renderer.console.print(
                Panel(json.dumps(data, indent=2, default=str), title=command, border_style="cyan")
            )

    def _handle_clear_event(self, event: dict[str, Any]) -> None:
        """Handle clear event from daemon."""
        # Clear local UI state if renderer supports it
        if hasattr(self._renderer, "clear"):
            self._renderer.clear()

    def _handle_status(self, event: dict[str, Any]) -> None:
        """Process status changes, update thread_id, call on_status_change."""
        state_str = event.get("state", "unknown")
        tid_raw = event.get("thread_id", self._state.thread_id)

        # Keep existing thread_id when daemon sends empty handshake
        tid = self._state.thread_id if tid_raw in (None, "") else str(tid_raw)
        previous_thread_id = self._state.thread_id
        self._state.thread_id = tid
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="processor.status",
            state=state_str,
            thread_id=tid,
        )

        # Clear session state on thread change
        if tid and tid != previous_thread_id:
            self._state.clear_session()
            self._presentation.reset_session()

        self._renderer.on_status_change(state_str)

        # On turn end, finalize streaming and call hook
        if state_str in {"idle", "stopped"}:
            self._state.reset_turn()
            self._presentation.reset_turn()
            self._renderer.on_turn_end()

    def _handle_stream_event(self, event: dict[str, Any]) -> None:
        """Route to messages or custom event handlers."""
        mode = event.get("mode", "")
        namespace = tuple(event.get("namespace", []))
        data = event.get("data")
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="processor.stream_event",
            mode=mode,
            namespace=namespace,
        )

        if mode == "messages":
            self._handle_messages(data, namespace)
        elif mode == "custom" and isinstance(data, dict):
            self._handle_custom_event(data, namespace)

    def _handle_error_event(self, event: dict[str, Any]) -> None:
        """Handle error events."""
        error = event.get("message", event.get("error", "Unknown error"))
        context = event.get("code")
        self._renderer.on_error(error, context=context)

    def _handle_messages(
        self,
        data: Any,
        namespace: tuple[str, ...],
    ) -> None:
        """Process AIMessage/ToolMessage with deduplication and streaming."""
        if isinstance(data, (list, tuple)) and len(data) == _MSG_PAIR_LEN:
            msg, metadata = data
        elif isinstance(data, dict):
            return
        else:
            return

        # Skip summarization messages
        if metadata and isinstance(metadata, dict) and metadata.get("lc_source") == "summarization":
            return

        is_main = not namespace
        msg_kind: str
        if isinstance(msg, AIMessage):
            msg_kind = "AIMessageChunk" if isinstance(msg, AIMessageChunk) else "AIMessage"
        elif isinstance(msg, ToolMessage):
            msg_kind = "ToolMessage"
        elif isinstance(msg, dict):
            msg_kind = str(msg.get("type", "dict"))
        else:
            msg_kind = type(msg).__name__
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="processor.messages",
            msg_kind=msg_kind,
            is_main=is_main,
        )

        if isinstance(msg, AIMessage):
            self._handle_ai_message(msg, is_main=is_main, namespace=namespace)
        elif isinstance(msg, ToolMessage):
            self._handle_tool_message(msg, is_main=is_main, namespace=namespace)
        elif isinstance(msg, dict):
            self._handle_dict_message(msg, is_main=is_main, namespace=namespace)

    def _handle_ai_message(
        self,
        msg: AIMessage,
        *,
        is_main: bool,
        namespace: tuple[str, ...],  # noqa: ARG002
    ) -> None:
        """Handle AIMessage objects."""
        # Update name_map from tool calls
        update_name_map_from_tool_calls(msg, self._state.name_map)

        # Deduplication (complete messages only, chunks share IDs)
        msg_id = msg.id or ""
        is_chunk = isinstance(msg, AIMessageChunk)
        if not is_chunk:
            if msg_id in self._state.seen_message_ids:
                return
            self._state.seen_message_ids.add(msg_id)

        raw_tcs = getattr(msg, "tool_calls", None) or []
        tcs = normalize_tool_calls_list(raw_tcs)
        has_tc_args = tool_calls_have_any_arg_dict(raw_tcs)

        # Accumulate streaming tool args (IG-053)
        tool_call_chunks = getattr(msg, "tool_call_chunks", None) or []
        accumulate_tool_call_chunks(
            self._state.pending_tool_calls,
            tool_call_chunks,
            is_main=is_main,
        )

        # Emit pending tool calls with complete args
        self._emit_pending_tool_calls(is_main)

        # Process content blocks
        tool_call_emitted_from_blocks = False
        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    # Suppress during internal context (research internal LLM responses)
                    if self._state.internal_context_active and not is_main:
                        continue
                    # Always pass to renderer for accumulation, let renderer decide display
                    if text:
                        cleaned = self._clean_assistant_text(text, is_streaming=is_chunk)
                        if cleaned:
                            self._emit_assistant_text(
                                cleaned,
                                is_main=is_main,
                                is_streaming=is_chunk,
                            )
                elif btype in ("tool_call", "tool_call_chunk"):
                    if has_tc_args:
                        continue
                    name = block.get("name", "")
                    if name and self._presentation.tier_visible(
                        VerbosityTier.NORMAL, self._verbosity
                    ):
                        coerced = extract_tool_args_dict(block)
                        # Skip if no args - will be emitted when tool result arrives
                        if not coerced:
                            continue
                        tool_call_id = block.get("id", "")
                        self._renderer.on_tool_call(
                            name,
                            coerced,
                            tool_call_id,
                            is_main=is_main,
                        )
                        tool_call_emitted_from_blocks = True
                        # Log tool invocation for audit trail
                        logger.info(
                            "tool_call name=%s id=%s args=%s is_main=%s",
                            name,
                            tool_call_id,
                            preview_first(str(coerced), 200) if coerced else "{}",
                            is_main,
                        )
        elif is_main and isinstance(msg.content, str) and msg.content:
            # Always pass to renderer for accumulation, let renderer decide display
            cleaned = self._clean_assistant_text(msg.content, is_streaming=is_chunk)
            if cleaned:
                self._emit_assistant_text(
                    cleaned,
                    is_main=is_main,
                    is_streaming=is_chunk,
                )

        # Handle tool_calls attribute
        # IMPORTANT: Only emit if we have non-empty args. Otherwise, let the accumulation
        # from tool_call_chunks happen and emit when tool result arrives.
        if tcs:
            for tc in tcs:
                name = tc.get("name", "")
                if not name or not self._presentation.tier_visible(
                    VerbosityTier.NORMAL, self._verbosity
                ):
                    continue
                tc_args = extract_tool_args_dict(tc)

                # Skip chunks with empty args - they'll come from tool_call_chunks
                if is_chunk and not tc_args and not has_tc_args:
                    continue

                # Skip if args are empty - will be emitted via finalize_pending_tool_call
                if not tc_args and not tool_call_emitted_from_blocks:
                    continue

                if has_tc_args:
                    tool_call_id = tc.get("id", "")
                    # Deduplicate tool calls by ID
                    if tool_call_id and tool_call_id in self._state.emitted_tool_call_ids:
                        continue
                    if tool_call_id:
                        self._state.emitted_tool_call_ids.add(tool_call_id)
                    self._renderer.on_tool_call(name, tc_args, tool_call_id, is_main=is_main)
                    # Log tool invocation for audit trail
                    logger.info(
                        "tool_call name=%s id=%s args=%s is_main=%s",
                        name,
                        tool_call_id,
                        preview_first(str(tc_args), 200) if tc_args else "{}",
                        is_main,
                    )

    def _handle_tool_message(
        self,
        msg: ToolMessage,
        *,
        is_main: bool,
        namespace: tuple[str, ...],  # noqa: ARG002
    ) -> None:
        """Handle ToolMessage objects."""
        if not self._presentation.tier_visible(VerbosityTier.NORMAL, self._verbosity):
            return

        tool_name = getattr(msg, "name", "tool")
        tool_call_id = getattr(msg, "tool_call_id", None) or ""

        # Deduplicate tool results by ID
        if tool_call_id and tool_call_id in self._state.emitted_tool_result_ids:
            return
        if tool_call_id:
            self._state.emitted_tool_result_ids.add(tool_call_id)

        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        brief = extract_tool_brief(tool_name, content)

        # Finalize pending tool call if needed (IG-053)
        parsed_args, pending, needs_emit, raw_args_str = finalize_pending_tool_call(
            self._state.pending_tool_calls,
            tool_call_id,
        )
        if needs_emit:
            # Pass raw args for display fallback when parsed args unavailable
            args_to_display = parsed_args or ({"_raw": raw_args_str} if raw_args_str else {})
            self._renderer.on_tool_call(
                pending.get("name") or tool_name,
                args_to_display,
                tool_call_id,
                is_main=pending.get("is_main", is_main),
            )

        payload = extract_tool_result_card_payload(msg)
        is_error = (
            payload.is_error if payload is not None else infer_tool_output_suggests_error(content)
        )

        # Log tool result for audit trail
        logger.info(
            "tool_result name=%s id=%s status=%s result=%s is_main=%s",
            tool_name,
            tool_call_id,
            "error" if is_error else "success",
            preview_first(brief, 300) if brief else "",
            is_main,
        )

        self._renderer.on_tool_result(
            tool_name,
            brief,
            tool_call_id,
            is_error=is_error,
            is_main=is_main,
        )

    def _handle_dict_message(
        self,
        msg: dict[str, Any],
        *,
        is_main: bool,
        namespace: tuple[str, ...],  # noqa: ARG002
    ) -> None:
        """Handle deserialized dict messages (after JSON transport)."""
        msg_type = msg.get("type", "")
        msg_id = msg.get("id", "")
        is_chunk = msg_type == "AIMessageChunk"

        # Handle ToolMessage dicts (serialized via model_dump)
        if msg_type in ("ToolMessage", "tool"):
            self._handle_tool_message_dict(msg, is_main=is_main)
            return

        if not is_chunk:
            if msg_id and msg_id in self._state.seen_message_ids:
                return
            if msg_id:
                self._state.seen_message_ids.add(msg_id)

        # Accumulate streaming tool args from tool_call_chunks (IG-053)
        tool_call_chunks = msg.get("tool_call_chunks", [])
        if isinstance(tool_call_chunks, list) and tool_call_chunks:
            accumulate_tool_call_chunks(
                self._state.pending_tool_calls,
                tool_call_chunks,
                is_main=is_main,
            )

        # Process content blocks or content string
        blocks = msg.get("content_blocks") or []
        if not blocks:
            content = msg.get("content", "")
            if isinstance(content, list):
                blocks = content
            elif is_main and isinstance(content, str) and content:
                # Always pass to renderer for accumulation, let renderer decide display
                cleaned = self._clean_assistant_text(content, is_streaming=is_chunk)
                if cleaned:
                    self._emit_assistant_text(
                        cleaned,
                        is_main=is_main,
                        is_streaming=is_chunk,
                    )

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                # Always pass to renderer for accumulation, let renderer decide display
                if text:
                    cleaned = self._clean_assistant_text(text, is_streaming=is_chunk)
                    if cleaned:
                        self._emit_assistant_text(
                            cleaned,
                            is_main=is_main,
                            is_streaming=is_chunk,
                        )
            elif btype in ("tool_call_chunk", "tool_call"):
                name = block.get("name", "")
                if name and self._presentation.tier_visible(VerbosityTier.NORMAL, self._verbosity):
                    args = extract_tool_args_dict(block)
                    tool_call_id = block.get("id", "")
                    # Deduplicate tool calls
                    if tool_call_id and tool_call_id in self._state.emitted_tool_call_ids:
                        continue
                    if tool_call_id:
                        self._state.emitted_tool_call_ids.add(tool_call_id)
                    self._renderer.on_tool_call(name, args, tool_call_id, is_main=is_main)
                    # Log tool invocation for audit trail
                    logger.info(
                        "tool_call name=%s id=%s args=%s is_main=%s",
                        name,
                        tool_call_id,
                        preview_first(str(args), 200) if args else "{}",
                        is_main,
                    )

        # Handle tool_calls from serialized AIMessage (model_dump produces tool_calls not tool_call_chunks)
        # IMPORTANT: Only emit if we have non-empty args. Otherwise, let the accumulation
        # from tool_call_chunks happen and emit when tool result arrives.
        tool_calls = msg.get("tool_calls", [])
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("name", "")
                    if name and self._presentation.tier_visible(
                        VerbosityTier.NORMAL, self._verbosity
                    ):
                        args = extract_tool_args_dict(tc)
                        tool_call_id = tc.get("id", "")

                        # Skip emitting if args are empty - they'll come from tool_call_chunks
                        # and will be emitted when the tool result arrives (via finalize_pending_tool_call)
                        if not args:
                            continue

                        # Deduplicate tool calls
                        if tool_call_id and tool_call_id in self._state.emitted_tool_call_ids:
                            continue
                        if tool_call_id:
                            self._state.emitted_tool_call_ids.add(tool_call_id)
                        self._renderer.on_tool_call(name, args, tool_call_id, is_main=is_main)
                        # Log tool invocation for audit trail
                        logger.info(
                            "tool_call name=%s id=%s args=%s is_main=%s",
                            name,
                            tool_call_id,
                            preview_first(str(args), 200) if args else "{}",
                            is_main,
                        )

    def _handle_tool_message_dict(
        self,
        msg: dict[str, Any],
        *,
        is_main: bool,
    ) -> None:
        """Handle ToolMessage dict (serialized via model_dump).

        Args:
            msg: ToolMessage serialized as dict.
            is_main: True if from main agent.
        """
        if not self._presentation.tier_visible(VerbosityTier.NORMAL, self._verbosity):
            return

        tool_name = msg.get("name", "tool")
        tool_call_id = msg.get("tool_call_id", "")

        # Deduplicate tool results by ID
        if tool_call_id and tool_call_id in self._state.emitted_tool_result_ids:
            return
        if tool_call_id:
            self._state.emitted_tool_result_ids.add(tool_call_id)

        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)

        brief = extract_tool_brief(tool_name, content)

        # Finalize pending tool call if needed (IG-053)
        parsed_args, pending, needs_emit, raw_args_str = finalize_pending_tool_call(
            self._state.pending_tool_calls,
            tool_call_id,
        )
        if needs_emit:
            # Pass raw args for display fallback when parsed args unavailable
            args_to_display = parsed_args or ({"_raw": raw_args_str} if raw_args_str else {})
            self._renderer.on_tool_call(
                pending.get("name") or tool_name,
                args_to_display,
                tool_call_id,
                is_main=pending.get("is_main", is_main),
            )

        payload = extract_tool_result_card_payload(msg)
        is_error = (
            payload.is_error if payload is not None else infer_tool_output_suggests_error(content)
        )

        # Log tool result for audit trail
        logger.info(
            "tool_result name=%s id=%s status=%s result=%s is_main=%s",
            tool_name,
            tool_call_id,
            "error" if is_error else "success",
            preview_first(brief, 300) if brief else "",
            is_main,
        )

        self._renderer.on_tool_result(
            tool_name,
            brief,
            tool_call_id,
            is_error=is_error,
            is_main=is_main,
        )

    def _emit_pending_tool_calls(self, is_main: bool) -> None:  # noqa: FBT001
        """Emit pending tool calls that have complete JSON args."""
        for tc_id, pending in list(self._state.pending_tool_calls.items()):
            if pending["emitted"]:
                continue
            # Deduplicate
            if tc_id in self._state.emitted_tool_call_ids:
                pending["emitted"] = True
                continue
            parsed_args = try_parse_pending_tool_call_args(pending)
            if parsed_args is not None and self._presentation.tier_visible(
                VerbosityTier.NORMAL, self._verbosity
            ):
                self._state.emitted_tool_call_ids.add(tc_id)
                self._renderer.on_tool_call(
                    pending["name"],
                    parsed_args,
                    tc_id,
                    is_main=pending.get("is_main", is_main),
                )
                pending["emitted"] = True

    def _handle_custom_event(
        self,
        data: dict[str, Any],
        namespace: tuple[str, ...],
    ) -> None:
        """Process protocol/progress events."""
        etype = data.get("type", "")

        # Tool events are now visible at NORMAL verbosity (RFC-0020 CLI Stream Display Pipeline)
        # They are processed through on_progress_event -> StreamDisplayPipeline

        # Handle output events (chitchat, quiz, goal completion streaming, etc.) through unified registry
        # IG-254: Single source of truth for user-visible output events
        # IG-268: Include goal_completion_message from agent_loop.completed (removed exclusion)
        data_for_progress = data
        if etype == "soothe.cognition.agent_loop.completed":
            if self._final_output_mode == "batch":
                content = extract_output_text(etype, data)
                if content and self._presentation.tier_visible(
                    VerbosityTier.QUIET, self._verbosity
                ):
                    cleaned = self._clean_assistant_text(content)
                    if cleaned:
                        self._emit_assistant_text(
                            cleaned,
                            is_main=True,
                            is_streaming=False,
                        )
                        self._presentation.mark_final_answer_locked()
            # Prevent renderer-side duplicate final emission in both modes:
            # - streaming mode: final text is emitted via chunk stream
            # - batch mode: final text is emitted above
            data_for_progress = dict(data)
            data_for_progress.pop("goal_completion_message", None)
            # Continue processing as progress event for status/goal completion lines.
        elif is_output_event(etype):
            # RFC-614: Unified streaming output handling
            streaming_config = self._get_effective_streaming_config()

            # Skip if streaming disabled for this event type
            if not self._should_stream_event_type(etype, streaming_config):
                return

            content = extract_output_text(etype, data)
            if content and self._presentation.tier_visible(VerbosityTier.QUIET, self._verbosity):
                # Treat all ``*.streaming`` events as streaming text payloads. Some
                # providers send ``is_chunk=False`` for chunk-like boundaries.
                is_streaming_chunk = etype.endswith(".streaming")

                # Use unified accumulator with namespace from event parameter
                display_text = self._state.streaming_accumulator.accumulate(
                    etype,
                    content,
                    namespace=namespace,  # Use namespace from _handle_custom_event parameter
                    is_chunk=is_streaming_chunk,
                )

                if display_text:
                    # Clean and display
                    cleaned = self._clean_assistant_text(
                        display_text,
                        is_streaming=is_streaming_chunk,
                    )
                    if cleaned:
                        self._emit_assistant_text(
                            cleaned,
                            is_main=True,
                            is_streaming=is_streaming_chunk,
                        )

                # Lock final answer for non-streaming final events
                if not is_streaming_chunk:
                    self._presentation.mark_final_answer_locked()
                    # Finalize stream
                    self._state.streaming_accumulator.finalize_stream(etype, namespace=namespace)
            return

        category = classify_event_to_tier(etype, namespace)

        # Check for multi-step plan from PLAN_CREATED event
        if etype == PLAN_CREATED and len(data.get("steps", [])) > 1:
            self._state.multi_step_active = True

        # Agentic loop started: track multi-iteration but suppress the goal echo
        # (the goal just duplicates the user's input shown above)
        # Note: Continue to renderer.on_progress_event() to synchronize renderer state (IG-143 fix)
        if etype == "soothe.cognition.agent_loop.started" and data.get("max_iterations", 1) > 1:
            self._state.multi_step_active = True

        # Update plan state and call specific hooks
        if etype == PLAN_CREATED:
            self._handle_plan_created(data)
        elif etype == PLAN_STEP_STARTED:
            self._handle_plan_step_started(data)
        elif etype == PLAN_STEP_COMPLETED:
            self._handle_plan_step_completed(data)
        elif category == VerbosityTier.QUIET and "error" in etype:
            error_text = data.get("error", data.get("message", str(etype)))
            self._renderer.on_error(error_text)
        elif self._presentation.tier_visible(category, self._verbosity):
            self._renderer.on_progress_event(etype, data_for_progress, namespace=namespace)

    def _handle_plan_created(self, data: dict[str, Any]) -> None:
        """Handle plan creation event."""
        from soothe_sdk.client.schemas import Plan, PlanStep

        steps = [
            PlanStep(
                step_id=str(s.get("step_id") or s.get("id") or i),
                description=str(s.get("description", "")),
                status=str(s.get("status", "pending")),
            )
            for i, s in enumerate(data.get("steps", []))
        ]
        plan = Plan(
            plan_id=str(data.get("plan_id") or "local-plan"),
            goal=str(data.get("goal", "")),
            steps=steps,
            status=str(data.get("plan_status", data.get("status", "created"))),
        )
        self._state.current_plan = plan
        self._renderer.on_plan_created(plan)

    def _handle_plan_step_started(self, data: dict[str, Any]) -> None:
        """Handle plan step started event."""
        step_id = data.get("step_id", "")
        description = data.get("description", "")

        if self._state.current_plan:
            for step in self._state.current_plan.steps:
                if step.step_id == step_id:
                    step.status = "in_progress"
                    break

        self._renderer.on_plan_step_started(step_id, description)

    def _handle_plan_step_completed(self, data: dict[str, Any]) -> None:
        """Handle plan step completed event."""
        step_id = data.get("step_id", "")
        success = data.get("success", False)
        duration_ms = data.get("duration_ms", 0)

        if self._state.current_plan:
            for step in self._state.current_plan.steps:
                if step.step_id == step_id:
                    step.status = "completed" if success else "failed"
                    break

        self._renderer.on_plan_step_completed(step_id, success, duration_ms)

    def _clean_assistant_text(self, text: str, *, is_streaming: bool = False) -> str:
        """Apply shared response cleaning for user-facing assistant text.

        Args:
            text: Text to clean.
            is_streaming: If True, preserve boundary whitespace for proper
                streaming chunk concatenation.
        """
        return self._policy.filter_content(
            strip_internal_tags(text),
            preserve_boundary_whitespace=is_streaming,
        )

    def _maybe_extract_quiet_answer(self, text: str) -> str:
        """Apply quiet-mode answer extraction with fallback."""
        if self._verbosity == "quiet":
            return self._policy.extract_quiet_answer(text)
        return text

    def _get_effective_streaming_config(self) -> Any:
        """Get effective streaming config with defaults (RFC-614).

        Since EventProcessor doesn't have direct access to CLI config,
        we use sensible defaults based on initialization parameters.

        Returns:
            Dict with enabled, mode, execution_streaming, synthesis_streaming fields.
        """
        # Use defaults - streaming is enabled by default per RFC-614
        # final_output_mode controls batch/streaming display mode
        config = {
            "enabled": True,
            "mode": self._final_output_mode
            if self._final_output_mode in {"streaming", "batch"}
            else "streaming",
            "execution_streaming": True,
            "synthesis_streaming": True,
        }

        return config

    def _should_stream_event_type(self, etype: str, config: dict[str, Any]) -> bool:
        """Check if event type should be streamed based on config (RFC-614).

        Args:
            etype: Event type string.
            config: Effective config dict with enabled, mode, per-phase flags.

        Returns:
            True if event should be streamed/processed, False to skip.
        """
        if not config.get("enabled", True):
            return False

        # Non-streaming output events (e.g., chitchat/quiz/responded) are
        # always eligible when output streaming is enabled globally.
        if not etype.endswith(".streaming"):
            return True

        # In batch mode, suppress synthesized goal-completion stream chunks.
        if config.get("mode") == "batch" and etype == "soothe.output.goal_completion.streaming":
            return False

        # Check specific streaming flags
        if etype == "soothe.output.execution.streaming":
            return config.get("execution_streaming", True)
        if etype == "soothe.output.goal_completion.streaming":
            return config.get("synthesis_streaming", True)
        if etype == "soothe.output.tool_response.streaming":
            return config.get("tool_response_streaming", False)

        # Default: stream all remaining *.streaming events when enabled.
        return True
