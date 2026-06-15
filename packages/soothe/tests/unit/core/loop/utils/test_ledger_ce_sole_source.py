"""Tests for RFC-624 Phase 4 Stage 2: CE-only ledger writes."""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.loop.state.schemas import LoopState
from soothe.foundation.loop.utils.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    _record_ledger_message,
)


def _make_state_with_ce() -> tuple[LoopState, ContextEngine]:
    """Create a LoopState bound to a real ContextEngine instance."""
    from soothe.foundation.context.models import GoalNode
    from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    state = LoopState(goal="test", thread_id="thread-1")
    goal = GoalNode(description="test goal")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    return state, ce


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend."""
    from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


class TestRecordLedgerMessageCEOnly:
    """_record_ledger_message writes to CE only (RFC-624 Phase 4 Stage 2)."""

    def test_writes_to_ce_ledger(self) -> None:
        ce = _make_ce()
        msg = LoopHumanMessage(content="Hello", phase="plan_assess")
        _record_ledger_message(ce, msg, "plan_assess")

        ledger_msgs = ce.ledger.get_messages()
        assert len(ledger_msgs) == 1
        assert ledger_msgs[0].content == "Hello"

    def test_raises_value_error_without_ce(self) -> None:
        """Stage 2: _record_ledger_message requires a CE instance."""
        msg = LoopHumanMessage(content="Hello", phase="plan_assess")
        try:
            _record_ledger_message(None, msg, "plan_assess")
        except ValueError as e:
            assert "requires a ContextEngine instance" in str(e)
        else:
            raise AssertionError("Expected ValueError")

    def test_ce_receives_human_and_ai_pair(self) -> None:
        ce = _make_ce()
        human = LoopHumanMessage(content="Plan this", phase="plan_assess")
        ai = LoopAIMessage(content="Here's the plan", phase="plan_assess")
        _record_ledger_message(ce, human, "plan_assess")
        _record_ledger_message(ce, ai, "plan_assess")

        ledger_msgs = ce.ledger.get_messages()
        assert len(ledger_msgs) == 2
        assert isinstance(ledger_msgs[0], HumanMessage)
        assert isinstance(ledger_msgs[1], AIMessage)

    def test_non_base_message_logs_warning(self) -> None:
        """When msg is not a BaseMessage, logs warning and drops."""
        ce = _make_ce()
        # Pass a plain dict (not a BaseMessage) — should log warning, not write to ledger
        _record_ledger_message(ce, {"content": "not a message"}, "plan_assess")
        # CE ledger should be unchanged
        assert len(ce.ledger.get_messages()) == 0


class TestLoopMessagesProperty:
    """loop_messages property queries CE when bound, returns cache when not."""

    def test_empty_when_ce_empty(self) -> None:
        state, ce = _make_state_with_ce()
        assert state.loop_messages == []

    def test_reflects_ce_ledger(self) -> None:
        state, ce = _make_state_with_ce()
        human = LoopHumanMessage(content="Plan", thread_id="thread-1", phase="plan_assess")
        ai = LoopAIMessage(content="Done", thread_id="thread-1", phase="plan_assess")
        ce.ledger.record_message(human, "plan_assess")
        ce.ledger.record_message(ai, "plan_assess")

        assert len(state.loop_messages) == 2
        assert isinstance(state.loop_messages[0], LoopHumanMessage)
        assert isinstance(state.loop_messages[1], LoopAIMessage)

    def test_returns_cache_without_ce(self) -> None:
        state = LoopState(goal="test", thread_id="thread-1")
        assert state.loop_messages == []

    def test_preserves_loop_message_types(self) -> None:
        """Loop-tagged messages (LoopHumanMessage, LoopAIMessage) pass through unchanged."""
        state, ce = _make_state_with_ce()
        human = LoopHumanMessage(
            content="Execute step",
            thread_id="t1",
            iteration=3,
            phase="execute_step",
        )
        ai = LoopAIMessage(
            content="Result",
            thread_id="t1",
            iteration=3,
            phase="execute_step",
        )
        ce.ledger.record_message(human, "execute_step")
        ce.ledger.record_message(ai, "execute_step")

        assert isinstance(state.loop_messages[0], LoopHumanMessage)
        assert state.loop_messages[0].thread_id == "t1"
        assert isinstance(state.loop_messages[1], LoopAIMessage)
        assert state.loop_messages[1].iteration == 3

    def test_converts_plain_base_messages(self) -> None:
        """Plain HumanMessage/AIMessage from CE are wrapped into Loop types."""
        state, ce = _make_state_with_ce()
        ce.ledger.record_message(HumanMessage(content="plain human"), "plan_assess")
        ce.ledger.record_message(AIMessage(content="plain ai"), "plan_assess")

        assert len(state.loop_messages) == 2
        assert isinstance(state.loop_messages[0], LoopHumanMessage)
        assert isinstance(state.loop_messages[1], LoopAIMessage)
        assert state.loop_messages[0].content == "plain human"

    def test_respects_max_bound(self) -> None:
        """loop_messages property respects MAX_LOOP_MESSAGES_PER_GOAL."""
        from soothe.foundation.loop.state.schemas import MAX_LOOP_MESSAGES_PER_GOAL

        state, ce = _make_state_with_ce()
        # Add more messages than the bound
        for i in range(MAX_LOOP_MESSAGES_PER_GOAL + 20):
            ce.ledger.record_message(
                LoopHumanMessage(content=f"msg-{i}", phase="execute_step"),
                "execute_step",
            )

        assert len(state.loop_messages) == MAX_LOOP_MESSAGES_PER_GOAL
        # Should keep the most recent messages
        assert state.loop_messages[0].content == f"msg-{20}"

    def test_always_fresh(self) -> None:
        """Each access to loop_messages queries CE — always fresh."""
        state, ce = _make_state_with_ce()
        assert len(state.loop_messages) == 0

        ce.ledger.record_message(
            LoopHumanMessage(content="new", phase="plan_assess"), "plan_assess"
        )
        # No sync needed — property always queries CE
        assert len(state.loop_messages) == 1
        assert state.loop_messages[0].content == "new"


class TestBindCE:
    """bind_ce wires LoopState to ContextEngine."""

    def test_bind_sets_ce_reference(self) -> None:
        state = LoopState(goal="test", thread_id="thread-1")
        assert state._ce is None
        assert state._ce_goal_id is None

        from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

        ce = ContextEngine(
            persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        )
        state.bind_ce(ce, "goal-123")

        assert state._ce is ce
        assert state._ce_goal_id == "goal-123"

    def test_bind_ce_clears_caches(self) -> None:
        """bind_ce clears local caches so CE becomes authoritative."""
        state = LoopState(goal="test", thread_id="thread-1")
        state._loop_messages_cache.append(LoopHumanMessage(content="stale", phase="execute_step"))
        state._step_results_cache.append(
            __import__("soothe.foundation.loop.state.schemas", fromlist=["StepResult"]).StepResult(
                step_id="s1", success=True, duration_ms=100, thread_id="t1"
            )
        )
        state._completed_step_ids_cache.add("s1")

        from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

        ce = ContextEngine(
            persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        )
        state.bind_ce(ce, "goal-123")

        assert len(state._loop_messages_cache) == 0
        assert len(state._step_results_cache) == 0
        assert len(state._completed_step_ids_cache) == 0

    def test_bind_ce_excluded_from_serialization(self) -> None:
        """Private CE attributes should not appear in model_dump()."""
        state, ce = _make_state_with_ce()
        dumped = state.model_dump()
        assert "_ce" not in dumped
        assert "_ce_goal_id" not in dumped


class TestStepResultsProperty:
    """step_results property queries CE StepDAG when bound."""

    def test_returns_cache_without_ce(self) -> None:
        state = LoopState(goal="test", thread_id="thread-1")
        assert state.step_results == []

    def test_returns_empty_when_no_executions(self) -> None:
        state, ce = _make_state_with_ce()
        assert state.step_results == []


class TestCompletedStepIdsProperty:
    """completed_step_ids property queries CE StepDAG when bound."""

    def test_returns_cache_without_ce(self) -> None:
        state = LoopState(goal="test", thread_id="thread-1")
        assert state.completed_step_ids == set()

    def test_returns_empty_when_no_completed_steps(self) -> None:
        state, ce = _make_state_with_ce()
        assert state.completed_step_ids == set()


class TestWriteThenReadRoundtrip:
    """End-to-end: write via _record_ledger_message → read loop_messages property."""

    def test_write_to_ce_read_from_property(self) -> None:
        state, ce = _make_state_with_ce()

        # Write via CE path (no loop_messages argument)
        human = LoopHumanMessage(content="Plan step", thread_id="thread-1", phase="plan_assess")
        ai = LoopAIMessage(content="Here's the plan", thread_id="thread-1", phase="plan_assess")
        _record_ledger_message(ce, human, "plan_assess")
        _record_ledger_message(ce, ai, "plan_assess")

        # Property reads directly from CE — no sync needed
        assert len(state.loop_messages) == 2
        assert state.loop_messages[0].content == "Plan step"
        assert state.loop_messages[1].content == "Here's the plan"
