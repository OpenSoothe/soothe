"""Normalize LangGraph ``astream`` chunks for StrangeLoop Act and finalize paths.

``CompiledStateGraph.astream`` can emit 3-tuples ``(namespace, mode, data)``,
2-tuples ``(mode, data)``, dict updates with ``{"model": {"messages": [...]}}``,
or list-shaped ``data`` ``[message, metadata]``.

This module provides a single place to extract :class:`~langchain_core.messages.BaseMessage`
instances and plain text from message ``content`` fields.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

_TUPLE_LEN = 3
_MSG_TUPLE_LEN = 2
_LIST_MIN_LEN = 2


def join_text_fragments(parts: list[str]) -> str:
    """Join text fragments with newline separators between content blocks."""
    return "\n".join(parts) if parts else ""


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


def _walk_stream_messages_payload_for_base_messages(obj: Any) -> Iterator[BaseMessage]:
    """DFS over LangGraph ``messages`` payloads that may nest lists/tuples/dicts."""
    if isinstance(obj, BaseMessage):
        yield obj
        return
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_stream_messages_payload_for_base_messages(v)
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_stream_messages_payload_for_base_messages(item)


def iter_namespaced_tool_messages(chunk: Any) -> Iterator[tuple[tuple[str, ...], ToolMessage]]:
    """Yield ``(namespace, ToolMessage)`` from subgraph ``messages`` stream chunks.

    Root graph chunks (empty namespace) are ignored; use
    :func:`iter_messages_for_act_aggregation` for those. Used for audit logging and
    tool totals that include subagent / compiled-subgraph tool results.

    Args:
        chunk: Raw ``astream`` chunk from ``CoreAgent.astream`` / ``CompiledStateGraph.astream``.

    Yields:
        Pairs of normalized namespace tuple and :class:`~langchain_core.messages.ToolMessage`.
    """
    parsed = parse_tuple_stream_chunk(chunk)
    if parsed is None:
        return
    namespace, mode, data = parsed
    if mode != "messages" or not namespace:
        return
    ns_tuple = tuple(str(x) for x in namespace)
    for msg in _walk_stream_messages_payload_for_base_messages(data):
        if isinstance(msg, ToolMessage):
            yield (ns_tuple, msg)


def iter_messages_for_delegate_task_scan(chunk: Any) -> Iterator[ToolMessage]:
    """Yield ``task`` tool messages from **namespaced** ``messages`` stream chunks only.

    Root-graph chunks are handled by :func:`iter_messages_for_act_aggregation`. Compiled
    subgraphs (e.g. Deep Research) may emit the parent delegation's ``ToolMessage`` only under a
    non-empty LangGraph namespace; those must still contribute delegate-final text (IG-355).

    Args:
        chunk: Raw ``astream`` chunk.

    Yields:
        :class:`~langchain_core.messages.ToolMessage` instances whose ``name`` is ``task``.
    """
    parsed = parse_tuple_stream_chunk(chunk)
    if parsed is None:
        return
    namespace, mode, data = parsed
    if mode != "messages" or not namespace:
        return
    for msg in _walk_stream_messages_payload_for_base_messages(data):
        if isinstance(msg, ToolMessage) and getattr(msg, "name", "") == "task":
            yield msg


def iter_messages_for_act_aggregation(chunk: Any) -> Iterator[BaseMessage]:
    """Yield messages from one ``astream`` chunk for Act-phase aggregation.

    Matches ``Executor._stream_and_collect`` stream selection:
    - Tuple path: only ``mode == \"messages\"`` with **empty** namespace (root graph).
    - Dict path: ``chunk[\"model\"][\"messages\"]`` when present.

    Subgraph AIMessages are excluded on purpose: orchestration context stays compact.
    Delegate **final** user-visible text for completion is taken from ``task`` ``ToolMessage``
    payloads collected separately (IG-355), not by merging namespaced assistant streams here.

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
    when both exist (same policy as the previous inline loop in ``StrangeLoop``).

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
    """Choose longer of accumulated chunk text vs final non-chunk AI text.

    Normalizes successive empty lines into a single empty line.
    Successive empty lines = 2+ blank lines in a row.
    A blank line is a line with no characters between newlines.
    """
    if len(state.accumulated_chunks) >= len(state.final_ai_message_text):
        text = state.accumulated_chunks
    else:
        text = state.final_ai_message_text

    if not text:
        return ""

    # Split into lines, process, then rejoin
    lines = text.split("\n")
    result: list[str] = []
    empty_count = 0
    have_content = False

    for line in lines:
        if line == "":
            empty_count += 1
        else:
            # Output collapsed blank lines before content
            if empty_count > 0:
                if not have_content:
                    # Leading: 2 empty strings = 1 blank line in join representation
                    result.append("")
                    result.append("")
                else:
                    # Middle: 1 empty string = 1 blank line in join representation
                    result.append("")
            empty_count = 0
            have_content = True
            result.append(line)

    # Trailing: 2 empty strings = 1 blank line in join representation
    if empty_count > 0:
        result.append("")
        result.append("")

    return "\n".join(result)


__all__ = [
    "GoalCompletionAccumState",
    "extract_text_from_message_content",
    "iter_messages_for_act_aggregation",
    "iter_namespaced_tool_messages",
    "join_text_fragments",
    "parse_tuple_stream_chunk",
    "resolve_goal_completion_text",
    "update_goal_completion_from_message",
]
