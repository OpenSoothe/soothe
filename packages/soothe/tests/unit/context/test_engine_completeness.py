"""Tests for ContextEngine public API, callbacks, and lossless persistence (RFC-624 Phase 3a)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode, StepExecution, StepNode
from soothe.context.store_sqlite import SqliteContextPersistence


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
    async def test_dag_snapshot_model_dump_json_serializable(self) -> None:
        """Autopilot goal persistence uses model_dump(mode='json') for PostgreSQL JSONB."""
        import json

        ce = _ce()
        goal = await ce.create_goal("Test goal")
        await ce.add_step(goal.id, StepNode(id="s1", description="Step 1"))
        await ce.complete_step(goal.id, "s1", StepExecution(duration_ms=1))
        snapshot = ce.get_dag_snapshot()
        json.dumps(snapshot.model_dump(mode="json"))

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
        lineage = ce._dag.goal_lineage(child.id)
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
    async def test_pre_rfc624_ledger_format_loads_via_normalize(self) -> None:
        """Pre-RFC-624 ledger rows (type + content + phase) upgrade on read."""
        from soothe.context.store_sqlite import SqliteContextPersistence

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


class TestDeferredSaveCoalescing:
    @pytest.mark.asyncio
    async def test_defer_save_batches_until_flush(self) -> None:
        ce = _ce()
        goal = await ce.create_goal("Batch goal")
        await ce.add_step(goal.id, StepNode(id="s1", description="Step 1"))

        save_dag_calls = 0
        original_save_dag = ce._persistence.save_dag

        async def counting_save_dag(dag):  # type: ignore[no-untyped-def]
            nonlocal save_dag_calls
            save_dag_calls += 1
            return await original_save_dag(dag)

        ce._persistence.save_dag = counting_save_dag  # type: ignore[method-assign]

        ce.defer_save()
        ce.defer_save()
        assert save_dag_calls == 0

        await ce.save()
        assert save_dag_calls == 1
        assert ce._save_dirty is False
