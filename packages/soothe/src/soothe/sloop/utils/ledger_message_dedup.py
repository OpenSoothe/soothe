"""RFC-214 reference-based dedup for CoreAgent ledger projection."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def _normalize_message_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def message_reference_id(msg: BaseMessage) -> str | None:
    """Return the stable id used for RFC-214 dedup (``core_agent_message_id`` or ``id``)."""
    ref = _normalize_message_id(getattr(msg, "core_agent_message_id", None))
    if ref is not None:
        return ref
    return _normalize_message_id(getattr(msg, "id", None))


def collect_core_agent_message_ids(messages: list[BaseMessage]) -> frozenset[str]:
    """Collect message ids present in a CoreAgent checkpoint ``messages`` channel."""
    ids: set[str] = set()
    for msg in messages:
        ref = message_reference_id(msg)
        if ref is not None:
            ids.add(ref)
        raw_id = _normalize_message_id(getattr(msg, "id", None))
        if raw_id is not None:
            ids.add(raw_id)
    return frozenset(ids)


def filter_messages_not_in_checkpoint(
    messages: list[BaseMessage],
    checkpoint_message_ids: frozenset[str],
) -> list[BaseMessage]:
    """Drop ledger rows whose reference id is already in the CoreAgent thread."""
    if not checkpoint_message_ids or not messages:
        return list(messages)
    out: list[BaseMessage] = []
    for msg in messages:
        ref = message_reference_id(msg)
        if ref is not None and ref in checkpoint_message_ids:
            continue
        out.append(msg)
    return out


def extract_execute_turn_core_agent_message_ids(
    *,
    graph_messages: list[BaseMessage] | None,
    stream_ai_messages: list[BaseMessage] | None,
    envelope_human_id: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve human/AI ``core_agent_message_id`` values for ledger recording.

    Args:
        graph_messages: Full CoreAgent graph ``messages`` after the step stream.
        stream_ai_messages: AI messages collected from the act stream.
        envelope_human_id: Id assigned to the current-step envelope before streaming.

    Returns:
        ``(human_core_agent_message_id, ai_core_agent_message_id)``.
    """
    human_id = _normalize_message_id(envelope_human_id)
    ai_id: str | None = None

    if stream_ai_messages:
        ai_candidates = [
            m
            for m in stream_ai_messages
            if isinstance(m, AIMessage) and type(m).__name__ != "AIMessageChunk"
        ]
        if ai_candidates:
            ai_id = _normalize_message_id(getattr(ai_candidates[-1], "id", None))

    if graph_messages and human_id is None:
        for msg in reversed(graph_messages):
            if not isinstance(msg, (HumanMessage, LoopHumanMessage)):
                continue
            human_id = _normalize_message_id(getattr(msg, "id", None))
            if human_id is not None:
                break

    if graph_messages and ai_id is None:
        for msg in reversed(graph_messages):
            if not isinstance(msg, (AIMessage, LoopAIMessage)):
                continue
            if type(msg).__name__ == "AIMessageChunk":
                continue
            ai_id = _normalize_message_id(getattr(msg, "id", None))
            if ai_id is not None:
                break

    return human_id, ai_id
