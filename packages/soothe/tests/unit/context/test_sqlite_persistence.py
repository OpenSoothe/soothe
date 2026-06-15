"""Tests for SqliteContextPersistence (RFC-624 Phase 4 Step 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.foundation.context.models import GoalNode, GoalStepDAG, StepExecution, StepNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "ce_state.db"


@pytest.fixture
def persistence(tmp_db: Path) -> SqliteContextPersistence:
    return SqliteContextPersistence(loop_id="test-loop-1", db_path=tmp_db)


def _make_dag() -> GoalStepDAG:
    dag = GoalStepDAG()
    goal = GoalNode(description="Test goal")
    step = StepNode(id="S1", description="Step 1")
    goal.steps.add_step(step)
    goal.steps.mark_completed("S1", StepExecution(duration_ms=100))
    dag.add_goal(goal)
    return dag


class TestSqliteContextPersistence:
    async def test_save_and_load_dag(self, persistence: SqliteContextPersistence) -> None:
        dag = _make_dag()
        await persistence.save_dag(dag)

        loaded = await persistence.load_dag()
        assert loaded is not None
        assert len(loaded.goals) == 1
        goal = list(loaded.goals.values())[0]
        assert goal.description == "Test goal"
        assert goal.steps.total_steps == 1
        assert goal.steps.completed_steps == 1

    async def test_load_dag_empty(self, persistence: SqliteContextPersistence) -> None:
        loaded = await persistence.load_dag()
        assert loaded is None

    async def test_save_and_load_ledger(self, persistence: SqliteContextPersistence) -> None:
        messages = [
            {"type": "HumanMessage", "content": "Hello", "phase": "plan_assess"},
            {"type": "AIMessage", "content": "World", "phase": "plan_generate"},
        ]
        await persistence.save_ledger(messages)

        loaded = await persistence.load_ledger()
        assert len(loaded) == 2
        assert loaded[0]["content"] == "Hello"
        assert loaded[1]["content"] == "World"

    async def test_load_ledger_empty(self, persistence: SqliteContextPersistence) -> None:
        loaded = await persistence.load_ledger()
        assert loaded == []

    async def test_clear(self, persistence: SqliteContextPersistence) -> None:
        dag = _make_dag()
        await persistence.save_dag(dag)
        await persistence.save_ledger([{"type": "HumanMessage", "content": "test"}])

        await persistence.clear()

        assert await persistence.load_dag() is None
        assert await persistence.load_ledger() == []

    async def test_overwrite_dag(self, persistence: SqliteContextPersistence) -> None:
        dag1 = GoalStepDAG()
        dag1.add_goal(GoalNode(description="Goal 1"))
        await persistence.save_dag(dag1)

        dag2 = GoalStepDAG()
        dag2.add_goal(GoalNode(description="Goal 2"))
        dag2.add_goal(GoalNode(description="Goal 3"))
        await persistence.save_dag(dag2)

        loaded = await persistence.load_dag()
        assert loaded is not None
        assert len(loaded.goals) == 2

    async def test_separate_loop_ids(self, tmp_db: Path) -> None:
        p1 = SqliteContextPersistence(loop_id="loop-1", db_path=tmp_db)
        p2 = SqliteContextPersistence(loop_id="loop-2", db_path=tmp_db)

        dag = _make_dag()
        await p1.save_dag(dag)

        assert await p2.load_dag() is None
        assert await p1.load_dag() is not None

    async def test_corrupt_dag_returns_none(self, persistence: SqliteContextPersistence) -> None:
        # Write invalid JSON directly
        conn = persistence._ensure_connection()
        conn.execute(
            "INSERT INTO ce_dag (loop_id, dag_json, updated_at) VALUES (?, ?, ?)",
            ("test-loop-1", "not json{", "2026-01-01"),
        )
        conn.commit()

        loaded = await persistence.load_dag()
        assert loaded is None

    async def test_corrupt_ledger_returns_empty(
        self, persistence: SqliteContextPersistence
    ) -> None:
        conn = persistence._ensure_connection()
        conn.execute(
            "INSERT INTO ce_ledger (loop_id, ledger_json, updated_at) VALUES (?, ?, ?)",
            ("test-loop-1", "not json{", "2026-01-01"),
        )
        conn.commit()

        loaded = await persistence.load_ledger()
        assert loaded == []

    async def test_cross_goal_accumulation(self, persistence: SqliteContextPersistence) -> None:
        """Verify that successive goals accumulate in the DAG (RFC-624 Phase 4 Step 1)."""
        # Goal 1
        dag1 = GoalStepDAG()
        goal1 = GoalNode(description="First goal")
        goal1.steps.add_step(StepNode(id="S1", description="Step 1"))
        dag1.add_goal(goal1)
        await persistence.save_dag(dag1)

        # Simulate ce.load() for goal 2 — restore and add
        loaded = await persistence.load_dag()
        assert loaded is not None
        assert len(loaded.goals) == 1

        # Mark goal 1 as completed
        list(loaded.goals.values())[0].status = "completed"

        # Add goal 2
        goal2 = GoalNode(description="Second goal")
        loaded.add_goal(goal2)
        await persistence.save_dag(loaded)

        # Verify both goals are present
        final = await persistence.load_dag()
        assert final is not None
        assert len(final.goals) == 2
        goals = list(final.goals.values())
        assert any(g.description == "First goal" and g.status == "completed" for g in goals)
        assert any(g.description == "Second goal" for g in goals)
