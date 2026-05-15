"""Core agent execution loop for the Textual UI (execute_task_textual)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain.agents.middleware.human_in_the_loop import (
        HITLDecision,
    )
    from langgraph.types import Interrupt

from soothe_sdk.core.subagent_wire import is_allowlisted_subagent_event_type
from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux.loop_stream import LOOP_ASSISTANT_OUTPUT_PHASES, assistant_output_phase
from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id, scoped_subgraph_tool_key

from soothe_cli.shared.commands.subagent_routing import parse_subagent_from_input
from soothe_cli.shared.core.presentation_engine import PresentationEngine
from soothe_cli.shared.events.essential_events import (
    LOOP_REASON_EVENT_TYPE,
)
from soothe_cli.shared.rendering.renderer_base import RendererBase
from soothe_cli.shared.tools.message_processing import (
    _normalize_tool_name_for_arg_map,
    accumulate_tool_call_chunks,
    extract_tool_args_dict,
)
from soothe_cli.shared.tools.tool_call_resolution import build_streaming_args_overlay
from soothe_cli.shared.tools.tool_card_payload import extract_tool_result_card_payload
from soothe_cli.shared.tools.tool_card_visibility import (
    should_elide_completed_tool_call_message,
    should_elide_stream_tool_card_mount,
    should_elide_tool_card_no_info,
)
from soothe_cli.tui._ask_user_types import AskUserRequest
from soothe_cli.tui._cli_context import CLIContext  # noqa: TC001
from soothe_cli.tui._session_stats import SessionStats
from soothe_cli.tui.config import build_stream_config
from soothe_cli.tui.file_ops import FileOpTracker
from soothe_cli.tui.hooks import dispatch_hook
from soothe_cli.tui.input import MediaTracker, parse_file_mentions
from soothe_cli.tui.media_utils import create_multimodal_content

# Import from sibling modules within this sub-package
from soothe_cli.tui.textual_adapter._adapter import (
    AGENT_LOOP_GOAL_COMPLETED,
    AGENT_LOOP_GOAL_STARTED,
    AGENT_LOOP_STEP_COMPLETED,
    AGENT_LOOP_STEP_STARTED,
    TextualUIAdapter,
    _get_ask_user_adapter,
    _get_hitl_request_adapter,
)
from soothe_cli.tui.textual_adapter._stream_formatting import (
    _flush_router_pending_subgraph_tools,
    _format_display_line_for_tui,
    _format_progress_event_lines_for_tui,
    _is_summarization_chunk,
    _mount_subagent_inner_tool_row_if_resolved,
    _raw_tool_content_for_presentation,
    _try_register_task_scoped_inner_tool_pending,
)
from soothe_cli.tui.textual_adapter._stream_messages import (
    _assistant_message_terminal_for_empty_tool_arg_mount,
    _defer_first_tool_card_mount_until_final_stream_chunk,
    _defer_tool_card_for_empty_streaming_args,
    _normalize_lc_stream_message,
    _tui_effective_ai_blocks,
    _tui_goal_completion_matches_prior_main_visible_answer,
)
from soothe_cli.tui.textual_adapter._turn_helpers import (
    _adapter_has_pending_tools,
    _finalize_goal_completion_stream,
    _flush_assistant_text_ns,
    _goal_completion_time_footer_if_needed,
    _handle_interrupt_cleanup,
    _hitl_reject_step_tool_rows,
    _hitl_start_step_tool_rows,
    _read_mentioned_file,
    _report_and_persist_tokens,
)
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    CognitionReasonMessage,
    CognitionStepMessage,
    DiffMessage,
    SummarizationMessage,
    ToolCallMessage,
)

logger = logging.getLogger(__name__)


async def execute_task_textual(
    user_input: str,
    assistant_id: str | None,
    session_state: Any,  # noqa: ANN401  # Dynamic session state type
    adapter: TextualUIAdapter,
    image_tracker: MediaTracker | None = None,
    context: CLIContext | None = None,
    *,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
    sandbox_type: str | None = None,
    workspace: str | None = None,
    message_kwargs: dict[str, Any] | None = None,
    turn_stats: SessionStats | None = None,
    skip_daemon_send_turn: bool = False,
) -> SessionStats:
    """Execute a task with output directed to Textual UI.

    This is the Textual-compatible version of execute_task() that uses
    the TextualUIAdapter for all UI operations.

    Args:
        user_input: The user's input message
        daemon_session: Connected daemon websocket session (exclusive execution path).
            When ``skip_daemon_send_turn=True``, only consumes chunks (prompt already
            queued server-side).
        assistant_id: The agent identifier
        session_state: Session state with auto_approve flag
        adapter: The TextualUIAdapter for UI operations
        image_tracker: Optional tracker for images
        context: Optional `CLIContext` with model override and params, passed
            to the graph via `context=`.
        sandbox_type: Sandbox provider name for trace metadata, or `None`
            if no sandbox is active.
        workspace: Resolved project directory (status-bar cwd / daemon bootstrap)
            mirrored into stream ``configurable.workspace``; when omitted,
            ``build_stream_config`` uses ``Path.cwd()`` (IG-341).
        message_kwargs: Extra fields merged into the stream input message
            dict (e.g., `additional_kwargs` for persisting skill metadata
            in the checkpoint).
        turn_stats: Pre-created `SessionStats` to accumulate into.

            When the caller holds a reference to the same object, stats are
            available even if this coroutine is cancelled before it can return.

            If `None`, a new instance is created internally.
        skip_daemon_send_turn: When ``True``, skip ``send_turn`` and only consume
            chunks (prompt already queued, e.g. after ``invoke_skill`` or a
            running loop).

    Returns:
        Stats accumulated over this turn (request count, token counts,
            wall-clock time).

    Raises:
        ValidationError: If HITL request validation fails (re-raised).
    """
    from langchain.agents.middleware.human_in_the_loop import (
        ApproveDecision,
        HITLRequest,
        RejectDecision,
    )
    from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
    from langgraph.types import Command
    from pydantic import ValidationError

    from soothe_cli.cli.stream import StreamDisplayPipeline

    if daemon_session is None:
        raise RuntimeError("execute_task_textual requires daemon_session")

    hitl_request_adapter = _get_hitl_request_adapter(HITLRequest)
    ask_user_adapter = _get_ask_user_adapter()
    show_tool_ui = True
    logger.debug("TUI turn: fixed normal UX show_tool_ui=%s", show_tool_ui)
    progress_pipeline = StreamDisplayPipeline()
    presentation = PresentationEngine()

    # Parse file mentions and inject content if any — defer blocking I/O
    prompt_text, mentioned_files = await asyncio.to_thread(parse_file_mentions, user_input)

    # Max file size to embed inline (256KB, matching mistral-vibe)
    # Larger files get a reference instead - use read_file tool to view them
    max_embed_bytes = 256 * 1024

    if mentioned_files:
        context_parts = [prompt_text, "\n\n## Referenced Files\n"]
        for file_path in mentioned_files:
            try:
                part = await asyncio.to_thread(_read_mentioned_file, file_path, max_embed_bytes)
                context_parts.append(part)
            except Exception as e:  # noqa: BLE001  # Resilient adapter error handling
                context_parts.append(f"\n### {file_path.name}\n[Error reading file: {e}]")
        final_input = "\n".join(context_parts)
    else:
        final_input = prompt_text

    # Include images and videos in the message content
    images_to_send = []
    videos_to_send = []
    if image_tracker:
        images_to_send = image_tracker.get_images()
        videos_to_send = image_tracker.get_videos()
    if images_to_send or videos_to_send:
        message_content = create_multimodal_content(final_input, images_to_send, videos_to_send)
    else:
        message_content = final_input

    loop_id = session_state.loop_id
    config = build_stream_config(
        loop_id,
        assistant_id,
        sandbox_type=sandbox_type,
        workspace=workspace,
    )

    await dispatch_hook("session.start", {"loop_id": loop_id})

    captured_input_tokens = 0
    captured_output_tokens = 0
    if turn_stats is None:
        turn_stats = SessionStats()
    start_time = time.monotonic()

    # Warn if token display callbacks are only partially wired — all three
    # should be set together to avoid inconsistent status-bar behavior.
    token_cbs = (
        adapter._on_tokens_update,
        adapter._on_tokens_hide,
        adapter._on_tokens_show,
    )
    if any(token_cbs) and not all(token_cbs):
        logger.warning(
            "Token callbacks partially wired (update=%s, hide=%s, show=%s); token display may behave inconsistently",
            adapter._on_tokens_update is not None,
            adapter._on_tokens_hide is not None,
            adapter._on_tokens_show is not None,
        )

    # Show spinner
    if adapter._set_spinner:
        await adapter._set_spinner("Thinking")

    # Hide token display during streaming (will be shown with accurate count at end)
    if adapter._on_tokens_hide:
        adapter._on_tokens_hide()

    file_op_tracker = FileOpTracker(assistant_id=assistant_id)
    router = adapter._step_router
    router.reset_turn()
    adapter._task_inner_tool_pending_lines.clear()
    adapter._task_inner_tool_start_times.clear()
    displayed_tool_ids: set[str] = set()
    tool_call_buffers: dict[str | int, dict] = {}
    # Streaming tool-call args (``tool_call_chunks``) — mirrors EventProcessor / IG-053
    pending_tool_calls_lc: dict[str, dict[str, Any]] = {}

    # Track pending text and assistant messages PER NAMESPACE to avoid interleaving
    # when multiple subagents stream in parallel
    pending_text_by_namespace: dict[tuple, str] = {}
    assistant_message_by_namespace: dict[tuple, Any] = {}
    goal_completion_stream_by_namespace: dict[tuple, AssistantMessage] = {}
    goal_loop_start_monotonic: float | None = None
    task_loop_assistant_by_tcid: dict[str, str] = {}

    # Clear media from tracker after creating the message
    if image_tracker:
        image_tracker.clear()

    user_msg: dict[str, Any] = {"role": "user", "content": message_content}
    if message_kwargs:
        user_msg.update(message_kwargs)
    stream_input: dict | Command = {"messages": [user_msg]}
    cfg_workspace = (config.get("configurable") or {}).get("workspace")
    if cfg_workspace:
        stream_input["workspace"] = cfg_workspace

    # Track summarization lifecycle so spinner status and notification stay in sync.
    summarization_in_progress = False
    try:
        while True:
            interrupt_occurred = False
            suppress_resumed_output = False
            pending_interrupts: dict[str, HITLRequest] = {}
            pending_ask_user: dict[str, AskUserRequest] = {}

            if isinstance(stream_input, Command):
                resume_data = getattr(stream_input, "resume", None)
                if not isinstance(resume_data, dict):
                    raise ValueError("Invalid daemon resume payload")
                await daemon_session.resume_interrupts(resume_data)
                chunk_source = daemon_session.iter_turn_chunks()
            elif skip_daemon_send_turn:
                chunk_source = daemon_session.iter_turn_chunks()
            else:
                daemon_text = message_content if isinstance(message_content, str) else final_input
                subagent_name, routed_text = parse_subagent_from_input(
                    daemon_text if isinstance(daemon_text, str) else final_input
                )
                ctx_model = context.get("model") if context else None
                raw_mp = context.get("model_params") if context else None
                mp = raw_mp if isinstance(raw_mp, dict) else None
                image_attachments: list[dict[str, str]] | None = None
                if images_to_send:
                    image_attachments = [
                        {
                            "mime_type": f"image/{img.format}",
                            "data": img.base64_data,
                        }
                        for img in images_to_send
                    ]
                await daemon_session.send_turn(
                    routed_text,
                    interactive=True,
                    preferred_subagent=subagent_name,
                    model=ctx_model if isinstance(ctx_model, str) and ctx_model.strip() else None,
                    model_params=mp,
                    attachments=image_attachments,
                )
                chunk_source = daemon_session.iter_turn_chunks()

            async for chunk in chunk_source:
                if not isinstance(chunk, (list, tuple)) or len(chunk) != 3:  # noqa: PLR2004
                    logger.debug("Skipping invalid stream chunk: %s", type(chunk).__name__)
                    continue

                namespace, current_stream_mode, data = chunk

                # Convert namespace to hashable tuple for dict keys
                ns_key = tuple(namespace) if namespace else ()

                # IG-416 debug: Log every chunk arrival
                if current_stream_mode == "custom" and isinstance(data, dict):
                    event_type = str(data.get("type", ""))
                    logger.info(
                        "[TUI_CHUNK] mode=%s ns=%r event_type=%s",
                        current_stream_mode,
                        ns_key,
                        event_type,
                    )

                # Root graph uses namespace ``()``; delegated subgraphs use non-empty
                # namespaces. Assistant *text* from subgraphs is suppressed (avoid duplicate
                # prose with main). Tool-call UI is gated by ``show_tool_ui``, not namespace.
                is_main_agent = ns_key == ()
                suppress_subgraph_assistant_text = not is_main_agent
                suppress_main_agent_assistant_text = False

                # Handle UPDATES stream - for interrupts and todos
                if current_stream_mode == "updates":
                    if not isinstance(data, dict):
                        continue

                    # Check for interrupts
                    if "__interrupt__" in data:
                        interrupts: list[Interrupt] = data["__interrupt__"]
                        if interrupts:
                            for interrupt_obj in interrupts:
                                iv = interrupt_obj.value
                                if isinstance(iv, dict) and iv.get("type") == "ask_user":
                                    try:
                                        validated_ask_user = ask_user_adapter.validate_python(iv)
                                        pending_ask_user[interrupt_obj.id] = validated_ask_user
                                        interrupt_occurred = True
                                        await dispatch_hook("input.required", {})
                                    except ValidationError:
                                        logger.exception("Invalid ask_user interrupt payload")
                                        raise
                                else:
                                    try:
                                        validated_request = hitl_request_adapter.validate_python(iv)
                                        pending_interrupts[interrupt_obj.id] = validated_request
                                        interrupt_occurred = True
                                        await dispatch_hook("input.required", {})
                                    except ValidationError:  # noqa: TRY203  # Re-raise preserves exception context in handler
                                        raise

                    # Check for todo updates (not yet implemented in Textual UI)
                    chunk_data = next(iter(data.values())) if data else None
                    if chunk_data and isinstance(chunk_data, dict) and "todos" in chunk_data:
                        pass  # Future: render todo list widget

                # Handle MESSAGES stream - for content and tool calls
                elif current_stream_mode == "messages":
                    if ns_key:
                        router.on_subgraph_namespace(ns_key)

                    if not isinstance(data, (list, tuple)) or len(data) != 2:  # noqa: PLR2004
                        logger.debug(
                            "Skipping non-pair message data: type=%s",
                            type(data).__name__,
                        )
                        continue

                    message, metadata = data
                    message = _normalize_lc_stream_message(message)

                    # Filter out summarization model output, but keep UI feedback.
                    # The summarization model streams AIMessage chunks tagged
                    # with lc_source="summarization" in the callback metadata.
                    # These are hidden from the user; only the spinner and a
                    # notification widget provide feedback.
                    if _is_summarization_chunk(metadata):
                        if not summarization_in_progress:
                            summarization_in_progress = True
                            if adapter._set_spinner:
                                await adapter._set_spinner("Offloading")
                        continue

                    # Regular (non-summarization) chunks resumed — summarization
                    # has finished. Mount the notification and reset the spinner.
                    if summarization_in_progress:
                        summarization_in_progress = False
                        try:
                            await adapter._mount_message(SummarizationMessage())
                        except Exception:
                            logger.debug(
                                "Failed to mount summarization notification",
                                exc_info=True,
                            )
                        if adapter._set_spinner and not _adapter_has_pending_tools(adapter):
                            await adapter._set_spinner("Thinking")

                    if isinstance(message, HumanMessage):
                        content = message.text
                        # Flush pending text for this namespace
                        pending_text = pending_text_by_namespace.get(ns_key, "")
                        if content and pending_text:
                            await _flush_assistant_text_ns(
                                adapter,
                                pending_text,
                                ns_key,
                                assistant_message_by_namespace,
                                router=router,
                            )
                            pending_text_by_namespace[ns_key] = ""
                        continue

                    tool_card = extract_tool_result_card_payload(message)
                    if tool_card is not None:
                        tool_id = tool_card.tool_call_id or None
                        if tool_id:
                            pending_tool_calls_lc.pop(str(tool_id), None)

                        if not show_tool_ui:
                            logger.debug(
                                "Tool result skipped (tool UI off): tool_call_id=%r name=%r",
                                tool_id,
                                tool_card.tool_name,
                            )
                            continue

                        if not tool_id:
                            logger.debug(
                                "Tool result has no tool_call_id (cannot match card): name=%r",
                                tool_card.tool_name,
                            )

                        record = file_op_tracker.complete_with_message(message)

                        # Update tool call status with output (unified ToolMessage / wire dict)
                        sid = str(tool_id) if tool_id else ""
                        row_key = (
                            scoped_subgraph_tool_key(ns_key, sid)
                            if sid and not is_main_agent
                            else sid
                        )
                        output_str = tool_card.output_display
                        handled_step = False
                        if row_key:
                            step_w = adapter._tool_to_step.pop(row_key, None)
                            if step_w is not None:
                                handled_step = True
                                dur_ms = step_w.row_duration_ms_since_started(row_key)
                                logger.debug(
                                    "Tool result matched step row: tool_call_id=%s error=%s",
                                    row_key,
                                    tool_card.is_error,
                                )
                                if not tool_card.is_error:
                                    step_w.set_tool_success(row_key, output_str, duration_ms=dur_ms)
                                else:
                                    step_w.set_tool_error(
                                        row_key, output_str or "Error", duration_ms=dur_ms
                                    )
                                    await dispatch_hook(
                                        "tool.error",
                                        {"tool_names": [tool_card.tool_name or "tool"]},
                                    )

                        handled_card = False
                        if sid and sid in adapter._current_tool_messages:
                            handled_card = True
                            # Pop before widget calls so the dict drains even
                            # if set_success/set_error raises.
                            tool_msg = adapter._current_tool_messages.pop(sid)
                            logger.debug(
                                "Tool result matched pending card: tool_call_id=%s name=%s error=%s",
                                sid,
                                tool_msg._tool_name,
                                tool_card.is_error,
                            )
                            if not tool_card.is_error:
                                tool_msg.set_success(output_str)
                                # Standalone ``task`` card: keep until subgraph completes so
                                # activity lines have a parent (when not using step aggregation).
                                if _normalize_tool_name_for_arg_map(
                                    tool_msg._tool_name
                                ) != "task" and should_elide_completed_tool_call_message(
                                    tool_msg, output_str, is_error=False
                                ):
                                    adapter._tool_display_by_call_id.pop(sid, None)
                                    await tool_msg.remove()
                            else:
                                tool_msg.set_error(output_str or "Error")
                                await dispatch_hook(
                                    "tool.error",
                                    {"tool_names": [tool_msg._tool_name]},
                                )

                        handled_task_inner = False
                        if (
                            row_key
                            and show_tool_ui
                            and presentation.tier_visible(VerbosityTier.NORMAL)
                        ):
                            pending_ln = adapter._task_inner_tool_pending_lines.pop(row_key, None)
                            start_tm = adapter._task_inner_tool_start_times.pop(row_key, None)
                            if pending_ln:
                                ts_ap = router.resolve_task_scope(ns_key)
                                if ts_ap and ts_ap[0]:
                                    parent_task = router.resolve_parent(
                                        ts_ap,
                                        step_cards=adapter._current_step_messages,
                                        tool_display_by_call_id=adapter._tool_display_by_call_id,
                                    )
                                    if parent_task is not None:
                                        duration_ms = (
                                            int((time.time() - start_tm) * 1000) if start_tm else 0
                                        )
                                        raw_body = _raw_tool_content_for_presentation(message)
                                        tname = tool_card.tool_name or "tool"
                                        status_ln = presentation.format_tool_result_status_line(
                                            tname,
                                            raw_body,
                                            is_error=tool_card.is_error,
                                            duration_ms=duration_ms,
                                        )
                                        parent_task.append_subagent_activity(
                                            f"{pending_ln} -> {status_ln}"
                                        )
                                        handled_task_inner = True

                        if (
                            tool_id
                            and show_tool_ui
                            and not (handled_step or handled_card or handled_task_inner)
                        ):
                            # Orphan result: no pending Task card / step row matched this id.
                            # Prefer attaching to the active step card; never mount standalone
                            # tool widgets (except the dedicated ``task`` delegation card).
                            tname = tool_card.tool_name or "tool"
                            output_str = tool_card.output_display
                            # Subgraph tool results without a parent row stay suppressed.
                            if not is_main_agent:
                                logger.debug(
                                    "Tool result orphan suppressed (subagent): "
                                    "tool_call_id=%s name=%s",
                                    tool_id,
                                    tname,
                                )
                            elif should_elide_tool_card_no_info(
                                tool_name=tname,
                                args={},
                                formatted_output=output_str,
                                is_error=tool_card.is_error,
                            ):
                                logger.debug(
                                    "Tool result orphan skipped (IG-300 no-info): "
                                    "tool_call_id=%s name=%s",
                                    tool_id,
                                    tname,
                                )
                            else:
                                step_attach = adapter._step_by_namespace.get(ns_key)
                                if (
                                    is_main_agent
                                    and step_attach is not None
                                    and sid
                                    and show_tool_ui
                                ):
                                    if not step_attach.has_tool_call_row(sid):
                                        step_attach.add_tool_call(
                                            sid,
                                            tname,
                                            {},
                                            raw_args="",
                                        )
                                        adapter._tool_to_step[sid] = step_attach
                                    o_dur = step_attach.row_duration_ms_since_started(sid)
                                    logger.debug(
                                        "Tool result orphan attached to step card: "
                                        "tool_call_id=%s name=%s",
                                        tool_id,
                                        tname,
                                    )
                                    if not tool_card.is_error:
                                        step_attach.set_tool_success(
                                            sid, output_str, duration_ms=o_dur
                                        )
                                    else:
                                        step_attach.set_tool_error(
                                            sid, output_str or "Error", duration_ms=o_dur
                                        )
                                        await dispatch_hook(
                                            "tool.error",
                                            {"tool_names": [tname]},
                                        )
                                else:
                                    logger.debug(
                                        "Tool result orphan suppressed (no standalone cards): "
                                        "tool_call_id=%s name=%s",
                                        tool_id,
                                        tname,
                                    )

                        # Reshow spinner only when all in-flight tools have
                        # completed (avoids premature "Thinking..." when
                        # parallel tool calls are active).
                        if adapter._set_spinner and not _adapter_has_pending_tools(adapter):
                            await adapter._set_spinner("Thinking")

                        # Show file operation results - always show diffs in chat
                        if record:
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                            if record.diff:
                                await adapter._mount_message(
                                    DiffMessage(record.diff, record.display_path)
                                )
                        continue

                    # Extract token usage (before content_blocks check
                    # - usage may be on any chunk)
                    if hasattr(message, "usage_metadata"):
                        usage = message.usage_metadata
                        if usage:
                            input_toks = usage.get("input_tokens", 0)
                            output_toks = usage.get("output_tokens", 0)
                            total_toks = usage.get("total_tokens", 0)
                            from soothe_cli.tui.config import settings

                            active_model = settings.model_name or ""
                            if input_toks or output_toks:
                                # Model gives split counts — preferred path
                                turn_stats.record_request(active_model, input_toks, output_toks)
                                captured_input_tokens = max(
                                    captured_input_tokens, input_toks + output_toks
                                )
                            elif total_toks:
                                # Fallback: model gives only total (no split)
                                turn_stats.record_request(active_model, total_toks, 0)
                                captured_input_tokens = max(captured_input_tokens, total_toks)

                    streaming_overlay: dict[str, dict[str, Any]] = {}
                    if isinstance(message, (AIMessage, AIMessageChunk)):
                        accumulate_tool_call_chunks(
                            pending_tool_calls_lc,
                            getattr(message, "tool_call_chunks", None) or [],
                            is_main=(ns_key == ()),
                        )
                        streaming_overlay = build_streaming_args_overlay(
                            message, pending_tool_calls_lc
                        )

                    blocks = _tui_effective_ai_blocks(
                        message,
                        ns_key=ns_key,
                        streaming_overlay=streaming_overlay or None,
                    )
                    if not blocks:
                        continue

                    # ``phase=goal_completion`` → standalone ``AssistantMessage`` (all namespaces).
                    if getattr(message, "phase", None) == "goal_completion":
                        from langchain_core.messages import AIMessageChunk

                        text_gc = "".join(
                            str(b.get("text", ""))
                            for b in blocks
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                        is_gc_chunk = isinstance(message, AIMessageChunk)
                        if text_gc == "" and is_gc_chunk:
                            continue

                        output_text = text_gc
                        pending_text = pending_text_by_namespace.get(ns_key, "")
                        existing_msg = assistant_message_by_namespace.get(ns_key)
                        stream_msg = goal_completion_stream_by_namespace.get(ns_key)
                        is_synthesis_stream_chunk = is_gc_chunk

                        if is_synthesis_stream_chunk:
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)

                            if stream_msg is None:
                                if adapter._set_spinner:
                                    await adapter._set_spinner("Synthesizing")
                                msg_id = f"asst-{uuid.uuid4().hex[:8]}"
                                if adapter._set_active_message:
                                    adapter._set_active_message(msg_id)
                                stream_msg = AssistantMessage(id=msg_id)
                                await adapter._mount_message(stream_msg)
                                goal_completion_stream_by_namespace[ns_key] = stream_msg

                            await stream_msg.append_content(output_text)
                            if getattr(message, "chunk_position", None) == "last":
                                await _finalize_goal_completion_stream(
                                    adapter,
                                    stream_msg,
                                    ns_key=ns_key,
                                    goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
                                    assistant_message_by_namespace=assistant_message_by_namespace,
                                    extra_text="",
                                    goal_loop_start_monotonic=goal_loop_start_monotonic,
                                    turn_start_monotonic=start_time,
                                )
                            continue

                        if stream_msg is not None:
                            await _finalize_goal_completion_stream(
                                adapter,
                                stream_msg,
                                ns_key=ns_key,
                                goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
                                assistant_message_by_namespace=assistant_message_by_namespace,
                                extra_text=output_text,
                                goal_loop_start_monotonic=goal_loop_start_monotonic,
                                turn_start_monotonic=start_time,
                            )
                            continue

                        if existing_msg is not None:
                            if adapter._set_active_message:
                                adapter._set_active_message(None)
                            if adapter._set_spinner:
                                await adapter._set_spinner("Thinking")
                            continue

                        if (
                            not is_gc_chunk
                            and _tui_goal_completion_matches_prior_main_visible_answer(
                                adapter,
                                ns_key=ns_key,
                                output_text=output_text,
                                pending_execute_text=pending_text,
                            )
                        ):
                            if adapter._set_active_message:
                                adapter._set_active_message(None)
                            if adapter._set_spinner:
                                await adapter._set_spinner("Thinking")
                            continue

                        if pending_text:
                            await _flush_assistant_text_ns(
                                adapter,
                                pending_text,
                                ns_key,
                                assistant_message_by_namespace,
                                router=router,
                            )
                            pending_text_by_namespace[ns_key] = ""
                            assistant_message_by_namespace.pop(ns_key, None)

                        repaired_output = RendererBase.repair_concatenated_output(output_text)
                        footer = _goal_completion_time_footer_if_needed(
                            repaired_output,
                            goal_loop_start_monotonic=goal_loop_start_monotonic,
                            turn_start_monotonic=start_time,
                        )
                        if footer:
                            repaired_output += footer
                        output_widget = AssistantMessage(
                            repaired_output,
                            id=f"asst-{uuid.uuid4().hex[:8]}",
                        )
                        await adapter._mount_message(output_widget)
                        await output_widget.write_initial_content()
                        if adapter._sync_message_content and output_widget.id:
                            adapter._sync_message_content(
                                output_widget.id,
                                repaired_output,
                            )
                        assistant_message_by_namespace[ns_key] = output_widget

                        if adapter._set_active_message:
                            adapter._set_active_message(None)
                        if adapter._set_spinner:
                            await adapter._set_spinner("Thinking")
                        continue

                    for block in blocks:
                        block_type = block.get("type")

                        if block_type == "text":
                            if suppress_main_agent_assistant_text:
                                continue
                            task_scope_txt = router.resolve_task_scope(ns_key) if ns_key else None
                            phase_loop = getattr(message, "phase", None)
                            text = block.get("text", "") or ""
                            if task_scope_txt is not None:
                                if (
                                    phase_loop
                                    in (
                                        "execute_step",
                                        "execute_wave",
                                    )
                                    and text.strip()
                                ):
                                    tcid = str(task_scope_txt[0] or "").strip()
                                    if tcid:
                                        parent_tool = router.resolve_parent(
                                            task_scope_txt,
                                            step_cards=adapter._current_step_messages,
                                            tool_display_by_call_id=adapter._tool_display_by_call_id,
                                        )
                                        if parent_tool is not None and hasattr(
                                            parent_tool, "set_result_preview"
                                        ):
                                            prev = task_loop_assistant_by_tcid.get(tcid, "")
                                            task_loop_assistant_by_tcid[tcid] = prev + text
                                            parent_tool.set_result_preview(
                                                task_loop_assistant_by_tcid[tcid]
                                            )
                                continue
                            if suppress_subgraph_assistant_text:
                                continue
                            if not text:
                                continue
                            if phase_loop == "execute_step" and is_main_agent and text.strip():
                                step_w = adapter._step_by_namespace.get(ns_key)
                                if step_w is not None:
                                    step_w.append_execute_assistant_delta(text)
                                # Never mount standalone assistant cards for execute-step prose
                                # (aggregated on the step card when present).
                                continue

                            # Main graph: skip standalone AssistantMessage cards for
                            # intermediate AIMessage streams (execute_wave, unphased, etc.).
                            # ``goal_completion`` is handled above. Other RFC-614 user-output
                            # phases (quiz, autonomous_goal) still use cards.
                            if (
                                is_main_agent
                                and assistant_output_phase(message)
                                not in LOOP_ASSISTANT_OUTPUT_PHASES
                            ):
                                continue

                            # Track accumulated text for reference
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            pending_text += text
                            pending_text_by_namespace[ns_key] = pending_text

                            # Get or create assistant message for this namespace
                            current_msg = assistant_message_by_namespace.get(ns_key)
                            if current_msg is None:
                                if adapter._set_spinner:
                                    await adapter._set_spinner("Writing")
                                msg_id = f"asst-{uuid.uuid4().hex[:8]}"
                                # Mark active BEFORE mounting so pruning
                                # (triggered by mount) won't remove it
                                # (_mount_message can trigger
                                # _prune_old_messages if the window exceeds
                                # WINDOW_SIZE.)
                                if adapter._set_active_message:
                                    adapter._set_active_message(msg_id)
                                current_msg = AssistantMessage(id=msg_id)
                                await adapter._mount_message(current_msg)
                                assistant_message_by_namespace[ns_key] = current_msg

                            # Append just the new text chunk for smoother
                            # streaming (batched plain-text updates on the card)
                            await current_msg.append_content(text)

                        elif block_type in {"tool_call_chunk", "tool_call", "tool_use"}:
                            chunk_name = block.get("name")
                            chunk_args = block.get("args")
                            if chunk_args is None and block_type == "tool_use":
                                chunk_args = block.get("input")
                            chunk_id = block.get("id")
                            chunk_index = block.get("index")

                            buffer_key: str | int
                            if chunk_index is not None:
                                buffer_key = chunk_index
                            elif chunk_id is not None:
                                buffer_key = chunk_id
                            else:
                                buffer_key = f"unknown-{len(tool_call_buffers)}"

                            buffer = tool_call_buffers.setdefault(
                                buffer_key,
                                {
                                    "name": None,
                                    "id": None,
                                    "args": None,
                                    "args_parts": [],
                                },
                            )

                            if chunk_name:
                                buffer["name"] = chunk_name
                            if chunk_id:
                                buffer["id"] = chunk_id

                            if isinstance(chunk_args, dict):
                                buffer["args"] = chunk_args
                                buffer["args_parts"] = []
                            elif isinstance(chunk_args, str):
                                if chunk_args:
                                    parts: list[str] = buffer.setdefault("args_parts", [])
                                    if not parts or chunk_args != parts[-1]:
                                        parts.append(chunk_args)
                                    buffer["args"] = "".join(parts)
                            elif chunk_args is not None:
                                buffer["args"] = chunk_args

                            buffer_name = buffer.get("name")
                            buffer_id = buffer.get("id")
                            if buffer_name is None:
                                continue

                            parsed_args = buffer.get("args")
                            if isinstance(parsed_args, str):
                                if not parsed_args:
                                    continue
                                try:
                                    parsed_args = json.loads(parsed_args)
                                except json.JSONDecodeError:
                                    continue
                            elif parsed_args is None:
                                continue

                            if not isinstance(parsed_args, dict):
                                parsed_args = {"value": parsed_args}

                            if isinstance(parsed_args, dict):
                                parsed_args = extract_tool_args_dict(parsed_args)

                            lookup_id = str(buffer_id) if buffer_id is not None else ""

                            # Flush pending text before tool call
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)

                            args_meaningful = bool(parsed_args)

                            # IG-403: Per-step task spawn + namespace bind (not global FIFO).
                            # IG-416: Extract step_id from unified tool_call_id format.
                            if (
                                lookup_id
                                and is_main_agent
                                and buffer_name == "task"
                                and args_meaningful
                            ):
                                # Parse unified tool_call_id to get step_id directly
                                parsed_step_id, parsed_type, _, _ = parse_unified_tool_call_id(
                                    str(lookup_id)
                                )
                                # Use parsed step_id from unified ID, fallback to router
                                bound_step_id = parsed_step_id or router.step_id_for_tool(
                                    str(lookup_id)
                                )
                                raw_st = parsed_args.get("subagent_type", "")
                                subagent_type = raw_st.strip() if isinstance(raw_st, str) else ""
                                if router.register_task_spawn(
                                    str(lookup_id),
                                    subagent_type,
                                    step_id=bound_step_id,
                                ):
                                    await _flush_router_pending_subgraph_tools(
                                        adapter,
                                        router,
                                        show_tool_ui=show_tool_ui,
                                        pending_tool_calls_lc=pending_tool_calls_lc,
                                        file_op_tracker=file_op_tracker,
                                    )
                                    if bound_step_id:
                                        step_w = adapter._current_step_messages.get(bound_step_id)
                                        if step_w is not None:
                                            raw_spawn = ""
                                            pend_spawn = pending_tool_calls_lc.get(str(lookup_id))
                                            if isinstance(pend_spawn, dict):
                                                raw_spawn = str(pend_spawn.get("args_str", ""))
                                            if not step_w.has_tool_call_row(str(lookup_id)):
                                                step_w.add_tool_call(
                                                    str(lookup_id),
                                                    buffer_name or "task",
                                                    parsed_args,
                                                    raw_args=raw_spawn,
                                                )
                                            adapter._tool_to_step[str(lookup_id)] = step_w
                                    elif lookup_id not in adapter._current_tool_messages:
                                        task_card = ToolCallMessage(
                                            buffer_name,
                                            parsed_args,
                                            tool_call_id=lookup_id,
                                        )
                                        await adapter._mount_message(task_card)
                                        task_card.set_running()
                                        adapter._current_tool_messages[lookup_id] = task_card
                                        adapter._tool_display_by_call_id[str(lookup_id)] = task_card

                            if not args_meaningful and _defer_tool_card_for_empty_streaming_args(
                                message
                            ):
                                # Keep buffer; a later chunk should carry real kwargs.
                                logger.debug(
                                    "Tool call card deferred (streaming args incomplete): "
                                    "name=%s id=%r chunk_position=%r",
                                    buffer_name,
                                    chunk_id,
                                    getattr(message, "chunk_position", None),
                                )
                                continue

                            existing_tool = None
                            if lookup_id:
                                step_agg = adapter._step_by_namespace.get(ns_key)
                                if (
                                    step_agg is not None
                                    and is_main_agent
                                    and step_agg.has_tool_call_row(lookup_id)
                                ):
                                    step_agg.update_tool_args(lookup_id, parsed_args)
                                    logger.debug(
                                        "Tool call args refreshed on step card: id=%s name=%s",
                                        lookup_id,
                                        buffer_name,
                                    )
                                    tool_call_buffers.pop(buffer_key, None)
                                    continue
                                existing_tool = adapter._current_tool_messages.get(
                                    lookup_id
                                ) or adapter._tool_display_by_call_id.get(lookup_id)
                            if (
                                lookup_id
                                and args_meaningful
                                and existing_tool is not None
                                and not (is_main_agent and buffer_name == "task")
                            ):
                                if isinstance(existing_tool, ToolCallMessage):
                                    existing_tool.refresh_tool_args(parsed_args)
                                elif isinstance(existing_tool, CognitionStepMessage):
                                    existing_tool.update_tool_args(str(lookup_id), parsed_args)
                                logger.debug(
                                    "Tool call args refreshed on existing card: id=%s name=%s",
                                    lookup_id,
                                    buffer_name,
                                )
                                tool_call_buffers.pop(buffer_key, None)
                                continue

                            display_key = (
                                scoped_subgraph_tool_key(ns_key, str(lookup_id))
                                if lookup_id and not is_main_agent
                                else str(lookup_id)
                            )
                            if display_key and display_key not in displayed_tool_ids:
                                # IG-416: Extract step_id from unified tool_call_id
                                if lookup_id and is_main_agent:
                                    parsed_sid, _, _, _ = parse_unified_tool_call_id(str(lookup_id))
                                    bound_step = parsed_sid or router.step_id_for_tool(
                                        str(lookup_id)
                                    )
                                    if bound_step:
                                        step_card_bound = adapter._current_step_messages.get(
                                            bound_step
                                        )
                                        if step_card_bound and getattr(
                                            step_card_bound, "has_tool_call_row", lambda _x: False
                                        )(str(lookup_id)):
                                            # Already mounted via binding event, just update args
                                            if parsed_args:
                                                update_fn = getattr(
                                                    step_card_bound, "update_tool_args", None
                                                )
                                                if callable(update_fn):
                                                    update_fn(str(lookup_id), parsed_args)
                                            displayed_tool_ids.add(display_key)
                                            logger.debug(
                                                "Tool call args refreshed (binding-mounted): "
                                                "id=%s name=%s step_id=%s",
                                                lookup_id,
                                                buffer_name,
                                                bound_step,
                                            )
                                            tool_call_buffers.pop(buffer_key, None)
                                            continue
                                # IG-416: Parse unified ID for step_id
                                parsed_sid_early = ""
                                if lookup_id:
                                    parsed_sid_early, _, _, _ = parse_unified_tool_call_id(
                                        str(lookup_id)
                                    )
                                bound_early = parsed_sid_early or (
                                    router.step_id_for_tool(str(lookup_id)) if lookup_id else ""
                                )
                                step_card_early = (
                                    adapter._current_step_messages.get(bound_early)
                                    if bound_early
                                    else None
                                )
                                parent_early = None
                                if not is_main_agent:
                                    ts_early = router.resolve_task_scope(ns_key)
                                    if ts_early:
                                        parent_early = router.resolve_parent(
                                            ts_early,
                                            step_cards=adapter._current_step_messages,
                                            tool_display_by_call_id=adapter._tool_display_by_call_id,
                                        )
                                skip_defer_mount = (
                                    is_main_agent and step_card_early is not None
                                ) or (not is_main_agent and parent_early is not None)
                                if (
                                    not skip_defer_mount
                                    and _defer_first_tool_card_mount_until_final_stream_chunk(
                                        message
                                    )
                                ):
                                    logger.debug(
                                        "Tool call first mount deferred (non-final stream chunk): "
                                        "name=%s tool_call_id=%r chunk_position=%r",
                                        buffer_name,
                                        lookup_id,
                                        getattr(message, "chunk_position", None),
                                    )
                                    continue
                                elide_empty_args_card = should_elide_stream_tool_card_mount(
                                    tool_name=buffer_name or "",
                                    args=parsed_args,
                                    message_terminal_for_tool_args=_assistant_message_terminal_for_empty_tool_arg_mount(
                                        message
                                    ),
                                )
                                if elide_empty_args_card:
                                    displayed_tool_ids.add(display_key)
                                    _try_register_task_scoped_inner_tool_pending(
                                        adapter,
                                        router,
                                        lookup_id=str(lookup_id),
                                        buffer_name=buffer_name,
                                        parsed_args=parsed_args,
                                        is_main_agent=is_main_agent,
                                        ns_key=ns_key,
                                        show_tool_ui=show_tool_ui,
                                        presentation=presentation,
                                    )
                                    if await _mount_subagent_inner_tool_row_if_resolved(
                                        adapter,
                                        router,
                                        lookup_id=str(lookup_id),
                                        buffer_name=buffer_name,
                                        parsed_args=parsed_args,
                                        buffer_id=buffer_id,
                                        ns_key=ns_key,
                                        show_tool_ui=show_tool_ui,
                                        is_main_agent=is_main_agent,
                                        pending_tool_calls_lc=pending_tool_calls_lc,
                                        file_op_tracker=file_op_tracker,
                                    ):
                                        logger.debug(
                                            "Tool call card skipped (IG-300 terminal empty args); "
                                            "subagent row on parent: name=%s tool_call_id=%r "
                                            "chunk_position=%r",
                                            buffer_name,
                                            lookup_id,
                                            getattr(message, "chunk_position", None),
                                        )
                                        tool_call_buffers.pop(buffer_key, None)
                                        continue
                                    if not is_main_agent:
                                        router.buffer_subgraph_tool(
                                            ns_key=ns_key,
                                            lookup_id=str(lookup_id),
                                            display_key=display_key,
                                            tool_name=buffer_name or "tool",
                                            args=parsed_args,
                                        )
                                        tool_call_buffers.pop(buffer_key, None)
                                        continue
                                    logger.debug(
                                        "Tool call card skipped (IG-300 terminal empty args); "
                                        "main agent — aggregating on step: name=%s tool_call_id=%r",
                                        buffer_name,
                                        lookup_id,
                                    )
                                else:
                                    displayed_tool_ids.add(display_key)
                                    _try_register_task_scoped_inner_tool_pending(
                                        adapter,
                                        router,
                                        lookup_id=str(lookup_id),
                                        buffer_name=buffer_name,
                                        parsed_args=parsed_args,
                                        is_main_agent=is_main_agent,
                                        ns_key=ns_key,
                                        show_tool_ui=show_tool_ui,
                                        presentation=presentation,
                                    )
                                    if await _mount_subagent_inner_tool_row_if_resolved(
                                        adapter,
                                        router,
                                        lookup_id=str(lookup_id),
                                        buffer_name=buffer_name,
                                        parsed_args=parsed_args,
                                        buffer_id=buffer_id,
                                        ns_key=ns_key,
                                        show_tool_ui=show_tool_ui,
                                        is_main_agent=is_main_agent,
                                        pending_tool_calls_lc=pending_tool_calls_lc,
                                        file_op_tracker=file_op_tracker,
                                    ):
                                        tool_call_buffers.pop(buffer_key, None)
                                        continue
                                if show_tool_ui:
                                    file_op_tracker.start_operation(
                                        buffer_name, parsed_args, buffer_id
                                    )

                                    if adapter._set_spinner:
                                        await adapter._set_spinner("Tools")

                                    # IG-416: Parse unified ID for step_id, fallback to router binding
                                    parsed_sid = ""
                                    if lookup_id:
                                        parsed_sid, _, _, _ = parse_unified_tool_call_id(
                                            str(lookup_id)
                                        )
                                    bound_step_id = parsed_sid or router.step_id_for_tool(
                                        str(lookup_id)
                                    )
                                    if bound_step_id:
                                        active_step = adapter._current_step_messages.get(
                                            bound_step_id
                                        )
                                    else:
                                        # Fallback to namespace lookup (existing behavior)
                                        active_step = adapter._step_by_namespace.get(ns_key)
                                    use_step_aggregator = is_main_agent and active_step is not None
                                    if use_step_aggregator:
                                        # IG-402: Pass _raw from streaming accumulator so
                                        # format_tool_call_args can use its regex fallback.
                                        raw = ""
                                        pend = pending_tool_calls_lc.get(str(lookup_id))
                                        if isinstance(pend, dict):
                                            raw = str(pend.get("args_str", ""))
                                        active_step.add_tool_call(
                                            lookup_id,
                                            buffer_name or "tool",
                                            parsed_args,
                                            raw_args=raw,
                                        )
                                        adapter._tool_to_step[lookup_id] = active_step
                                        logger.debug(
                                            "Tool call row on step card: name=%s "
                                            "tool_call_id=%s namespace=%s",
                                            buffer_name,
                                            lookup_id,
                                            ns_key,
                                        )
                                    elif is_main_agent:
                                        # IG-402: No step card yet — buffer this tool so it can
                                        # be retroactively attached when step_started arrives.
                                        raw = ""
                                        pend = pending_tool_calls_lc.get(str(lookup_id))
                                        if isinstance(pend, dict):
                                            raw = str(pend.get("args_str", ""))
                                        router.buffer_main_tool(
                                            str(lookup_id),
                                            buffer_name or "tool",
                                            parsed_args,
                                            raw_args=raw,
                                        )
                                        if buffer_name != "task":
                                            # Pending marker for non-task tools: subagent
                                            # resolution sees this and knows the parent exists
                                            # but hasn't been flushed yet.
                                            adapter._tool_display_by_call_id[str(lookup_id)] = None
                                        logger.debug(
                                            "Tool call buffered for step aggregation: name=%s "
                                            "tool_call_id=%s namespace=%s",
                                            buffer_name,
                                            lookup_id,
                                            ns_key,
                                        )
                                    else:
                                        # Buffer until namespace → task scope resolves.
                                        raw_sg = ""
                                        pend_sg = pending_tool_calls_lc.get(str(lookup_id))
                                        if isinstance(pend_sg, dict):
                                            raw_sg = str(pend_sg.get("args_str", ""))
                                        router.buffer_subgraph_tool(
                                            ns_key=ns_key,
                                            lookup_id=str(lookup_id),
                                            display_key=display_key,
                                            tool_name=buffer_name or "tool",
                                            args=parsed_args,
                                            raw_args=raw_sg,
                                        )
                                        logger.debug(
                                            "Subagent tool buffered (parent pending): "
                                            "name=%s tool_call_id=%s namespace=%s",
                                            buffer_name,
                                            lookup_id,
                                            ns_key,
                                        )
                                else:
                                    logger.debug(
                                        "Tool call block not shown as card (tool UI off): "
                                        "name=%s tool_call_id=%s",
                                        buffer_name,
                                        lookup_id,
                                    )
                            elif show_tool_ui and args_meaningful and buffer_name and not lookup_id:
                                logger.debug(
                                    "Tool call has no stable id; card not mounted: "
                                    "name=%s namespace=%s",
                                    buffer_name,
                                    ns_key,
                                )

                            tool_call_buffers.pop(buffer_key, None)

                    if getattr(message, "chunk_position", None) == "last":
                        pending_text = pending_text_by_namespace.get(ns_key, "")
                        if pending_text:
                            await _flush_assistant_text_ns(
                                adapter,
                                pending_text,
                                ns_key,
                                assistant_message_by_namespace,
                                router=router,
                            )
                            pending_text_by_namespace[ns_key] = ""
                            assistant_message_by_namespace.pop(ns_key, None)

                elif current_stream_mode == "custom":
                    if isinstance(data, dict):
                        event_type = str(data.get("type", ""))
                        if event_type.startswith("soothe.error"):
                            error_text = str(
                                data.get("error") or data.get("message") or "Agent error"
                            )
                            adapter.finalize_pending_tools_with_error(error_text)
                            adapter.finalize_pending_steps_with_error(error_text)
                            await adapter._mount_message(AppMessage(error_text))
                            if adapter._set_spinner:
                                await adapter._set_spinner(None)
                            continue

                        if event_type == AGENT_LOOP_GOAL_STARTED:
                            if not ns_key:
                                goal_loop_start_monotonic = time.monotonic()
                                adapter._last_completed_main_step_execute_prose = ""
                                adapter._last_main_flushed_assistant_prose = ""
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)
                            continue

                        if event_type == AGENT_LOOP_GOAL_COMPLETED:
                            continue

                        if event_type == AGENT_LOOP_STEP_STARTED:
                            step_id = str(data.get("step_id", "")).strip()
                            description = str(data.get("description", "")).strip()
                            logger.info(
                                "[STEP_STARTED] received step_id=%s description=%s ns=%r",
                                step_id,
                                description[:50] if description else "",
                                ns_key,
                            )
                            if step_id:
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                        router=router,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)
                                step_widget = CognitionStepMessage(
                                    step_id=step_id,
                                    description=description or "(step)",
                                    id=f"step-{uuid.uuid4().hex[:8]}",
                                )
                                await adapter._mount_message(step_widget)
                                step_widget.set_running()
                                adapter._current_step_messages[step_id] = step_widget
                                adapter._step_by_namespace[ns_key] = step_widget
                                router.on_step_started(step_id)
                                # IG-416 debug: Log step card creation
                                logger.info(
                                    "[STEP_STARTED] CREATED step_card step_id=%s ns=%r "
                                    "current_step_messages_keys=%s",
                                    step_id,
                                    ns_key,
                                    list(adapter._current_step_messages.keys()),
                                )
                                router.route_pending_main_tools(
                                    adapter._current_step_messages,
                                    adapter._tool_to_step,
                                    adapter._tool_display_by_call_id,
                                )
                                await _flush_router_pending_subgraph_tools(
                                    adapter,
                                    router,
                                    show_tool_ui=show_tool_ui,
                                    pending_tool_calls_lc=pending_tool_calls_lc,
                                    file_op_tracker=file_op_tracker,
                                )

                                continue

                        if event_type == AGENT_LOOP_STEP_COMPLETED:
                            step_id = str(data.get("step_id", "")).strip()
                            if step_id:
                                router.on_step_completed(step_id)
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                        router=router,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)
                                success = bool(data.get("success", True))
                                duration_ms = int(data.get("duration_ms", 0))
                                tool_call_count = int(data.get("tool_call_count", 0))
                                summary = str(
                                    data.get("summary", "") or data.get("output_preview", "") or ""
                                )
                                if not summary.strip():
                                    summary = "Failed" if not success else "Done"
                                widget = adapter._current_step_messages.pop(step_id, None)
                                if widget is not None:
                                    if adapter._step_by_namespace.get(ns_key) is widget:
                                        adapter._step_by_namespace.pop(ns_key, None)
                                    stale_tool_ids = [
                                        k for k, sw in adapter._tool_to_step.items() if sw is widget
                                    ]
                                    for k in stale_tool_ids:
                                        adapter._tool_to_step.pop(k, None)
                                    # Clean up tool-to-step bindings for this step
                                    router.clear_step_tool_bindings(step_id)
                                    for k, parent in list(adapter._tool_display_by_call_id.items()):
                                        if parent is widget:
                                            adapter._tool_display_by_call_id.pop(k, None)
                                    widget.set_complete(
                                        success,
                                        duration_ms,
                                        tool_call_count,
                                        summary,
                                    )
                                    if not ns_key:
                                        adapter._last_completed_main_step_execute_prose = (
                                            widget.last_completed_execute_prose
                                        )
                                else:
                                    ev = dict(data)
                                    ev["namespace"] = list(ns_key)
                                    for line in progress_pipeline.process(ev):
                                        line_text = _format_display_line_for_tui(line)
                                        if line_text:
                                            await adapter._mount_message(AppMessage(line_text))
                                continue

                        if event_type == LOOP_REASON_EVENT_TYPE:
                            ev_plan = dict(data)
                            ev_plan["namespace"] = list(ns_key)
                            plan_lines = progress_pipeline.process(ev_plan)
                            if not plan_lines:
                                continue
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)
                            pa_raw = data.get("plan_action", "")
                            plan_action = pa_raw if pa_raw in ("keep", "new") else ""
                            plan_widget = CognitionReasonMessage(
                                next_action=str(data.get("next_action", "")),
                                status=str(data.get("status", "")),
                                iteration=int(data.get("iteration", 0)),
                                plan_action=str(plan_action),
                                assessment_reasoning=str(data.get("assessment_reasoning", "")),
                                plan_reasoning=str(data.get("plan_reasoning", "")),
                                id=f"plan-{uuid.uuid4().hex[:8]}",
                            )
                            await adapter._mount_message(plan_widget)
                            continue

                        if ns_key:
                            router.on_subgraph_namespace(ns_key)
                        task_scope = router.resolve_task_scope(ns_key)
                        if (
                            task_scope
                            and event_type.startswith("soothe.subagent.")
                            and is_allowlisted_subagent_event_type(event_type)
                        ):
                            tcid = task_scope[0]
                            card = router.resolve_parent(
                                task_scope,
                                step_cards=adapter._current_step_messages,
                                tool_display_by_call_id=adapter._tool_display_by_call_id,
                            )
                            if card is None and tcid:
                                card = adapter._current_tool_messages.get(tcid)
                            ev_wire = dict(data)
                            ev_wire.setdefault("type", event_type)
                            ev_wire["namespace"] = list(ns_key)
                            ev_wire["task_scope"] = task_scope
                            wire_lines = [
                                _format_display_line_for_tui(line)
                                for line in progress_pipeline.process(ev_wire)
                            ]
                            wire_lines = [ln for ln in wire_lines if ln]
                            if card is not None:
                                for line_text in wire_lines:
                                    card.append_subagent_activity(line_text)
                                continue

                        progress_lines = _format_progress_event_lines_for_tui(
                            data,
                            ns_key,
                            pipeline=progress_pipeline,
                            task_scope=task_scope,
                        )
                        if progress_lines:
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)
                            for progress_line in progress_lines:
                                await adapter._mount_message(AppMessage(progress_line))
                            continue

            # Reset summarization state if stream ended mid-summarization
            # (e.g. middleware error, stream exhausted before regular chunks).
            if summarization_in_progress:
                summarization_in_progress = False
                try:
                    await adapter._mount_message(SummarizationMessage())
                except Exception:
                    logger.debug(
                        "Failed to mount summarization notification",
                        exc_info=True,
                    )
                if adapter._set_spinner and not _adapter_has_pending_tools(adapter):
                    await adapter._set_spinner("Thinking")

            # Flush any remaining text from all namespaces
            for ns_key, pending_text in list(pending_text_by_namespace.items()):
                if pending_text:
                    await _flush_assistant_text_ns(
                        adapter,
                        pending_text,
                        ns_key,
                        assistant_message_by_namespace,
                        router=router,
                    )
            for ns_key, stream_msg in list(goal_completion_stream_by_namespace.items()):
                await _finalize_goal_completion_stream(
                    adapter,
                    stream_msg,
                    ns_key=ns_key,
                    goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
                    assistant_message_by_namespace=assistant_message_by_namespace,
                    extra_text="",
                    goal_loop_start_monotonic=goal_loop_start_monotonic,
                    turn_start_monotonic=start_time,
                )
            pending_text_by_namespace.clear()
            assistant_message_by_namespace.clear()
            task_loop_assistant_by_tcid.clear()

            # Buffered tools without a step card: do not mount standalone tool cards.
            routed_main = router.route_pending_main_tools(
                adapter._current_step_messages,
                adapter._tool_to_step,
                adapter._tool_display_by_call_id,
            )
            if routed_main:
                logger.debug(
                    "Routed %d pending main-namespace tool row(s) at stream end",
                    routed_main,
                )
            elif router.pending_main_tool_count:
                logger.debug(
                    "Dropping %d pending main-namespace tool row(s) (no step card)",
                    router.pending_main_tool_count,
                )
            pending_sub = router.pending_subgraph_tools()
            if pending_sub:
                logger.debug(
                    "Dropping %d pending subgraph tool row(s) (parent unresolved)",
                    len(pending_sub),
                )

            # Safety net: finalize any steps/tools still in-flight (e.g. worker
            # crash sent a soothe.error.* event but step_completed was never
            # emitted, or stream ended before matching results arrived).
            if adapter._current_step_messages or adapter._current_tool_messages:
                adapter.finalize_pending_tools_with_error("Stream ended unexpectedly")
                adapter.finalize_pending_steps_with_error("Stream ended unexpectedly")

            # Handle HITL after stream completes
            if interrupt_occurred:
                any_rejected = False
                resume_payload: dict[str, Any] = {}

                for interrupt_id, ask_req in list(pending_ask_user.items()):
                    questions = ask_req["questions"]

                    if adapter._request_ask_user:
                        if adapter._set_spinner:
                            await adapter._set_spinner(None)
                        result: dict[str, Any] = {
                            "type": "error",
                            "error": "ask_user callback returned no response",
                        }
                        try:
                            future = await adapter._request_ask_user(questions)
                        except Exception:
                            logger.exception("Failed to mount ask_user widget")
                            result = {
                                "type": "error",
                                "error": "failed to display ask_user prompt",
                            }
                            future = None

                        if future is None:
                            logger.error("ask_user callback returned no Future; reporting as error")
                        else:
                            try:
                                future_result = await future
                                if isinstance(future_result, dict):
                                    result = future_result
                                else:
                                    logger.error(
                                        "ask_user future returned non-dict result: %s",
                                        type(future_result).__name__,
                                    )
                                    result = {
                                        "type": "error",
                                        "error": "invalid ask_user widget result",
                                    }
                            except Exception:
                                logger.exception(
                                    "ask_user future resolution failed; reporting as error"
                                )
                                result = {
                                    "type": "error",
                                    "error": "failed to receive ask_user response",
                                }

                        result_type = result.get("type")
                        if result_type == "answered":
                            answers = result.get("answers", [])
                            if isinstance(answers, list):
                                resume_payload[interrupt_id] = {"answers": answers}
                                tool_id = ask_req["tool_call_id"]
                                tc_sid = str(tool_id) if tool_id is not None else ""
                                if tc_sid and tc_sid in adapter._current_tool_messages:
                                    tool_msg = adapter._current_tool_messages[tc_sid]
                                    tool_msg.set_success("User answered")
                                    adapter._current_tool_messages.pop(tc_sid, None)
                                if tc_sid:
                                    st_w = adapter._tool_to_step.pop(tc_sid, None)
                                    if st_w is not None:
                                        st_w.set_tool_success(
                                            tc_sid, "User answered", duration_ms=0
                                        )
                            else:
                                logger.error(
                                    "ask_user answered payload had non-list answers: %s",
                                    type(answers).__name__,
                                )
                                resume_payload[interrupt_id] = {
                                    "status": "error",
                                    "error": "invalid ask_user answers payload",
                                    "answers": ["" for _ in questions],
                                }
                                any_rejected = True
                        elif result_type == "cancelled":
                            resume_payload[interrupt_id] = {
                                "status": "cancelled",
                                "answers": ["" for _ in questions],
                            }
                            any_rejected = True
                        else:
                            error_text = result.get("error")
                            if not isinstance(error_text, str) or not error_text:
                                error_text = "ask_user interaction failed"
                            resume_payload[interrupt_id] = {
                                "status": "error",
                                "error": error_text,
                                "answers": ["" for _ in questions],
                            }
                            any_rejected = True
                    else:
                        logger.warning(
                            "ask_user interrupt received but no UI callback is registered; reporting as error"
                        )
                        resume_payload[interrupt_id] = {
                            "status": "error",
                            "error": "ask_user not supported by this UI",
                            "answers": ["" for _ in questions],
                        }

                for interrupt_id, hitl_request in list(pending_interrupts.items()):
                    action_requests = hitl_request["action_requests"]

                    if session_state.auto_approve:
                        decisions: list[HITLDecision] = [
                            ApproveDecision(type="approve") for _ in action_requests
                        ]
                        resume_payload[interrupt_id] = {"decisions": decisions}
                        for tool_msg in list(adapter._current_tool_messages.values()):
                            tool_msg.set_running()
                        _hitl_start_step_tool_rows(adapter)
                    else:
                        # Batch approval - one dialog for all parallel tool calls
                        await dispatch_hook(
                            "permission.request",
                            {"tool_names": [r.get("name", "") for r in action_requests]},
                        )
                        future = await adapter._request_approval(action_requests, assistant_id)
                        decision = await future

                        if isinstance(decision, dict):
                            decision_type = decision.get("type")

                            if decision_type == "auto_approve_all":
                                session_state.auto_approve = True
                                if adapter._on_auto_approve_enabled:
                                    adapter._on_auto_approve_enabled()
                                decisions = [
                                    ApproveDecision(type="approve") for _ in action_requests
                                ]
                                tool_msgs = list(adapter._current_tool_messages.values())
                                for tool_msg in tool_msgs:
                                    tool_msg.set_running()
                                _hitl_start_step_tool_rows(adapter)
                                for action_request in action_requests:
                                    tool_name = action_request.get("name")
                                    if tool_name in {
                                        "write_file",
                                        "edit_file",
                                    }:
                                        args = action_request.get("args", {})
                                        if isinstance(args, dict):
                                            file_op_tracker.mark_hitl_approved(tool_name, args)

                            elif decision_type == "approve":
                                decisions = [
                                    ApproveDecision(type="approve") for _ in action_requests
                                ]
                                tool_msgs = list(adapter._current_tool_messages.values())
                                for tool_msg in tool_msgs:
                                    tool_msg.set_running()
                                _hitl_start_step_tool_rows(adapter)
                                for action_request in action_requests:
                                    tool_name = action_request.get("name")
                                    if tool_name in {
                                        "write_file",
                                        "edit_file",
                                    }:
                                        args = action_request.get("args", {})
                                        if isinstance(args, dict):
                                            file_op_tracker.mark_hitl_approved(tool_name, args)

                            elif decision_type == "reject":
                                decisions = [RejectDecision(type="reject") for _ in action_requests]
                                _hitl_reject_step_tool_rows(adapter)
                                tool_msgs = list(adapter._current_tool_messages.values())
                                for tool_msg in tool_msgs:
                                    tool_msg.set_rejected()
                                adapter._current_tool_messages.clear()
                                adapter._tool_display_by_call_id.clear()
                                any_rejected = True
                            else:
                                logger.warning(
                                    "Unexpected HITL decision type: %s",
                                    decision_type,
                                )
                                decisions = [RejectDecision(type="reject") for _ in action_requests]
                                _hitl_reject_step_tool_rows(adapter)
                                for tool_msg in list(adapter._current_tool_messages.values()):
                                    tool_msg.set_rejected()
                                adapter._current_tool_messages.clear()
                                adapter._tool_display_by_call_id.clear()
                                any_rejected = True
                        else:
                            logger.warning(
                                "HITL decision was not a dict: %s",
                                type(decision).__name__,
                            )
                            decisions = [RejectDecision(type="reject") for _ in action_requests]
                            _hitl_reject_step_tool_rows(adapter)
                            for tool_msg in list(adapter._current_tool_messages.values()):
                                tool_msg.set_rejected()
                            adapter._current_tool_messages.clear()
                            adapter._tool_display_by_call_id.clear()
                            any_rejected = True

                        resume_payload[interrupt_id] = {"decisions": decisions}

                        if any_rejected:
                            break

                suppress_resumed_output = any_rejected

            if interrupt_occurred and resume_payload:
                if suppress_resumed_output and not pending_ask_user:
                    await adapter._mount_message(
                        AppMessage("Command rejected. Tell the agent what you'd like instead.")
                    )
                    turn_stats.wall_time_seconds = time.monotonic() - start_time
                    return turn_stats

                stream_input = Command(resume=resume_payload)
            else:
                await dispatch_hook("task.complete", {"loop_id": loop_id})
                break

    except (asyncio.CancelledError, KeyboardInterrupt):
        await _handle_interrupt_cleanup(
            adapter=adapter,
            config=config,
            daemon_session=daemon_session,
            pending_text_by_namespace=pending_text_by_namespace,
            captured_input_tokens=captured_input_tokens,
            captured_output_tokens=captured_output_tokens,
            turn_stats=turn_stats,
            start_time=start_time,
        )
        return turn_stats

    # Update token count and return stats
    turn_stats.wall_time_seconds = time.monotonic() - start_time
    await _report_and_persist_tokens(
        adapter,
        config,
        captured_input_tokens,
        captured_output_tokens,
        daemon_session=daemon_session,
    )
    return turn_stats
