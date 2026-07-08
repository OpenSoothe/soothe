"""RFC-214 core_agent_message_id dedup helpers."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from soothe.foundation.sloop.utils.ledger_message_dedup import (
    collect_core_agent_message_ids,
    extract_execute_turn_core_agent_message_ids,
    filter_messages_not_in_checkpoint,
    message_reference_id,
)
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_message_reference_id_prefers_core_agent_message_id() -> None:
    msg = LoopHumanMessage(
        content="h",
        id="ledger-id",
        core_agent_message_id="core-id",
    )
    assert message_reference_id(msg) == "core-id"


def test_collect_core_agent_message_ids_includes_id_and_core_ref() -> None:
    msgs = [
        HumanMessage(content="h", id="human-1"),
        AIMessage(content="a", id="ai-1"),
        LoopAIMessage(content="b", id="ledger-ai", core_agent_message_id="core-ai"),
    ]
    ids = collect_core_agent_message_ids(msgs)
    assert ids == frozenset({"human-1", "ai-1", "ledger-ai", "core-ai"})


def test_filter_messages_not_in_checkpoint_skips_matching_refs() -> None:
    ledger = [
        LoopHumanMessage(
            content="h1",
            phase="execute_step",
            step_id="01",
            core_agent_message_id="human-01",
        ),
        LoopAIMessage(
            content="a1",
            phase="execute_step",
            step_id="01",
            core_agent_message_id="ai-01",
        ),
        LoopHumanMessage(content="h2", phase="execute_step", step_id="02"),
    ]
    filtered = filter_messages_not_in_checkpoint(
        ledger,
        frozenset({"human-01", "ai-01"}),
    )
    assert len(filtered) == 1
    assert getattr(filtered[0], "step_id", None) == "02"


def test_filter_messages_not_in_checkpoint_keeps_rows_without_refs() -> None:
    ledger = [LoopHumanMessage(content="h", phase="execute_step")]
    assert filter_messages_not_in_checkpoint(ledger, frozenset({"x"})) == ledger


def test_extract_execute_turn_core_agent_message_ids_from_stream_and_envelope() -> None:
    human_id, ai_id = extract_execute_turn_core_agent_message_ids(
        graph_messages=None,
        stream_ai_messages=[AIMessage(content="done", id="ai-final")],
        envelope_human_id="env-human",
    )
    assert human_id == "env-human"
    assert ai_id == "ai-final"


def test_extract_execute_turn_core_agent_message_ids_from_graph_fallback() -> None:
    human_id, ai_id = extract_execute_turn_core_agent_message_ids(
        graph_messages=[
            HumanMessage(content="task", id="graph-human"),
            AIMessage(content="answer", id="graph-ai"),
        ],
        stream_ai_messages=[],
        envelope_human_id=None,
    )
    assert human_id == "graph-human"
    assert ai_id == "graph-ai"
