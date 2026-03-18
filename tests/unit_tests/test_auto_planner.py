"""Tests for AutoPlanner routing and goal_context forwarding."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.backends.planning.router import AutoPlanner
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    PlanStep,
    Reflection,
    StepResult,
)


def _make_planner(name: str) -> MagicMock:
    """Create a mock planner backend."""
    planner = MagicMock()
    planner.name = name
    planner.create_plan = AsyncMock(
        return_value=Plan(
            goal="test",
            steps=[PlanStep(id="step_1", description=f"{name} plan")],
        )
    )
    planner.revise_plan = AsyncMock(
        return_value=Plan(
            goal="test",
            steps=[PlanStep(id="step_1", description=f"{name} revised")],
            status="revised",
        )
    )
    planner.reflect = AsyncMock(
        return_value=Reflection(
            assessment="ok",
            should_revise=False,
            feedback="",
        )
    )
    return planner


class TestAutoPlanner:
    """Unit tests for AutoPlanner routing."""

    @pytest.mark.asyncio
    async def test_simple_goal_routes_to_direct(self) -> None:
        direct = _make_planner("direct")
        subagent = _make_planner("subagent")
        auto = AutoPlanner(direct=direct, subagent=subagent, routing_mode="heuristic")

        await auto.create_plan("hello world", PlanContext())
        direct.create_plan.assert_awaited_once()
        subagent.create_plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_medium_goal_routes_to_subagent(self) -> None:
        direct = _make_planner("direct")
        subagent = _make_planner("subagent")
        auto = AutoPlanner(direct=direct, subagent=subagent, routing_mode="heuristic")

        await auto.create_plan("implement user authentication", PlanContext())
        subagent.create_plan.assert_awaited_once()
        direct.create_plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complex_goal_routes_to_claude(self) -> None:
        direct = _make_planner("direct")
        subagent = _make_planner("subagent")
        claude = _make_planner("claude")
        auto = AutoPlanner(claude=claude, subagent=subagent, direct=direct, routing_mode="heuristic")

        await auto.create_plan("architect a new microservices system", PlanContext())
        claude.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complex_fallback_to_subagent_when_no_claude(self) -> None:
        direct = _make_planner("direct")
        subagent = _make_planner("subagent")
        auto = AutoPlanner(claude=None, subagent=subagent, direct=direct, routing_mode="heuristic")

        await auto.create_plan("architect a new microservices system", PlanContext())
        subagent.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_explicit_claude_keyword(self) -> None:
        direct = _make_planner("direct")
        claude = _make_planner("claude")
        auto = AutoPlanner(claude=claude, direct=direct, routing_mode="heuristic")

        await auto.create_plan("use claude to plan this task", PlanContext())
        claude.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_word_count_complex_threshold(self) -> None:
        direct = _make_planner("direct")
        subagent = _make_planner("subagent")
        auto = AutoPlanner(direct=direct, subagent=subagent, routing_mode="heuristic")

        # 170 tokens -> complex (>= 160 threshold)
        long_goal = " ".join(["word"] * 170)
        await auto.create_plan(long_goal, PlanContext())
        subagent.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reflect_forwards_goal_context(self) -> None:
        """AutoPlanner.reflect must forward goal_context to the delegate."""
        claude = _make_planner("claude")
        auto = AutoPlanner(claude=claude)

        plan = Plan(goal="test", steps=[PlanStep(id="s1", description="step")])
        results = [StepResult(step_id="s1", output="ok", success=True)]
        goal_ctx = GoalContext(
            current_goal_id="g1",
            all_goals=[],
            completed_goals=[],
            failed_goals=[],
            ready_goals=["g1"],
        )

        await auto.reflect(plan, results, goal_ctx)
        claude.reflect.assert_awaited_once_with(plan, results, goal_ctx)

    @pytest.mark.asyncio
    async def test_reflect_without_goal_context(self) -> None:
        """AutoPlanner.reflect works without goal_context (single-pass mode)."""
        direct = _make_planner("direct")
        auto = AutoPlanner(direct=direct)

        plan = Plan(goal="test", steps=[PlanStep(id="s1", description="step")])
        results = [StepResult(step_id="s1", output="ok", success=True)]

        await auto.reflect(plan, results)
        direct.reflect.assert_awaited_once_with(plan, results, None)


class TestAutoRoutingModes:
    """Test different routing_mode configurations."""

    @pytest.mark.asyncio
    async def test_heuristic_mode_no_llm_call(self) -> None:
        """In heuristic mode, _llm_classify is never called."""
        direct = _make_planner("direct")
        fast_model = MagicMock()
        auto = AutoPlanner(direct=direct, fast_model=fast_model, routing_mode="heuristic")

        # 40 tokens, no keywords -- would be ambiguous in hybrid mode
        goal = " ".join(["something"] * 40)
        await auto.create_plan(goal, PlanContext())
        fast_model.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_hybrid_mode_calls_llm_for_ambiguous(self) -> None:
        """In hybrid mode, ambiguous goals trigger LLM classification."""
        direct = _make_planner("direct")
        subagent = _make_planner("subagent")

        mock_response = MagicMock()
        mock_response.content = "medium"
        fast_model = MagicMock()
        fast_model.ainvoke = AsyncMock(return_value=mock_response)

        auto = AutoPlanner(
            direct=direct,
            subagent=subagent,
            fast_model=fast_model,
            routing_mode="hybrid",
        )

        # 40 tokens, no keywords -- ambiguous for heuristic (between 30 and 160)
        goal = " ".join(["something"] * 40)
        await auto.create_plan(goal, PlanContext())
        fast_model.ainvoke.assert_awaited_once()
        subagent.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_mode_always_classifies(self) -> None:
        """In llm mode, classification always uses the fast model."""
        direct = _make_planner("direct")
        subagent = _make_planner("subagent")

        mock_response = MagicMock()
        mock_response.content = "simple"
        fast_model = MagicMock()
        fast_model.ainvoke = AsyncMock(return_value=mock_response)

        auto = AutoPlanner(
            direct=direct,
            subagent=subagent,
            fast_model=fast_model,
            routing_mode="llm",
        )

        await auto.create_plan("implement auth", PlanContext())
        fast_model.ainvoke.assert_awaited_once()
        direct.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hybrid_skips_llm_when_heuristic_matches(self) -> None:
        """In hybrid mode, clear matches don't trigger LLM classification."""
        direct = _make_planner("direct")
        fast_model = MagicMock()
        auto = AutoPlanner(direct=direct, fast_model=fast_model, routing_mode="hybrid")

        await auto.create_plan("hello", PlanContext())
        fast_model.ainvoke.assert_not_called()
        direct.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hybrid_fallback_when_llm_fails(self) -> None:
        """When LLM classification fails, falls back to default routing."""
        direct = _make_planner("direct")
        fast_model = MagicMock()
        fast_model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        auto = AutoPlanner(direct=direct, fast_model=fast_model, routing_mode="hybrid")

        # 40 tokens, no keywords -- ambiguous
        goal = " ".join(["something"] * 40)
        await auto.create_plan(goal, PlanContext())
        # Should still produce a plan via fallback
        direct.create_plan.assert_awaited_once()
