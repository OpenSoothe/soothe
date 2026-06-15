"""Tests for RFC-214: Loop message serde round-trip (Gap G6 fix)."""

from langchain_core.messages import AIMessage, HumanMessage
from soothe_sdk.utils.serde import create_soothe_serde

from soothe.foundation.loop.state.checkpoint import GoalExecutionRecord
from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage


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


def test_goal_execution_record_serde_roundtrip():
    """GoalExecutionRecord serde preserves metadata fields."""
    from datetime import datetime

    serde = create_soothe_serde()

    record = GoalExecutionRecord(
        goal_id="test_goal_1",
        goal_text="Test goal",
        thread_id="test_thread",
        iteration=10,
        status="completed",
        plan_revision_count=2,
        goal_completion="Finished",
        duration_ms=1200,
        tokens_used=99,
        started_at=datetime.now(),
    )

    # Serialize
    serialized = serde.dumps_typed(record)

    # Deserialize
    deserialized = serde.loads_typed(serialized)

    # Verify record structure
    assert isinstance(deserialized, GoalExecutionRecord)
    assert deserialized.goal_id == record.goal_id
    assert deserialized.plan_revision_count == 2
    assert deserialized.goal_completion == "Finished"
    assert deserialized.duration_ms == 1200
    assert deserialized.tokens_used == 99


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


def test_minimal_goal_execution_record_serde():
    """GoalExecutionRecord serde works with minimal required fields."""
    from datetime import datetime

    serde = create_soothe_serde()

    record = GoalExecutionRecord(
        goal_id="test_goal_empty",
        goal_text="Empty ledger test",
        thread_id="test_thread",
        iteration=0,
        status="running",
        started_at=datetime.now(),
    )

    # Serialize/deserialize
    serialized = serde.dumps_typed(record)
    deserialized = serde.loads_typed(serialized)

    assert deserialized.goal_id == "test_goal_empty"
    assert deserialized.status == "running"
