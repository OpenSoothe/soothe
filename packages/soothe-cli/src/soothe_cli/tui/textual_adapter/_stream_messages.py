"""Message normalization and AI content block building utilities for TUI streaming."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_cli.tui.textual_adapter._adapter import TextualUIAdapter

from soothe_sdk.client.wire import envelope_langchain_message_dict

from soothe_cli.shared.rendering.renderer_base import RendererBase

logger = logging.getLogger(__name__)


def _normalize_lc_stream_message(message: Any) -> Any:
    """Turn daemon JSON dicts into LangChain message objects when possible.

    ``DaemonSession._normalize_stream_data`` already does this; this is a safety net
    for any path that still yields a raw dict (restore failure, alternate transports).
    """
    if not isinstance(message, dict):
        return message
    try:
        from langchain_core.messages import messages_from_dict

        wrapped = envelope_langchain_message_dict(message)
        restored = messages_from_dict([wrapped])
        if restored:
            return restored[0]
    except Exception:
        logger.debug("TUI could not restore LangChain message from dict", exc_info=True)
    return message


def _coerce_ai_message_for_blocks(message: Any) -> Any:
    """Best-effort dict → ``AIMessage`` / ``AIMessageChunk`` for block extraction.

    If the wire payload uses ``type: \"AIMessage\"`` (class name) instead of ``ai``,
    :func:`messages_from_dict` would fail; :func:`envelope_langchain_message_dict`
    canonicalizes first (see ``daemon_session``).
    """
    from langchain_core.messages import AIMessage, AIMessageChunk, messages_from_dict

    if isinstance(message, (AIMessage, AIMessageChunk)):
        return message
    if not isinstance(message, dict):
        return message
    try:
        wrapped = envelope_langchain_message_dict(message)
        restored = messages_from_dict([wrapped])
        if restored and isinstance(restored[0], (AIMessage, AIMessageChunk)):
            return restored[0]
    except Exception:
        logger.debug("TUI could not coerce dict to AIMessage for blocks", exc_info=True)
    return message


def _expand_nonstandard_tool_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map LangChain ``non_standard`` tool wrappers to plain ``tool_call`` blocks.

    Anthropic-style ``tool_use`` content is often stored as
    ``{\"type\": \"non_standard\", \"value\": {\"type\": \"tool_use\", ...}}``.
    The TUI loop only understands ``tool_call`` / ``tool_call_chunk`` — without this,
    tool cards never mount for Claude/Anthropic providers.
    """
    out: list[dict[str, Any]] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") != "non_standard":
            out.append(b)
            continue
        val = b.get("value")
        if not isinstance(val, dict):
            out.append(b)
            continue
        inner_t = val.get("type")
        if inner_t == "tool_use":
            out.append(
                {
                    "type": "tool_call",
                    "name": val.get("name"),
                    "id": val.get("id"),
                    "args": val.get("input") if val.get("input") is not None else {},
                }
            )
            continue
        if inner_t in ("tool_call", "tool_call_chunk"):
            out.append(
                {
                    "type": inner_t,
                    "name": val.get("name"),
                    "id": val.get("id"),
                    "args": val.get("args"),
                    "index": val.get("index"),
                }
            )
            continue
        out.append(b)
    return out


def _assistant_message_terminal_for_empty_tool_arg_mount(message: Any) -> bool:
    """True when streamed tool-call kwargs will not be refined by a later chunk.

    Used with :func:`should_elide_stream_tool_card_mount` to avoid mounting cards
    that only show placeholder headers (IG-300).
    """
    from langchain_core.messages import AIMessage, AIMessageChunk

    if isinstance(message, AIMessage):
        return True
    if isinstance(message, AIMessageChunk):
        return getattr(message, "chunk_position", None) == "last"
    return False


def _tui_main_assistant_body_for_dedupe(raw: str) -> str:
    """Normalize assistant text the same way as :func:`_flush_assistant_text_ns` input."""
    from soothe_cli.shared.events.explore_task_display import (
        format_explore_task_json_blob_for_display,
    )

    return format_explore_task_json_blob_for_display(
        RendererBase.repair_concatenated_output(raw or "")
    ).strip()


