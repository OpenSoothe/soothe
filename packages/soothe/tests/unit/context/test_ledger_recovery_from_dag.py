"""Integration tests for ledger recovery from DAG (soothe.context)."""

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from soothe.context.engine import ContextEngine
from soothe.context.models import StepExecution, StepNode
from soothe.context.store_sqlite import SqliteContextPersistence


class TestLedgerRecoveryFromDAG:
    @pytest.mark.asyncio
    async def test_step_results_in_ledger_after_persistence(self) -> None:
        persistence = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        engine = ContextEngine(persistence=persistence)
        goal = await engine.create_goal("Test")
        await engine.add_step(goal.id, StepNode(id="S1", description="Do it"))
        await engine.complete_step(goal.id, "S1", StepExecution(tokens_used=10))
        await engine.record_message(HumanMessage(content="hello"), phase="plan")
        await engine.save()

        engine2 = ContextEngine(persistence=persistence)
        await engine2.load()
        msgs = await engine2.get_ledger()
        assert len(msgs) == 1
        assert msgs[0].content == "hello"

    @pytest.mark.asyncio
    async def test_dag_restores_step_status(self) -> None:
        persistence = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        engine = ContextEngine(persistence=persistence)
        goal = await engine.create_goal("Test")
        await engine.add_step(goal.id, StepNode(id="S1", description="Step 1"))
        await engine.add_step(goal.id, StepNode(id="S2", description="Step 2"))
        await engine.complete_step(goal.id, "S1", StepExecution())
        await engine.save()

        engine2 = ContextEngine(persistence=persistence)
        await engine2.load()
        fetched = await engine2.get_goal(goal.id)
        assert fetched.steps.nodes["S1"].status == "completed"
        assert fetched.steps.nodes["S2"].status == "pending"
