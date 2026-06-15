"""Integration tests for ContextEngine lifecycle (soothe.context.engine)."""

from pathlib import Path

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import StepExecution, StepNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence


class TestContextEngineGoalLifecycle:
    @pytest.mark.asyncio
    async def test_create_and_get_goal(self) -> None:
        engine = ContextEngine()
        goal = await engine.create_goal("Build feature X", priority=80)
        fetched = await engine.get_goal(goal.id)
        assert fetched is goal
        assert fetched.description == "Build feature X"

    @pytest.mark.asyncio
    async def test_list_goals_by_status(self) -> None:
        engine = ContextEngine()
        g1 = await engine.create_goal("A")
        await engine.create_goal("B")
        await engine.complete_goal(g1.id)
        active = await engine.list_goals(status="completed")
        assert len(active) == 1
        assert active[0].id == g1.id

    @pytest.mark.asyncio
    async def test_fail_goal(self) -> None:
        engine = ContextEngine()
        goal = await engine.create_goal("Will fail")
        await engine.fail_goal(goal.id, "error msg")
        fetched = await engine.get_goal(goal.id)
        assert fetched.status == "failed"

    @pytest.mark.asyncio
    async def test_suspend_goal(self) -> None:
        engine = ContextEngine()
        goal = await engine.create_goal("Will suspend")
        await engine.suspend_goal(goal.id, "waiting")
        fetched = await engine.get_goal(goal.id)
        assert fetched.status == "suspended"


class TestContextEngineStepLifecycle:
    @pytest.mark.asyncio
    async def test_add_step_to_goal(self) -> None:
        engine = ContextEngine()
        goal = await engine.create_goal("Test")
        step = StepNode(id="S1", description="Step one")
        await engine.add_step(goal.id, step)
        fetched = await engine.get_goal(goal.id)
        assert "S1" in fetched.steps.nodes

    @pytest.mark.asyncio
    async def test_add_steps_batch(self) -> None:
        engine = ContextEngine()
        goal = await engine.create_goal("Test")
        steps = [
            StepNode(id="S1", description="First"),
            StepNode(id="S2", description="Second", dependencies=["S1"]),
        ]
        await engine.add_steps(goal.id, steps, plan_iteration=1)
        fetched = await engine.get_goal(goal.id)
        assert len(fetched.steps.nodes) == 2
        assert fetched.steps.nodes["S1"].plan_iteration == 1

    @pytest.mark.asyncio
    async def test_complete_step(self) -> None:
        engine = ContextEngine()
        goal = await engine.create_goal("Test")
        await engine.add_step(goal.id, StepNode(id="S1", description="Step"))
        exe = StepExecution(tokens_used=50, duration_ms=100)
        await engine.complete_step(goal.id, "S1", exe)
        fetched = await engine.get_goal(goal.id)
        assert fetched.steps.nodes["S1"].status == "completed"
        assert fetched.total_tokens_used == 50

    @pytest.mark.asyncio
    async def test_fail_step(self) -> None:
        engine = ContextEngine()
        goal = await engine.create_goal("Test")
        await engine.add_step(goal.id, StepNode(id="S1", description="Step"))
        exe = StepExecution(tokens_used=10, error="timeout")
        await engine.fail_step(goal.id, "S1", exe)
        fetched = await engine.get_goal(goal.id)
        assert fetched.steps.nodes["S1"].status == "failed"
        assert fetched.total_tokens_used == 10

    @pytest.mark.asyncio
    async def test_add_step_to_missing_goal_raises(self) -> None:
        engine = ContextEngine()
        with pytest.raises(KeyError, match="not found"):
            await engine.add_step("missing", StepNode(id="S1", description="X"))


class TestContextEngineProjection:
    @pytest.mark.asyncio
    async def test_project_returns_bundle(self) -> None:
        engine = ContextEngine()
        goal = await engine.create_goal("Test", priority=90)
        goal.status = "active"
        await engine.add_step(goal.id, StepNode(id="S1", description="Do it"))
        bundle = await engine.project()
        assert bundle.active_goal is not None
        assert bundle.active_goal.id == goal.id

    @pytest.mark.asyncio
    async def test_project_empty_engine(self) -> None:
        engine = ContextEngine()
        bundle = await engine.project()
        assert bundle.active_goal is None


class TestContextEngineLedger:
    @pytest.mark.asyncio
    async def test_record_and_get_messages(self) -> None:
        from langchain_core.messages import HumanMessage

        engine = ContextEngine()
        await engine.record_message(HumanMessage(content="hello"), phase="plan")
        msgs = await engine.get_ledger(phases=["plan"])
        assert len(msgs) == 1
        assert msgs[0].content == "hello"


class TestContextEnginePersistence:
    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self) -> None:
        persistence = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        engine = ContextEngine(persistence=persistence)
        goal = await engine.create_goal("Persist me")
        await engine.add_step(goal.id, StepNode(id="S1", description="Step"))
        await engine.save()

        engine2 = ContextEngine(persistence=persistence)
        loaded = await engine2.load()
        assert loaded is True
        fetched = await engine2.get_goal(goal.id)
        assert fetched is not None
        assert fetched.description == "Persist me"

    @pytest.mark.asyncio
    async def test_load_empty_returns_false(self) -> None:
        persistence = SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
        engine = ContextEngine(persistence=persistence)
        loaded = await engine.load()
        assert loaded is False
