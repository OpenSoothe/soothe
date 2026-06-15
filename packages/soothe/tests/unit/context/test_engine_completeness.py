"""Tests for ContextEngine public API, callbacks, and lossless persistence (RFC-624 Phase 3a)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode, StepExecution, StepNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence


def _ce(**kwargs) -> ContextEngine:
    """Create a ContextEngine with in-memory SQLite persistence."""
    p = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    return ContextEngine(persistence=p, **kwargs)


# ── Public Read API ──────────────────────────────────────────────────


class TestPublicReadAPI:
    @pytest.mark.asyncio
    async def test_get_dag_snapshot(self) -> None:
        ce = _ce()
        goal = await ce.create_goal("Test goal")
        await ce.add_step(goal.id, StepNode(id="s1", description="Step 1"))
        snapshot = ce.get_dag_snapshot()
        assert len(snapshot.goals) == 1
        assert snapshot.goals[0].description == "Test goal"

    @pytest.mark.asyncio
    async def test_get_step_dag(self) -> None:
        ce = _ce()
        goal = await ce.create_goal("Test goal")
        await ce.add_step(goal.id, StepNode(id="s1", description="Step 1"))
        step_dag = ce.get_step_dag(goal.id)
        assert step_dag is not None
        assert "s1" in step_dag.nodes

    @pytest.mark.asyncio
    async def test_get_step_dag_missing_goal(self) -> None:
        ce = _ce()
        assert ce.get_step_dag("missing") is None

    @pytest.mark.asyncio
    async def test_get_ledger_entries(self) -> None:
        ce = _ce()
        ce._ledger.record_message(HumanMessage(content="hello"), "execute_step")
        ce._ledger.record_message(AIMessage(content="world"), "plan_assess")
        entries = ce.get_ledger_entries()
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_get_ledger_entries_filtered(self) -> None:
        ce = _ce()
        ce._ledger.record_message(HumanMessage(content="hello"), "execute_step")
        ce._ledger.record_message(AIMessage(content="world"), "plan_assess")
        entries = ce.get_ledger_entries(phases=["execute_step"])
        assert len(entries) == 1
        assert entries[0][1] == "execute_step"

    @pytest.mark.asyncio
    async def test_get_all_goals(self) -> None:
        ce = _ce()
        await ce.create_goal("Goal 1")
        await ce.create_goal("Goal 2")
        goals = ce.get_all_goals()
        assert len(goals) == 2

    @pytest.mark.asyncio
    async def test_get_goal_lineage(self) -> None:
        ce = _ce()
        parent = await ce.create_goal("Parent")
        child = GoalNode(description="Child", parent_id=parent.id)
        ce._dag.add_goal(child)
        lineage = ce.get_goal_lineage(child.id)
        assert lineage == ["Parent", "Child"]


# ── Missing State Transitions ────────────────────────────────────────


class TestMissingTransitions:
    @pytest.mark.asyncio
    async def test_cancel_goal(self) -> None:
        ce = _ce()
        goal = await ce.create_goal("Test goal")
        await ce.cancel_goal(goal.id)
        assert goal.status == "cancelled"

    @pytest.mark.asyncio
    async def test_skip_step(self) -> None:
        ce = _ce()
        goal = await ce.create_goal("Test goal")
        await ce.add_step(goal.id, StepNode(id="s1", description="Step 1"))
        await ce.skip_step(goal.id, "s1")
        step_dag = ce.get_step_dag(goal.id)
        assert step_dag.nodes["s1"].status == "skipped"

    @pytest.mark.asyncio
    async def test_skip_step_missing_goal(self) -> None:
        ce = _ce()
        await ce.skip_step("missing", "s1")  # should not raise

    @pytest.mark.asyncio
    async def test_block_goal(self) -> None:
        ce = _ce()
        goal = await ce.create_goal("Test goal")
        await ce.block_goal(goal.id)
        assert goal.status == "blocked"

    @pytest.mark.asyncio
    async def test_unblock_goal(self) -> None:
        ce = _ce()
        goal = await ce.create_goal("Test goal")
        await ce.block_goal(goal.id)
        await ce.unblock_goal(goal.id)
        assert goal.status == "pending"


# ── Callback Event Mechanism ─────────────────────────────────────────


class TestCallbacks:
    @pytest.mark.asyncio
    async def test_goal_created_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str]] = []
        ce.on("goal_created", lambda gid: events.append(("created", gid)))
        goal = await ce.create_goal("Test goal")
        assert len(events) == 1
        assert events[0] == ("created", goal.id)

    @pytest.mark.asyncio
    async def test_goal_activated_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str]] = []
        ce.on("goal_activated", lambda gid: events.append(("activated", gid)))
        goal = await ce.create_goal("Test goal")
        await ce.activate_goal(goal.id, loop_id="loop-1")
        assert len(events) == 1
        assert events[0] == ("activated", goal.id)

    @pytest.mark.asyncio
    async def test_goal_completed_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str]] = []
        ce.on("goal_completed", lambda gid: events.append(("completed", gid)))
        goal = await ce.create_goal("Test goal")
        await ce.complete_goal(goal.id)
        assert len(events) == 1
        assert events[0] == ("completed", goal.id)

    @pytest.mark.asyncio
    async def test_goal_failed_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str, str]] = []
        ce.on("goal_failed", lambda gid, err: events.append(("failed", gid, err)))
        goal = await ce.create_goal("Test goal")
        await ce.fail_goal(goal.id, "something broke")
        assert len(events) == 1
        assert events[0] == ("failed", goal.id, "something broke")

    @pytest.mark.asyncio
    async def test_goal_suspended_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str, str]] = []
        ce.on("goal_suspended", lambda gid, reason: events.append(("suspended", gid, reason)))
        goal = await ce.create_goal("Test goal")
        await ce.suspend_goal(goal.id, "waiting")
        assert len(events) == 1
        assert events[0] == ("suspended", goal.id, "waiting")

    @pytest.mark.asyncio
    async def test_goal_cancelled_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str]] = []
        ce.on("goal_cancelled", lambda gid: events.append(("cancelled", gid)))
        goal = await ce.create_goal("Test goal")
        await ce.cancel_goal(goal.id)
        assert len(events) == 1
        assert events[0] == ("cancelled", goal.id)

    @pytest.mark.asyncio
    async def test_step_completed_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str, str]] = []
        ce.on("step_completed", lambda gid, sid: events.append(("step_completed", gid, sid)))
        goal = await ce.create_goal("Test goal")
        await ce.add_step(goal.id, StepNode(id="s1", description="Step 1"))
        await ce.complete_step(goal.id, "s1", StepExecution(duration_ms=100))
        assert len(events) == 1
        assert events[0] == ("step_completed", goal.id, "s1")

    @pytest.mark.asyncio
    async def test_step_failed_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str, str]] = []
        ce.on("step_failed", lambda gid, sid: events.append(("step_failed", gid, sid)))
        goal = await ce.create_goal("Test goal")
        await ce.add_step(goal.id, StepNode(id="s1", description="Step 1"))
        await ce.fail_step(goal.id, "s1", StepExecution(duration_ms=100, error="timeout"))
        assert len(events) == 1
        assert events[0] == ("step_failed", goal.id, "s1")

    @pytest.mark.asyncio
    async def test_step_skipped_callback(self) -> None:
        ce = _ce()
        events: list[tuple[str, str, str]] = []
        ce.on("step_skipped", lambda gid, sid: events.append(("step_skipped", gid, sid)))
        goal = await ce.create_goal("Test goal")
        await ce.add_step(goal.id, StepNode(id="s1", description="Step 1"))
        await ce.skip_step(goal.id, "s1")
        assert len(events) == 1
        assert events[0] == ("step_skipped", goal.id, "s1")

    @pytest.mark.asyncio
    async def test_callback_error_does_not_block_transition(self) -> None:
        ce = _ce()

        def bad_callback(gid: str) -> None:
            raise RuntimeError("callback error")

        ce.on("goal_created", bad_callback)
        goal = await ce.create_goal("Test goal")
        # State change still happened despite callback error
        assert goal.status == "pending"
        assert ce.get_all_goals()[0].description == "Test goal"

    @pytest.mark.asyncio
    async def test_off_unregisters_callback(self) -> None:
        ce = _ce()
        events: list[str] = []
        cb = lambda gid: events.append(gid)  # noqa: E731
        ce.on("goal_created", cb)
        await ce.create_goal("First")
        assert len(events) == 1
        ce.off("goal_created", cb)
        await ce.create_goal("Second")
        # Callback no longer fires
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_multiple_callbacks_same_event(self) -> None:
        ce = _ce()
        results1: list[str] = []
        results2: list[str] = []
        ce.on("goal_created", lambda gid: results1.append(gid))
        ce.on("goal_created", lambda gid: results2.append(gid))
        await ce.create_goal("Test")
        assert len(results1) == 1
        assert len(results2) == 1


# ── Lossless Persistence ─────────────────────────────────────────────


class TestLosslessPersistence:
    @pytest.mark.asyncio
    async def test_round_trip_human_message(self) -> None:
        ce = _ce()
        ce._ledger.record_message(HumanMessage(content="hello world"), "execute_step")
        await ce.save()
        ce2 = ContextEngine(persistence=ce._persistence)
        await ce2.load()
        entries = ce2.get_ledger_entries()
        assert len(entries) == 1
        assert isinstance(entries[0][0], HumanMessage)
        assert entries[0][0].content == "hello world"
        assert entries[0][1] == "execute_step"

    @pytest.mark.asyncio
    async def test_round_trip_ai_message(self) -> None:
        ce = _ce()
        ce._ledger.record_message(
            AIMessage(content="response", response_metadata={"tokens": 42}),
            "plan_assess",
        )
        await ce.save()
        ce2 = ContextEngine(persistence=ce._persistence)
        await ce2.load()
        entries = ce2.get_ledger_entries()
        assert len(entries) == 1
        assert isinstance(entries[0][0], AIMessage)
        assert entries[0][0].content == "response"

    @pytest.mark.asyncio
    async def test_round_trip_tool_message(self) -> None:
        ce = _ce()
        ce._ledger.record_message(
            ToolMessage(content="tool result", tool_call_id="tc1"),
            "execute_step",
        )
        await ce.save()
        ce2 = ContextEngine(persistence=ce._persistence)
        await ce2.load()
        entries = ce2.get_ledger_entries()
        assert len(entries) == 1
        assert isinstance(entries[0][0], ToolMessage)
        assert entries[0][0].content == "tool result"

    @pytest.mark.asyncio
    async def test_round_trip_system_message(self) -> None:
        ce = _ce()
        ce._ledger.record_message(
            SystemMessage(content="system instruction"),
            "compacted",
        )
        await ce.save()
        ce2 = ContextEngine(persistence=ce._persistence)
        await ce2.load()
        entries = ce2.get_ledger_entries()
        assert len(entries) == 1
        assert isinstance(entries[0][0], SystemMessage)
        assert entries[0][0].content == "system instruction"

    @pytest.mark.asyncio
    async def test_backward_compat_legacy_format(self) -> None:
        """Old format (type + content + phase, no _msg_type key) loads correctly."""
        from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

        persistence = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        # Simulate old-format ledger data
        await persistence.save_ledger(
            [
                {"type": "AIMessage", "content": "old ai msg", "phase": "plan_assess"},
                {"type": "HumanMessage", "content": "old human msg", "phase": "execute_step"},
            ]
        )

        ce = ContextEngine(persistence=persistence)
        await ce.load()
        entries = ce.get_ledger_entries()
        assert len(entries) == 2
        assert isinstance(entries[0][0], AIMessage)
        assert entries[0][0].content == "old ai msg"
        assert isinstance(entries[1][0], HumanMessage)
        assert entries[1][0].content == "old human msg"
