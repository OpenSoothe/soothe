"""Tests for enhanced dependency-aware reflect() (RFC-0010)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.cognition.planning.simple import SimplePlanner
from soothe.protocols.planner import Plan, PlanStep, StepResult


@pytest.fixture
def planner() -> SimplePlanner:
    return SimplePlanner(model=MagicMock())


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
    async def test_all_success(self, planner: SimplePlanner) -> None:
        plan = _plan_with_deps()
        results = [
            StepResult(step_id="s1", output="ok", success=True),
            StepResult(step_id="s2", output="ok", success=True),
            StepResult(step_id="s3", output="ok", success=True),
        ]
        reflection = await planner.reflect(plan, results)
        assert not reflection.should_revise
        assert reflection.blocked_steps == []
        assert reflection.failed_details == {}
        assert "3/3" in reflection.assessment

    @pytest.mark.asyncio
    async def test_direct_failure(self, planner: SimplePlanner) -> None:
        """s1 fails directly (no dependencies)."""
        plan = _plan_with_deps()
        results = [
            StepResult(step_id="s1", output="timeout", success=False),
        ]
        reflection = await planner.reflect(plan, results)
        assert reflection.should_revise
        assert "s1" not in reflection.blocked_steps
        assert "s1" in reflection.failed_details
        assert "timeout" in reflection.failed_details["s1"]

    @pytest.mark.asyncio
    async def test_blocked_by_dependency(self, planner: SimplePlanner) -> None:
        """s1 fails, s2 depends on s1 so s2 is blocked."""
        plan = _plan_with_deps()
        results = [
            StepResult(step_id="s1", output="connection error", success=False),
            StepResult(step_id="s2", output="dependency failed", success=False),
        ]
        reflection = await planner.reflect(plan, results)
        assert reflection.should_revise
        assert "s2" in reflection.blocked_steps
        assert "s1" not in reflection.blocked_steps
        assert "Directly failed" in reflection.assessment
        assert "Blocked by dependencies" in reflection.assessment

    @pytest.mark.asyncio
    async def test_cascading_block(self, planner: SimplePlanner) -> None:
        """s1 fails, s2 blocked by s1, s3 blocked by both."""
        plan = _plan_with_deps()
        results = [
            StepResult(step_id="s1", output="error", success=False),
            StepResult(step_id="s2", output="blocked", success=False),
            StepResult(step_id="s3", output="blocked", success=False),
        ]
        reflection = await planner.reflect(plan, results)
        assert reflection.should_revise
        assert "s2" in reflection.blocked_steps
        assert "s3" in reflection.blocked_steps
        assert "s1" not in reflection.blocked_steps
        assert len(reflection.failed_details) == 3

    @pytest.mark.asyncio
    async def test_independent_failure_no_block(self, planner: SimplePlanner) -> None:
        """s1 and s2 fail independently (s2 depends on s1, but s1 also fails)."""
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(id="s1", description="Step A"),
                PlanStep(id="s2", description="Step B"),
            ],
        )
        results = [
            StepResult(step_id="s1", output="err", success=False),
            StepResult(step_id="s2", output="err", success=False),
        ]
        reflection = await planner.reflect(plan, results)
        assert reflection.should_revise
        assert reflection.blocked_steps == []
        assert len(reflection.failed_details) == 2
