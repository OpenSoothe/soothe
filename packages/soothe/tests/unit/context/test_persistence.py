"""Tests for persistence backends (soothe.context.persistence)."""

from pathlib import Path

import pytest

from soothe.foundation.context.models import GoalNode, GoalStepDAG, StepNode


class TestSqliteMemoryPersistence:
    """Tests using SQLite :memory: backend (replaces InMemoryContextPersistence)."""

    @pytest.mark.asyncio
    async def test_save_and_load_dag(self) -> None:
        from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

        p = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        dag = GoalStepDAG()
        goal = GoalNode(description="Test")
        goal.steps.add_step(StepNode(id="S1", description="Step"))
        dag.add_goal(goal)

        await p.save_dag(dag)
        loaded = await p.load_dag()
        assert loaded is not None
        assert len(loaded.goals) == 1
        restored = list(loaded.goals.values())[0]
        assert restored.description == "Test"
        assert "S1" in restored.steps.nodes

    @pytest.mark.asyncio
    async def test_load_empty_returns_none(self) -> None:
        from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

        p = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        assert await p.load_dag() is None

    @pytest.mark.asyncio
    async def test_save_and_load_ledger(self) -> None:
        from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

        p = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        data = [{"type": "HumanMessage", "content": "hello", "phase": "plan"}]
        await p.save_ledger(data)
        loaded = await p.load_ledger()
        assert len(loaded) == 1
        assert loaded[0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_load_ledger_empty(self) -> None:
        from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

        p = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        assert await p.load_ledger() == []

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence

        p = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        dag = GoalStepDAG()
        dag.add_goal(GoalNode(description="X"))
        await p.save_dag(dag)
        await p.save_ledger([{"type": "HumanMessage", "content": "hi", "phase": None}])
        await p.clear()
        assert await p.load_dag() is None
        assert await p.load_ledger() == []
