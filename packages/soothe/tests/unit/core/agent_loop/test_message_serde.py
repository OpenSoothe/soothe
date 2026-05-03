"""Tests for RFC-214: Loop message serde round-trip (Gap G6 fix)."""

from langchain_core.messages import AIMessage, HumanMessage
from soothe_sdk.utils.serde import create_soothe_serde

from soothe.core.agent_loop.state.checkpoint import GoalExecutionRecord
from soothe.core.agent_loop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_loop_human_message_serde_roundtrip():
    """Test LoopHumanMessage round-trip preserves type (not dict)."""
    serde = create_soothe_serde()

    msg = LoopHumanMessage(
        content="Execute step A",
        thread_id="test_thread",
        iteration=10,
        goal_summary="Test goal",
        phase="execute_step",
        step_id="step_a_uuid",
    )

    # Serialize
    serialized = serde.dumps_typed(msg)

    # Deserialize
    deserialized = serde.loads_typed(serialized)

    # Verify type preserved (NOT dict)
    assert isinstance(deserialized, LoopHumanMessage)
    assert not isinstance(deserialized, dict)

    # Verify fields preserved
    assert deserialized.content == msg.content
    assert deserialized.thread_id == msg.thread_id
    assert deserialized.iteration == msg.iteration
    assert deserialized.phase == msg.phase
    assert deserialized.step_id == msg.step_id


def test_loop_ai_message_serde_roundtrip():
    """Test LoopAIMessage round-trip preserves type (not dict)."""
    serde = create_soothe_serde()

    msg = LoopAIMessage(
        content="Step A completed successfully",
        thread_id="test_thread",
        iteration=10,
        phase="execute_step",
        step_id="step_a_uuid",
        response_metadata={"token_usage": {"total": 100}},
    )

    # Serialize
    serialized = serde.dumps_typed(msg)

    # Deserialize
    deserialized = serde.loads_typed(serialized)

    # Verify type preserved (NOT dict)
    assert isinstance(deserialized, LoopAIMessage)
    assert not isinstance(deserialized, dict)

    # Verify fields preserved
    assert deserialized.content == msg.content
    assert deserialized.thread_id == msg.thread_id
    assert deserialized.iteration == msg.iteration
    assert deserialized.phase == msg.phase
    assert deserialized.step_id == msg.step_id


def test_goal_execution_record_with_ledger_serde_roundtrip():
    """Test GoalExecutionRecord with loop_messages preserves message types."""
    from datetime import datetime

    serde = create_soothe_serde()

    # Create ledger with adjacent Human-AI pairs
    ledger = [
        LoopHumanMessage(
            content="Plan next steps",
            thread_id="test_thread",
            iteration=10,
            phase="plan",
        ),
        LoopAIMessage(
            content="Next actions: 1. Query database",
            thread_id="test_thread",
            iteration=10,
            phase="plan",
        ),
        LoopHumanMessage(
            content="Execute: Query database",
            thread_id="test_thread",
            iteration=10,
            phase="execute_step",
            step_id="step_a",
        ),
        LoopAIMessage(
            content="Found 150 records",
            thread_id="test_thread",
            iteration=10,
            phase="execute_step",
            step_id="step_a",
        ),
    ]

    record = GoalExecutionRecord(
        goal_id="test_goal_1",
        goal_text="Test goal",
        thread_id="test_thread",
        iteration=10,
        status="running",
        loop_messages=ledger,
        started_at=datetime.now(),
    )

    # Serialize
    serialized = serde.dumps_typed(record)

    # Deserialize
    deserialized = serde.loads_typed(serialized)

    # Verify record structure
    assert isinstance(deserialized, GoalExecutionRecord)
    assert deserialized.goal_id == record.goal_id

    # Verify ledger preserved
    assert len(deserialized.loop_messages) == len(ledger)

    # Verify ALL message types preserved (no dict fallback)
    for msg in deserialized.loop_messages:
        assert isinstance(msg, (LoopHumanMessage, LoopAIMessage))
        assert not isinstance(msg, dict)

    # Verify adjacent Human-AI pairs preserved
    assert isinstance(deserialized.loop_messages[0], LoopHumanMessage)
    assert isinstance(deserialized.loop_messages[1], LoopAIMessage)
    assert isinstance(deserialized.loop_messages[2], LoopHumanMessage)
    assert isinstance(deserialized.loop_messages[3], LoopAIMessage)

    # Verify Human-AI pairing by phase/step_id
    assert deserialized.loop_messages[0].phase == "plan"
    assert deserialized.loop_messages[1].phase == "plan"
    assert deserialized.loop_messages[2].phase == "execute_step"
    assert deserialized.loop_messages[3].phase == "execute_step"
    assert deserialized.loop_messages[2].step_id == "step_a"
    assert deserialized.loop_messages[3].step_id == "step_a"


def test_mixed_message_types_in_ledger():
    """Test ledger with mixed Loop and standard LangChain messages."""
    serde = create_soothe_serde()

    ledger = [
        LoopHumanMessage(content="Loop human", phase="execute_step"),
        HumanMessage(content="Standard human"),  # Should serialize normally
        LoopAIMessage(content="Loop AI", phase="execute_step"),
        AIMessage(content="Standard AI"),  # Should serialize normally
    ]

    # Serialize/deserialize
    serialized = serde.dumps_typed(ledger)
    deserialized = serde.loads_typed(serialized)

    # Verify Loop types preserved
    assert isinstance(deserialized[0], LoopHumanMessage)
    assert isinstance(deserialized[2], LoopAIMessage)

    # Verify standard types preserved
    assert isinstance(deserialized[1], HumanMessage)
    assert isinstance(deserialized[3], AIMessage)


def test_empty_ledger_serde():
    """Test GoalExecutionRecord with empty ledger."""
    from datetime import datetime

    serde = create_soothe_serde()

    record = GoalExecutionRecord(
        goal_id="test_goal_empty",
        goal_text="Empty ledger test",
        thread_id="test_thread",
        iteration=0,
        status="running",
        loop_messages=[],  # Empty ledger
        started_at=datetime.now(),
    )

    # Serialize/deserialize
    serialized = serde.dumps_typed(record)
    deserialized = serde.loads_typed(serialized)

    # Verify empty ledger preserved
    assert isinstance(deserialized.loop_messages, list)
    assert len(deserialized.loop_messages) == 0
