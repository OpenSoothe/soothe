"""HITL, interrupt, token persistence, and text flush helpers for execute_task_textual."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from soothe_cli.tui.textual_adapter._adapter import TextualUIAdapter
    from soothe_cli.tui.widgets.messages import AssistantMessage

from soothe_sdk.ux.task_namespace import resolve_task_scope_for_namespace

from soothe_cli.shared.rendering.renderer_base import RendererBase
from soothe_cli.tui._session_stats import SessionStats
from soothe_cli.tui.widgets.messages import AppMessage, AssistantMessage

logger = logging.getLogger(__name__)


def _loop_id_for_remote_state(config: RunnableConfig, daemon_session: Any) -> str:
    """Resolve checkpoint thread id for daemon ``loop_state_*`` RPCs.

    Prefer ``configurable.thread_id`` from the stream config; fall back to the
    session's active loop when the config is empty (e.g. edge timing during
    bootstrap).
    """
    loop_id = str((config.get("configurable") or {}).get("thread_id") or "").strip()
    if loop_id:
        return loop_id
    raw = getattr(daemon_session, "loop_id", None)
    return str(raw or "").strip()


def _adapter_has_pending_tools(adapter: TextualUIAdapter) -> bool:
    """True while any tool is awaiting a ``ToolMessage`` (cards, step rows, or task-inner lines)."""
    if adapter._current_tool_messages or adapter._tool_to_step:
        return True
    return bool(adapter._task_inner_tool_pending_lines)


def _hitl_start_step_tool_rows(adapter: TextualUIAdapter) -> None:
    """Mark step-aggregated tool rows running after HITL approval (IG-402)."""
    for tcid, stw in list(adapter._tool_to_step.items()):
        stw.set_tool_running(tcid)


def _hitl_reject_step_tool_rows(adapter: TextualUIAdapter) -> None:
    """Mark step-aggregated tool rows rejected and drop pending bindings (IG-402)."""
    for tcid, stw in list(adapter._tool_to_step.items()):
        stw.set_tool_rejected(tcid)
    adapter._tool_to_step.clear()


def _build_interrupted_ai_message(
    pending_text_by_namespace: dict[tuple, str],
    adapter: TextualUIAdapter,
) -> Any:
    """Build an AIMessage capturing interrupted state (text + tool calls).

    Args:
        pending_text_by_namespace: Dict of accumulated text by namespace
        adapter: UI adapter with pending tool cards and step rows (IG-402).

    Returns:
        AIMessage with accumulated content and tool calls, or None if empty.
    """
    from langchain_core.messages import AIMessage

    main_ns_key = ()
    accumulated_text = pending_text_by_namespace.get(main_ns_key, "").strip()

    tool_calls: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for tool_id, tool_widget in list(adapter._current_tool_messages.items()):
        tool_calls.append(
            {
                "id": tool_id,
                "name": tool_widget._tool_name,
                "args": tool_widget._args,
            }
        )
        seen_ids.add(str(tool_id))

    for step_w in dict.fromkeys(adapter._tool_to_step.values()):
        if hasattr(step_w, "iter_open_tool_calls_for_interrupt"):
            for row in step_w.iter_open_tool_calls_for_interrupt():
                rid = str(row.get("id", ""))
                if rid and rid not in seen_ids:
                    tool_calls.append(row)
                    seen_ids.add(rid)

    if not accumulated_text and not tool_calls:
        return None

    return AIMessage(
        content=accumulated_text,
        tool_calls=tool_calls or [],
    )


def _read_mentioned_file(file_path: Any, max_embed_bytes: int) -> str:
    """Read a mentioned file for inline embedding (sync, for use with to_thread).

    Args:
        file_path: Resolved path to the file.
        max_embed_bytes: Size threshold; larger files get a reference only.

    Returns:
        Markdown snippet with the file content or a size-exceeded reference.
    """
    file_size = file_path.stat().st_size
    if file_size > max_embed_bytes:
        size_kb = file_size // 1024
        return (
            f"\n### {file_path.name}\n"
            f"Path: `{file_path}`\n"
            f"Size: {size_kb}KB (too large to embed, "
            "use read_file tool to view)"
        )
    content = file_path.read_text(encoding="utf-8")
    return f"\n### {file_path.name}\nPath: `{file_path}`\n```\n{content}\n```"


async def _finalize_goal_completion_stream(
    adapter: TextualUIAdapter,
    stream_msg: AssistantMessage,
    *,
    ns_key: tuple[Any, ...],
    goal_completion_stream_by_namespace: dict[tuple[Any, ...], AssistantMessage],
    assistant_message_by_namespace: dict[tuple[Any, ...], Any],
    extra_text: str,
) -> None:
    """Stop the goal_completion ``AssistantMessage`` stream and record it under ``ns_key``."""
    if extra_text and extra_text not in getattr(stream_msg, "_content", ""):
        await stream_msg.append_content(extra_text)
    # Expand before ending the stream so the first post-stream layout is full
    # body text (avoids a collapsed preview flash for long synthesis text).
    stream_msg.set_body_expanded(True)
    await stream_msg.stop_stream()
    if adapter._sync_message_content and stream_msg.id:
        adapter._sync_message_content(stream_msg.id, stream_msg._content)
    goal_completion_stream_by_namespace.pop(ns_key, None)
    assistant_message_by_namespace[ns_key] = stream_msg
    if adapter._set_active_message:
        adapter._set_active_message(None)
    if adapter._set_spinner:
        await adapter._set_spinner("Thinking")


async def _handle_interrupt_cleanup(
    *,
    adapter: TextualUIAdapter,
    config: RunnableConfig,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
    pending_text_by_namespace: dict[tuple, str],
    captured_input_tokens: int,
    captured_output_tokens: int,
    turn_stats: SessionStats,
    start_time: float,
) -> None:
    """Shared cleanup for CancelledError and KeyboardInterrupt.

    Args:
        adapter: UI adapter with display callbacks.
        config: Runnable config with loop_id mapped to thread_id in configurable.
        daemon_session: Active daemon websocket session; also receives ``/cancel``
            so the in-flight query stops (Ctrl+C / Esc; ``detach`` is quit-only).
        pending_text_by_namespace: Accumulated text per namespace.
        captured_input_tokens: Input tokens captured before interrupt.
        captured_output_tokens: Output tokens captured before interrupt.
        turn_stats: Stats for the current turn.
        start_time: Monotonic timestamp when the turn began.
    """
    import time

    from langchain_core.messages import HumanMessage
    from langchain_core.messages.base import messages_to_dict

    # Clear active message immediately so it won't block pruning.
    # If we don't do this, the store still thinks it's active and protects
    # from pruning, which breaks get_messages_to_prune(), potentially
    # blocking all future pruning.
    if adapter._set_active_message:
        adapter._set_active_message(None)

    # Hide spinner (may still show a stale status if interrupted)
    if adapter._set_spinner:
        await adapter._set_spinner(None)

    await adapter._mount_message(AppMessage("Interrupted by user"))

    interrupted_msg = _build_interrupted_ai_message(pending_text_by_namespace, adapter)

    # Save accumulated state before marking tools as rejected (best-effort).
    # State update failures shouldn't prevent cleanup.
    # Use shorter timeout (2s) during interrupt cleanup to avoid blocking cancel.
    try:
        cancellation_msg = HumanMessage(
            content="[SYSTEM] Task interrupted by user. Previous operation was cancelled."
        )
        loop_id = _loop_id_for_remote_state(config, daemon_session)
        if loop_id:
            if interrupted_msg:
                await daemon_session.aupdate_loop_state(
                    loop_id,
                    {"messages": messages_to_dict([interrupted_msg])},
                    timeout=2.0,
                )
            await daemon_session.aupdate_loop_state(
                loop_id,
                {"messages": messages_to_dict([cancellation_msg])},
                timeout=2.0,
            )
    except Exception:
        logger.warning("Failed to save interrupted state", exc_info=True)

    # Mark tools as rejected AFTER saving state
    for tool_msg in list(adapter._current_tool_messages.values()):
        tool_msg.set_rejected()
    adapter._current_tool_messages.clear()
    adapter._tool_display_by_call_id.clear()

    for step_msg in list(adapter._current_step_messages.values()):
        step_msg.set_interrupted("Interrupted by user")
    adapter._current_step_messages.clear()
    adapter._tool_to_step.clear()
    adapter._step_by_namespace.clear()
    adapter._pending_main_tools.clear()

    adapter._last_completed_main_step_execute_prose = ""
    adapter._last_main_flushed_assistant_prose = ""

    # Keep the token count marked stale whenever interrupted state was captured,
    # including tool-only turns after assistant text was already flushed.
    approximate = interrupted_msg is not None

    turn_stats.wall_time_seconds = time.monotonic() - start_time
    await _report_and_persist_tokens(
        adapter,
        config,
        captured_input_tokens,
        captured_output_tokens,
        shield=True,
        approximate=approximate,
        daemon_session=daemon_session,
    )

    # Ensure the daemon-side query is cancelled, not detached (detach is quit-only).
    try:
        await daemon_session.cancel_remote_query()
        logger.info("Sent cancel to daemon during interrupt cleanup")
    except Exception:
        logger.warning("Failed to send cancel to daemon during interrupt cleanup", exc_info=True)


async def _persist_context_tokens(
    config: RunnableConfig,
    tokens: int,
    *,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
) -> None:
    """Best-effort persist of the context token count into remote loop state."""
    try:
        loop_id = _loop_id_for_remote_state(config, daemon_session)
        if loop_id:
            await daemon_session.aupdate_loop_state(loop_id, {"_context_tokens": tokens})
    except Exception:  # non-critical; stale count on resume is acceptable
        logger.warning(
            "Failed to persist _context_tokens=%d; token count may be stale on resume",
            tokens,
            exc_info=True,
        )


async def _report_and_persist_tokens(
    adapter: TextualUIAdapter,
    config: RunnableConfig,
    captured_input_tokens: int,
    captured_output_tokens: int,
    *,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
    shield: bool = False,
    approximate: bool = False,
) -> None:
    """Update the token display and best-effort persist via ``loop_state_update``."""
    if captured_input_tokens or captured_output_tokens:
        if adapter._on_tokens_update:
            adapter._on_tokens_update(captured_input_tokens, approximate=approximate)
        if shield:
            try:
                await _persist_context_tokens(
                    config,
                    captured_input_tokens,
                    daemon_session=daemon_session,
                )
            except (Exception, asyncio.CancelledError):
                logger.debug(
                    "Token persist suppressed during interrupt cleanup",
                    exc_info=True,
                )
        else:
            await _persist_context_tokens(
                config,
                captured_input_tokens,
                daemon_session=daemon_session,
            )
    elif adapter._on_tokens_show:
        adapter._on_tokens_show(approximate=approximate)


async def _flush_assistant_text_ns(
    adapter: TextualUIAdapter,
    text: str,
    ns_key: tuple,
    assistant_message_by_namespace: dict[tuple, Any],
    *,
    namespace_task_bindings: dict[tuple[str, ...], tuple[str, str]] | None = None,
) -> None:
    """Flush accumulated assistant text for a specific namespace.

    Finalizes the streaming state on the assistant card.
    If no message exists yet, creates one with the full content.
    """
    from soothe_cli.cli.stream.task_scope import format_task_scope_prefix
    from soothe_cli.shared.events.explore_task_display import (
        format_explore_task_json_blob_for_display,
    )
    from soothe_cli.tui.textual_adapter._stream_messages import _tui_main_assistant_body_for_dedupe

    repaired_text = RendererBase.repair_concatenated_output(text)
    repaired_text = format_explore_task_json_blob_for_display(repaired_text)
    if not repaired_text.strip():
        return

    ts_card = None
    if namespace_task_bindings is not None and ns_key:
        ts_card = resolve_task_scope_for_namespace(namespace_task_bindings, ns_key)
    if ts_card and ts_card[0]:
        parent_tool = adapter._tool_display_by_call_id.get(ts_card[0])
        if parent_tool is not None:
            line = f"⚙ {format_task_scope_prefix(ts_card[0], ts_card[1])} {repaired_text.strip()}"
            parent_tool.append_subagent_activity(line)
            return
        # Suppress standalone AssistantMessage for all subagent tasks —
        # only goal_completion surfaces the final result.
        return

    current_msg = assistant_message_by_namespace.get(ns_key)
    if current_msg is None:
        # No message was created during streaming - create one with full content
        msg_id = f"asst-{uuid.uuid4().hex[:8]}"
        current_msg = AssistantMessage(repaired_text, id=msg_id)
        await adapter._mount_message(current_msg)
        await current_msg.write_initial_content()
        assistant_message_by_namespace[ns_key] = current_msg
    else:
        # Stop the stream to finalize the content
        await current_msg.stop_stream()
        # Normalize final rendered content after stream completion.
        if repaired_text != current_msg._content:
            await current_msg.set_content(repaired_text)

    # When the AssistantMessage was first mounted and recorded in the
    # MessageStore, it had empty content (streaming hadn't started yet).
    # Now that streaming is done, the widget holds the full text in
    # `_content`, but the store's MessageData still has `content=""`.
    # If the message is later pruned and re-hydrated, `to_widget()` would
    # recreate it from that stale empty string. This call copies the
    # widget's final content back into the store so re-hydration works.
    if adapter._sync_message_content and current_msg.id:
        adapter._sync_message_content(current_msg.id, current_msg._content)

    if not ns_key:
        adapter._last_main_flushed_assistant_prose = _tui_main_assistant_body_for_dedupe(
            getattr(current_msg, "_content", "") or ""
        )

    # Clear active message since streaming is done
    if adapter._set_active_message:
        adapter._set_active_message(None)
