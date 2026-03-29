"""Unified daemon event processor with pluggable rendering.

This module implements RFC-0019's unified event processing architecture.
EventProcessor handles all event routing, state management, and filtering,
delegating display to RendererProtocol implementations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.core.event_catalog import PLAN_CREATED, PLAN_STEP_COMPLETED, PLAN_STEP_STARTED
from soothe.core.verbosity_tier import (
    VerbosityTier,
    classify_event_to_tier,
    should_show,
)
from soothe.subagents.research.events import SUBAGENT_RESEARCH_INTERNAL_LLM
from soothe.ux.core.display_policy import DisplayPolicy, VerbosityLevel, normalize_verbosity
from soothe.ux.core.message_processing import (
    accumulate_tool_call_chunks,
    coerce_tool_call_args_to_dict,
    extract_tool_brief,
    finalize_pending_tool_call,
    normalize_tool_calls_list,
    strip_internal_tags,
    tool_calls_have_any_arg_dict,
    try_parse_pending_tool_call_args,
)
from soothe.ux.core.processor_state import ProcessorState
from soothe.ux.core.rendering import update_name_map_from_tool_calls

if TYPE_CHECKING:
    from soothe.protocols.planner import Plan
    from soothe.ux.core.renderer_protocol import RendererProtocol

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
    ) -> None:
        """Initialize processor with renderer and verbosity level.

        Args:
            renderer: Callback interface for display.
            verbosity: Progress visibility level.
        """
        self._renderer = renderer
        self._verbosity = normalize_verbosity(verbosity)
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

    def process_event(self, event: dict[str, Any]) -> None:
        """Main entry point - routes event to appropriate handler.

        Args:
            event: Daemon event dictionary with 'type' key.
        """
        event_type = event.get("type", "")

        if event_type == "status":
            self._handle_status(event)
        elif event_type == "event":
            self._handle_stream_event(event)
        elif event_type == "error":
            self._handle_error_event(event)
        # command_response and clear handled by caller if needed

    def _handle_status(self, event: dict[str, Any]) -> None:
        """Process status changes, update thread_id, call on_status_change."""
        state_str = event.get("state", "unknown")
        tid_raw = event.get("thread_id", self._state.thread_id)

        # Keep existing thread_id when daemon sends empty handshake
        tid = self._state.thread_id if tid_raw in (None, "") else str(tid_raw)
        previous_thread_id = self._state.thread_id
        self._state.thread_id = tid

        # Clear session state on thread change
        if tid and tid != previous_thread_id:
            self._state.clear_session()

        self._renderer.on_status_change(state_str)

        # On turn end, finalize streaming and call hook
        if state_str in {"idle", "stopped"}:
            self._state.reset_turn()
            self._renderer.on_turn_end()

    def _handle_stream_event(self, event: dict[str, Any]) -> None:
        """Route to messages or custom event handlers."""
        mode = event.get("mode", "")
        namespace = tuple(event.get("namespace", []))
        data = event.get("data")

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
                    if text and self._policy.should_show_assistant_text(
                        text,
                        is_main=is_main,
                        is_multi_step_active=self._state.multi_step_active,
                    ):
                        cleaned = self._clean_assistant_text(text)
                        if cleaned:
                            self._renderer.on_assistant_text(
                                self._maybe_extract_quiet_answer(cleaned),
                                is_main=is_main,
                                is_streaming=is_chunk,
                            )
                elif btype in ("tool_call", "tool_call_chunk"):
                    if has_tc_args:
                        continue
                    name = block.get("name", "")
                    if name and should_show(VerbosityTier.DETAILED, self._verbosity):
                        coerced = coerce_tool_call_args_to_dict(block.get("args"))
                        if not coerced and raw_tcs:
                            continue
                        tool_call_id = block.get("id", "")
                        self._renderer.on_tool_call(
                            name,
                            coerced,
                            tool_call_id,
                            is_main=is_main,
                        )
                        if coerced:
                            tool_call_emitted_from_blocks = True
        elif (
            is_main
            and isinstance(msg.content, str)
            and msg.content
            and self._policy.should_show_assistant_text(
                msg.content,
                is_main=is_main,
                is_multi_step_active=self._state.multi_step_active,
            )
        ):
            cleaned = self._clean_assistant_text(msg.content)
            if cleaned:
                self._renderer.on_assistant_text(
                    self._maybe_extract_quiet_answer(cleaned),
                    is_main=is_main,
                    is_streaming=is_chunk,
                )

        # Handle tool_calls attribute
        if tcs:
            for tc in tcs:
                name = tc.get("name", "")
                if not name or not should_show(VerbosityTier.DETAILED, self._verbosity):
                    continue
                tc_args = coerce_tool_call_args_to_dict(tc.get("args"))

                # Skip chunks with empty args
                if is_chunk and not tc_args and not has_tc_args:
                    continue

                if has_tc_args or (not tc_args and not tool_call_emitted_from_blocks):
                    tool_call_id = tc.get("id", "")
                    self._renderer.on_tool_call(name, tc_args, tool_call_id, is_main=is_main)

    def _handle_tool_message(
        self,
        msg: ToolMessage,
        *,
        is_main: bool,
        namespace: tuple[str, ...],  # noqa: ARG002
    ) -> None:
        """Handle ToolMessage objects."""
        if not should_show(VerbosityTier.DETAILED, self._verbosity):
            return

        tool_name = getattr(msg, "name", "tool")
        tool_call_id = getattr(msg, "tool_call_id", None) or ""
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        brief = extract_tool_brief(tool_name, content)

        # Finalize pending tool call if needed (IG-053)
        parsed_args, pending, needs_emit = finalize_pending_tool_call(
            self._state.pending_tool_calls,
            tool_call_id,
        )
        if needs_emit:
            self._renderer.on_tool_call(
                pending.get("name") or tool_name,
                parsed_args or {},
                tool_call_id,
                is_main=pending.get("is_main", is_main),
            )

        # Determine if error
        is_error = any(indicator in content.lower() for indicator in ["error", "failed", "exception", "traceback"])

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
        msg_id = msg.get("id", "")
        is_chunk = msg.get("type") == "AIMessageChunk"

        if not is_chunk:
            if msg_id and msg_id in self._state.seen_message_ids:
                return
            if msg_id:
                self._state.seen_message_ids.add(msg_id)

        # Process content blocks or content string
        blocks = msg.get("content_blocks") or []
        if not blocks:
            content = msg.get("content", "")
            if isinstance(content, list):
                blocks = content
            elif (
                is_main
                and isinstance(content, str)
                and content
                and self._policy.should_show_assistant_text(
                    content,
                    is_main=is_main,
                    is_multi_step_active=self._state.multi_step_active,
                )
            ):
                cleaned = self._clean_assistant_text(content)
                if cleaned:
                    self._renderer.on_assistant_text(
                        self._maybe_extract_quiet_answer(cleaned),
                        is_main=is_main,
                        is_streaming=is_chunk,
                    )

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                if text and self._policy.should_show_assistant_text(
                    text,
                    is_main=is_main,
                    is_multi_step_active=self._state.multi_step_active,
                ):
                    cleaned = self._clean_assistant_text(text)
                    if cleaned:
                        self._renderer.on_assistant_text(
                            self._maybe_extract_quiet_answer(cleaned),
                            is_main=is_main,
                            is_streaming=is_chunk,
                        )
            elif btype in ("tool_call_chunk", "tool_call"):
                name = block.get("name", "")
                if name and should_show(VerbosityTier.DETAILED, self._verbosity):
                    args = coerce_tool_call_args_to_dict(block.get("args", {}))
                    tool_call_id = block.get("id", "")
                    self._renderer.on_tool_call(name, args, tool_call_id, is_main=is_main)

        # Handle tool_call_chunks
        tool_call_chunks = msg.get("tool_call_chunks", [])
        if isinstance(tool_call_chunks, list):
            for tc in tool_call_chunks:
                if isinstance(tc, dict):
                    name = tc.get("name", "")
                    if name and should_show(VerbosityTier.DETAILED, self._verbosity):
                        args = coerce_tool_call_args_to_dict(tc.get("args", {}))
                        tool_call_id = tc.get("id", "")
                        self._renderer.on_tool_call(name, args, tool_call_id, is_main=is_main)

    def _emit_pending_tool_calls(self, is_main: bool) -> None:  # noqa: FBT001
        """Emit pending tool calls that have complete JSON args."""
        for tc_id, pending in list(self._state.pending_tool_calls.items()):
            if pending["emitted"]:
                continue
            parsed_args = try_parse_pending_tool_call_args(pending)
            if parsed_args is not None and should_show(VerbosityTier.DETAILED, self._verbosity):
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

        # Handle internal context tracking for research events
        if etype == SUBAGENT_RESEARCH_INTERNAL_LLM:
            self._state.internal_context_active = True
            return  # Don't display internal events

        # Exit internal context on non-internal research events
        if etype.startswith("soothe.subagent.research.") and etype != SUBAGENT_RESEARCH_INTERNAL_LLM:
            self._state.internal_context_active = False

        # Skip most tool events (handled by message layer) except research subagent events
        if etype.startswith("soothe.tool.") and not etype.startswith("soothe.subagent.research."):
            return

        # Handle chitchat/final responses through shared cleaner path
        if etype in {"soothe.output.chitchat.response", "soothe.output.autonomous.final_report"}:
            content = data.get("content", data.get("summary", ""))
            if content and should_show(VerbosityTier.QUIET, self._verbosity):
                cleaned = self._clean_assistant_text(content)
                if cleaned:
                    self._renderer.on_assistant_text(
                        self._maybe_extract_quiet_answer(cleaned),
                        is_main=True,
                        is_streaming=False,
                    )
            return

        category = classify_event_to_tier(etype, namespace)

        # Check for multi-step plan
        if etype == PLAN_CREATED and len(data.get("steps", [])) > 1:
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
        elif should_show(category, self._verbosity):
            self._renderer.on_progress_event(etype, data, namespace=namespace)

    def _handle_plan_created(self, data: dict[str, Any]) -> None:
        """Handle plan creation event."""
        from soothe.protocols.planner import Plan, PlanStep

        steps = [
            PlanStep(
                id=s.get("id", str(i)),
                description=s.get("description", ""),
                depends_on=s.get("depends_on", []),
                status="pending",
            )
            for i, s in enumerate(data.get("steps", []))
        ]
        plan = Plan(
            goal=data.get("goal", ""),
            steps=steps,
            reasoning=data.get("reasoning"),
            is_plan_only=data.get("is_plan_only", False),
        )
        self._state.current_plan = plan
        self._renderer.on_plan_created(plan)

    def _handle_plan_step_started(self, data: dict[str, Any]) -> None:
        """Handle plan step started event."""
        step_id = data.get("step_id", "")
        description = data.get("description", "")

        if self._state.current_plan:
            for step in self._state.current_plan.steps:
                if step.id == step_id:
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
                if step.id == step_id:
                    step.status = "completed" if success else "failed"
                    break

        self._renderer.on_plan_step_completed(step_id, success, duration_ms)

    def _clean_assistant_text(self, text: str) -> str:
        """Apply shared response cleaning for user-facing assistant text."""
        return self._policy.filter_content(strip_internal_tags(text))

    def _maybe_extract_quiet_answer(self, text: str) -> str:
        """Apply quiet-mode answer extraction with fallback."""
        if self._verbosity == "quiet":
            return self._policy.extract_quiet_answer(text)
        return text