def _tui_goal_completion_matches_prior_main_visible_answer(
    adapter: TextualUIAdapter,
    *,
    ns_key: tuple[Any, ...],
    output_text: str,
    pending_execute_text: str = "",
) -> bool:
    """Return True when ``goal_completion`` duplicates an already-shown main answer.

    Covers (1) ``execute_step`` prose on ``CognitionStepMessage``, (2) prose last flushed to a
    standalone ``AssistantMessage``, and (3) prose still in ``pending_text_by_namespace`` that
    was already streamed into an ``AssistantMessage`` via ``append_content`` but not yet
    flushed (``goal_completion`` can arrive before ``chunk_position == last`` or end-of-turn
    flush — common for direct daemon runs; ``/explore`` often interleaves flushes differently).
    """
    if ns_key != ():
        return False
    body = _tui_main_assistant_body_for_dedupe(output_text)
    if not body:
        return False
    step_prior = _tui_main_assistant_body_for_dedupe(
        adapter._last_completed_main_step_execute_prose
    )
    if step_prior and body == step_prior:
        return True
    flush_prior = _tui_main_assistant_body_for_dedupe(adapter._last_main_flushed_assistant_prose)
    if flush_prior and body == flush_prior:
        return True
    pending_prior = _tui_main_assistant_body_for_dedupe(pending_execute_text)
    return bool(pending_prior) and body == pending_prior


def _tui_effective_ai_blocks(
    message: Any,
    *,
    ns_key: tuple[Any, ...],
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build content blocks for TUI streaming (text + tool calls).

    Tool kwargs are merged in
    :func:`soothe_cli.shared.tool_call_resolution.materialize_ai_blocks_with_resolved_tools`.
    """
    from langchain_core.messages import AIMessage, AIMessageChunk

    from soothe_cli.shared.tools.tool_call_resolution import (
        materialize_ai_blocks_with_resolved_tools,
    )

    message = _coerce_ai_message_for_blocks(message)
    if not isinstance(message, (AIMessage, AIMessageChunk)):
        return []

    # Root namespace: allow string fallback. Subgraphs: suppress plain string (avoid dup with main).
    allow_plain_string = not ns_key
    raw_blocks = getattr(message, "content_blocks", None)
    blocks: list[dict[str, Any]] = []
    if raw_blocks:
        blocks = _expand_nonstandard_tool_blocks([b for b in raw_blocks if isinstance(b, dict)])
        return materialize_ai_blocks_with_resolved_tools(
            blocks, message, streaming_overlay=streaming_overlay
        )

    raw = getattr(message, "content", None)
    if not allow_plain_string:
        if isinstance(raw, list):
            toolish = [
                b
                for b in raw
                if isinstance(b, dict)
                and b.get("type") in ("tool_call", "tool_call_chunk", "tool_use", "non_standard")
            ]
            if toolish:
                expanded = _expand_nonstandard_tool_blocks(toolish)
                return materialize_ai_blocks_with_resolved_tools(
                    expanded, message, streaming_overlay=streaming_overlay
                )
        return materialize_ai_blocks_with_resolved_tools(
            [], message, streaming_overlay=streaming_overlay
        )
    if isinstance(raw, str) and raw.strip():
        merged = [{"type": "text", "text": raw}]
        return materialize_ai_blocks_with_resolved_tools(
            merged, message, streaming_overlay=streaming_overlay
        )
    if isinstance(raw, list):
        part = _expand_nonstandard_tool_blocks([b for b in raw if isinstance(b, dict)])
        if not part:
            return materialize_ai_blocks_with_resolved_tools(
                [], message, streaming_overlay=streaming_overlay
            )
        return materialize_ai_blocks_with_resolved_tools(
            part, message, streaming_overlay=streaming_overlay
        )
    return materialize_ai_blocks_with_resolved_tools(
        [], message, streaming_overlay=streaming_overlay
    )
