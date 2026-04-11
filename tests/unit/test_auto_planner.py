"""Tests for AutoPlanner routing with unified classification (RFC-0012)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition.planning.router import AutoPlanner
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


def _make_classification(task_complexity: str) -> MagicMock:
    """Create a mock unified classification."""
    classification = MagicMock()
    classification.task_complexity = task_complexity
    classification.is_plan_only = False
    return classification


class TestAutoPlanner:
    """Unit tests for AutoPlanner routing with unified classification."""

    @pytest.mark.asyncio
    async def test_chitchat_goal_routes_to_simple_planner(self) -> None:
        """Chitchat classification routes to LLMPlanner (shouldn't reach here normally)."""
        simple = _make_planner("simple")
        auto = AutoPlanner(simple=simple)

        context = PlanContext(unified_classification=_make_classification("chitchat"))
        await auto.create_plan("hello world", context)
        simple.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_medium_goal_routes_to_simple_planner(self) -> None:
        """Medium classification routes to LLMPlanner."""
        simple = _make_planner("simple")
        auto = AutoPlanner(simple=simple)

        context = PlanContext(unified_classification=_make_classification("medium"))
        await auto.create_plan("implement user authentication", context)
        simple.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complex_goal_routes_to_claude(self) -> None:
        """Complex classification routes to ClaudePlanner."""
        simple = _make_planner("simple")
        claude = _make_planner("claude")
        auto = AutoPlanner(claude=claude, simple=simple)

        context = PlanContext(unified_classification=_make_classification("complex"))
        await auto.create_plan("architect a new microservices system", context)
        claude.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complex_fallback_to_simple_when_no_claude(self) -> None:
        """Complex classification falls back to LLMPlanner when Claude is unavailable."""
        simple = _make_planner("simple")
        auto = AutoPlanner(claude=None, simple=simple)

        context = PlanContext(unified_classification=_make_classification("complex"))
        await auto.create_plan("architect a new microservices system", context)
        simple.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_when_no_unified_classification(self) -> None:
        """Without unified classification, falls back to token-count heuristic."""
        simple = _make_planner("simple")
        auto = AutoPlanner(simple=simple, use_tiktoken=False)

        # Short goal -> simple (< 30 tokens)
        context = PlanContext()
        await auto.create_plan("hello world", context)
        simple.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reflect_forwards_goal_context(self) -> None:
        """AutoPlanner.reflect must forward goal_context to the delegate."""
        claude = _make_planner("claude")
        auto = AutoPlanner(claude=claude)

        plan = Plan(goal="test", steps=[PlanStep(id="s1", description="step")])
        results = [StepResult(step_id="s1", success=True, outcome={"type": "generic", "size_bytes": 2})]
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
        simple = _make_planner("simple")
        auto = AutoPlanner(simple=simple)

        plan = Plan(goal="test", steps=[PlanStep(id="s1", description="step")])
        results = [StepResult(step_id="s1", success=True, outcome={"type": "generic", "size_bytes": 2})]

        await auto.reflect(plan, results)
        simple.reflect.assert_awaited_once_with(plan, results, None)


class TestAutoPlannerFallback:
    """Test fallback routing without unified classification."""

    @pytest.mark.asyncio
    async def test_fallback_simple_threshold(self) -> None:
        """Fallback routes short goals to LLMPlanner."""
        simple = _make_planner("simple")
        auto = AutoPlanner(simple=simple, use_tiktoken=False)

        # < 30 tokens -> medium (chitchat shouldn't reach here, defaults to medium)
        context = PlanContext()
        await auto.create_plan("hello world", context)
        simple.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_complex_threshold(self) -> None:
        """Fallback routes long goals to best available planner."""
        simple = _make_planner("simple")
        claude = _make_planner("claude")
        auto = AutoPlanner(claude=claude, simple=simple, use_tiktoken=False, complex_token_threshold=160)

        # Very long goal (>= 160 tokens) -> complex
        long_goal = " ".join(["word"] * 200)
        context = PlanContext()
        await auto.create_plan(long_goal, context)
        # Should use claude
        claude.create_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_medium_range(self) -> None:
        """Fallback routes medium-length goals to LLMPlanner."""
        simple = _make_planner("simple")
        auto = AutoPlanner(
            simple=simple,
            use_tiktoken=False,
            medium_token_threshold=30,
            complex_token_threshold=160,
        )

        # Between 30 and 160 tokens -> medium
        medium_goal = " ".join(["word"] * 50)
        context = PlanContext()
        await auto.create_plan(medium_goal, context)
        simple.create_plan.assert_awaited_once()
