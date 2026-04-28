"""Normalize LangGraph ``astream`` chunks for AgentLoop Act and finalize paths.

``CompiledStateGraph.astream`` can emit:
- 3-tuples ``(namespace, mode, data)`` (subgraphs / deepagents),
- 2-tuples ``(mode, data)`` (e.g. ``stream_mode`` without namespace),
- dict updates with ``{"model": {"messages": [...]}}``,
- legacy list-shaped ``data`` ``[message, metadata]``.

This module provides a single place to extract :class:`~langchain_core.messages.BaseMessage`
instances and plain text from message ``content`` fields.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

_TUPLE_LEN = 3
_MSG_TUPLE_LEN = 2
_LIST_MIN_LEN = 2


def join_text_fragments(parts: list[str]) -> str:
    """Join text fragments while preserving common word/markdown boundaries.

    LangGraph/LLM chunking can emit adjacent fragments without explicit boundary
    characters. A plain `''.join(parts)` may collapse tokens such as `first10`
    or markdown headings like `Report##`.
    """
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]

    out = [parts[0]]
    for part in parts[1:]:
        if not part:
            continue
        prev = out[-1]
        if not prev:
            out[-1] = part
            continue

        prev_last = prev[-1]
        next_first = part[0]

        # Keep explicit whitespace/newline boundaries untouched.
        if prev_last.isspace() or next_first.isspace():
            out.append(part)
            continue
        # Preserve markdown/code boundary before heading/list/html markers.
        if next_first in "#<":
            out.append("\n" + part)
            continue
        # Preserve human-readable token boundary for alpha<->digit transitions.
        if (prev_last.isalpha() and next_first.isdigit()) or (
            prev_last.isdigit() and next_first.isalpha()
        ):
            out.append(" " + part)
            continue

        out.append(part)

    return "".join(out)


def extract_text_from_message_content(content: Any) -> str:
    """Flatten LangChain message ``content`` (str or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return join_text_fragments(parts)
    return ""


def parse_tuple_stream_chunk(chunk: Any) -> tuple[Any, str, Any] | None:
    """Parse stream tuple into ``(namespace, mode, data)`` if applicable.

    Supports both 3-tuples (namespaced) and 2-tuples ``(mode, data)`` with empty
    namespace.
    """
    if not isinstance(chunk, tuple):
        return None
    if len(chunk) == _TUPLE_LEN:
        return chunk[0], chunk[1], chunk[2]
    if len(chunk) >= _MSG_TUPLE_LEN:
        return (), chunk[0], chunk[1]
    return None


def _iter_messages_from_messages_data(data: Any) -> Iterator[BaseMessage]:
    """Yield ``BaseMessage`` instances from ``messages`` mode payload."""
    if isinstance(data, tuple) and len(data) >= _MSG_TUPLE_LEN:
        head = data[0]
        if isinstance(head, BaseMessage):
            yield head
    elif isinstance(data, list) and len(data) >= _LIST_MIN_LEN:
        head = data[0]
        if isinstance(head, BaseMessage):
            yield head


def iter_messages_for_act_aggregation(chunk: Any) -> Iterator[BaseMessage]:
    """Yield messages from one ``astream`` chunk for Act-phase aggregation.

    Mirrors legacy ``Executor._stream_and_collect`` rules:
    - Tuple path: only ``mode == \"messages\"`` with **empty** namespace (root graph).
    - Dict path: ``chunk[\"model\"][\"messages\"]`` when present.

    Args:
        chunk: Raw chunk from ``CoreAgent.astream`` / ``CompiledStateGraph.astream``.

    Yields:
        :class:`~langchain_core.messages.BaseMessage` instances to process for tool/AI text
        and token metrics.
    """
    parsed = parse_tuple_stream_chunk(chunk)
    if parsed is not None:
        namespace, mode, data = parsed
        if mode == "messages" and not namespace:
            yield from _iter_messages_from_messages_data(data)
        return

    if isinstance(chunk, dict) and "model" in chunk:
        model_data = chunk["model"]
        if isinstance(model_data, dict) and "messages" in model_data:
            for msg in model_data["messages"]:
                if isinstance(msg, BaseMessage):
                    yield msg


@dataclass
class GoalCompletionAccumState:
    """Mutable accumulators for adaptive goal-completion streaming."""

    accumulated_chunks: str = ""
    final_ai_message_text: str = ""
    ai_msg_count: int = 0


def update_goal_completion_from_message(state: GoalCompletionAccumState, msg: BaseMessage) -> None:
    """Update goal-completion accumulators from one streamed AI message.

    Prefers accumulated chunk text over a sparse final :class:`~langchain_core.messages.AIMessage`
    when both exist (same policy as the previous inline loop in ``AgentLoop``).

    Args:
        state: Mutable accumulator state.
        msg: A streamed message (typically :class:`~langchain_core.messages.AIMessage` or
            :class:`~langchain_core.messages.AIMessageChunk`).
    """
    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return

    state.ai_msg_count += 1
    extracted = extract_text_from_message_content(msg.content)

    if isinstance(msg, AIMessageChunk):
        if extracted:
            state.accumulated_chunks += extracted
        return

    if isinstance(msg, AIMessage) and extracted:
        state.final_ai_message_text = extracted


def resolve_goal_completion_text(state: GoalCompletionAccumState) -> str:
    """Choose longer of accumulated chunk text vs final non-chunk AI text."""
    if len(state.accumulated_chunks) >= len(state.final_ai_message_text):
        return state.accumulated_chunks
    return state.final_ai_message_text


__all__ = [
    "GoalCompletionAccumState",
    "extract_text_from_message_content",
    "iter_messages_for_act_aggregation",
    "join_text_fragments",
    "parse_tuple_stream_chunk",
    "resolve_goal_completion_text",
    "update_goal_completion_from_message",
]
