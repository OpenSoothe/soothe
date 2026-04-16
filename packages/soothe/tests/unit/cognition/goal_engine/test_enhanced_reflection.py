"""Tests for enhanced dependency-aware reflect() (RFC-0010)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.cognition.agent_loop.planner import LLMPlanner
from soothe.protocols.planner import Plan, PlanStep, StepResult


@pytest.fixture
def planner() -> LLMPlanner:
    return LLMPlanner(model=MagicMock())


def _plan_with_deps() -> Plan:
    """Create a plan where step s3 depends on s1 and s2."""
    return Plan(
        goal="Test task",
        steps=[
            PlanStep(id="s1", description="Fetch data"),
            PlanStep(id="s2", description="Analyze data", depends_on=["s1"]),
            PlanStep(id="s3", description="Summarize", depends_on=["s1", "s2"]),
        ],
    )


class TestEnhancedReflection:
    """Test dependency-aware reflection."""

    @pytest.mark.asyncio
    async def test_all_success(self, planner: LLMPlanner) -> None:
        plan = _plan_with_deps()
        results = [
            StepResult(step_id="s1", success=True, outcome={"type": "generic", "size_bytes": 2}),
            StepResult(step_id="s2", success=True, outcome={"type": "generic", "size_bytes": 2}),
            StepResult(step_id="s3", success=True, outcome={"type": "generic", "size_bytes": 2}),
        ]
        reflection = await planner.reflect(plan, results)
        assert not reflection.should_revise
        assert reflection.blocked_steps == []
        assert reflection.failed_details == {}
        assert "3/3" in reflection.assessment

    @pytest.mark.asyncio
    async def test_direct_failure(self, planner: LLMPlanner) -> None:
        """s1 fails directly (no dependencies)."""
        plan = _plan_with_deps()
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "error", "error": "timeout"},
                error="timeout",
            ),
        ]
        reflection = await planner.reflect(plan, results)
        assert reflection.should_revise
        assert "s1" not in reflection.blocked_steps
        assert "s1" in reflection.failed_details
        assert "timeout" in reflection.failed_details["s1"]

    @pytest.mark.asyncio
    async def test_blocked_by_dependency(self, planner: LLMPlanner) -> None:
        """s1 fails, s2 depends on s1 so s2 is blocked."""
        plan = _plan_with_deps()
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "error", "error": "connection error"},
                error="connection error",
            ),
            StepResult(
                step_id="s2",
                success=False,
                outcome={"type": "error", "error": "dependency failed"},
                error="dependency failed",
            ),
        ]
        reflection = await planner.reflect(plan, results)
        assert reflection.should_revise
        assert "s2" in reflection.blocked_steps
        assert "s1" not in reflection.blocked_steps
        assert "Directly failed" in reflection.assessment
        assert "Blocked by dependencies" in reflection.assessment

    @pytest.mark.asyncio
    async def test_cascading_block(self, planner: LLMPlanner) -> None:
        """s1 fails, s2 blocked by s1, s3 blocked by both."""
        plan = _plan_with_deps()
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "error", "error": "error"},
                error="error",
            ),
            StepResult(
                step_id="s2",
                success=False,
                outcome={"type": "error", "error": "blocked"},
                error="blocked",
            ),
            StepResult(
                step_id="s3",
                success=False,
                outcome={"type": "error", "error": "blocked"},
                error="blocked",
            ),
        ]
        reflection = await planner.reflect(plan, results)
        assert reflection.should_revise
        assert "s2" in reflection.blocked_steps
        assert "s3" in reflection.blocked_steps
        assert "s1" not in reflection.blocked_steps
        assert len(reflection.failed_details) == 3

    @pytest.mark.asyncio
    async def test_independent_failure_no_block(self, planner: LLMPlanner) -> None:
        """s1 and s2 fail independently (s2 depends on s1, but s1 also fails)."""
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(id="s1", description="Step A"),
                PlanStep(id="s2", description="Step B"),
            ],
        )
        results = [
            StepResult(
                step_id="s1", success=False, outcome={"type": "error", "error": "err"}, error="err"
            ),
            StepResult(
                step_id="s2", success=False, outcome={"type": "error", "error": "err"}, error="err"
            ),
        ]
        reflection = await planner.reflect(plan, results)
        assert reflection.should_revise
        assert reflection.blocked_steps == []
        assert len(reflection.failed_details) == 2
