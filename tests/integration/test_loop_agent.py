"""Integration tests for Layer 2 LoopAgent (RFC-0008)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition.loop_agent import LoopAgent
from soothe.cognition.loop_agent.schemas import (
    AgentDecision,
    JudgeResult,
    StepAction,
    StepResult,
)
from soothe.protocols.planner import PlanContext


class MockPlanner:
    """Mock planner for testing."""

    def __init__(self):
        self.decision_count = 0

    async def decide_steps(
        self,
        goal: str,
        context: PlanContext,
        previous_judgment: JudgeResult | None = None,
    ) -> AgentDecision:
        """Return mock decision based on iteration."""
        self.decision_count += 1

        if self.decision_count == 1:
            # First decision: 3 steps
            return AgentDecision(
                type="execute_steps",
                steps=[
                    StepAction(
                        id="s1",
                        description="Step 1",
                        expected_output="Output 1",
                    ),
                    StepAction(
                        id="s2",
                        description="Step 2",
                        expected_output="Output 2",
                    ),
                    StepAction(
                        id="s3",
                        description="Step 3",
                        expected_output="Output 3",
                    ),
                ],
                execution_mode="sequential",
                reasoning="Initial plan",
            )
        # Second decision: replan with 2 steps
        return AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(
                    id="s4",
                    description="Revised step 1",
                    expected_output="New output 1",
                ),
                StepAction(
                    id="s5",
                    description="Revised step 2",
                    expected_output="New output 2",
                ),
            ],
            execution_mode="parallel",
            reasoning="Revised plan after replan",
        )


class MockJudge:
    """Mock judge for testing."""

    def __init__(self, scenario: str = "success"):
        """Initialize mock judge with scenario.

        Args:
            scenario: "success", "replan", or "continue"
        """
        self.scenario = scenario
        self.judge_count = 0

    async def judge(
        self,
        goal: str,
        evidence: list[StepResult],
        steps: list[StepAction],
    ) -> JudgeResult:
        """Return mock judgment based on scenario."""
        self.judge_count += 1

        if self.scenario == "success":
            # First iteration: done
            return JudgeResult(
                status="done",
                evidence_summary="Goal achieved",
                goal_progress=1.0,
                confidence=0.95,
                reasoning="All steps successful",
            )

        if self.scenario == "replan":
            # First iteration: replan
            # Second iteration: done
            if self.judge_count == 1:
                return JudgeResult(
                    status="replan",
                    evidence_summary="Need different approach",
                    goal_progress=0.3,
                    confidence=0.7,
                    reasoning="Steps failed, need replan",
                )
            return JudgeResult(
                status="done",
                evidence_summary="Goal achieved after replan",
                goal_progress=1.0,
                confidence=0.9,
                reasoning="Revised plan succeeded",
            )

        if self.scenario == "continue":
            # First iteration: continue
            # Second iteration: done
            if self.judge_count == 1:
                return JudgeResult(
                    status="continue",
                    evidence_summary="Progress made, continue",
                    goal_progress=0.6,
                    confidence=0.8,
                    reasoning="Strategy valid, continue",
                )
            return JudgeResult(
                status="done",
                evidence_summary="Goal achieved",
                goal_progress=1.0,
                confidence=0.95,
                reasoning="Completed remaining steps",
            )

        return JudgeResult(
            status="done",
            evidence_summary="Default done",
            goal_progress=1.0,
            confidence=0.9,
            reasoning="Default",
        )


class MockCoreAgent:
    """Mock CoreAgent for testing."""

    def __init__(self):
        self.call_count = 0

    async def astream(self, user_input: str, config: dict):
        """Mock astream that returns simple output."""

        async def mock_stream():
            self.call_count += 1
            yield {"content": f"Mock output for: {user_input[:50]}"}

        return mock_stream()


@pytest.mark.asyncio
async def test_loop_agent_success():
    """Test LoopAgent with successful execution."""
    planner = MockPlanner()
    judge = MockJudge(scenario="success")
    core_agent = MockCoreAgent()

    config = MagicMock()
    config.agentic.max_iterations = 8

    loop_agent = LoopAgent(
        core_agent=core_agent,
        planner=planner,
        judge=judge,
        config=config,
    )

    # Run loop
    result = await loop_agent.run(
        goal="Test goal",
        thread_id="test_thread",
        max_iterations=8,
    )

    # Verify result
    assert result.status == "done"
    assert result.goal_progress == 1.0
    assert planner.decision_count == 1
    assert judge.judge_count == 1


@pytest.mark.asyncio
async def test_loop_agent_with_replan():
    """Test LoopAgent with replan scenario."""
    planner = MockPlanner()
    judge = MockJudge(scenario="replan")
    core_agent = MockCoreAgent()

    config = MagicMock()
    config.agentic.max_iterations = 8

    loop_agent = LoopAgent(
        core_agent=core_agent,
        planner=planner,
        judge=judge,
        config=config,
    )

    # Run loop
    result = await loop_agent.run(
        goal="Test goal that needs replan",
        thread_id="test_thread",
        max_iterations=8,
    )

    # Verify result
    assert result.status == "done"
    assert planner.decision_count == 2  # Initial + replan
    assert judge.judge_count == 2  # After each plan execution


@pytest.mark.asyncio
async def test_loop_agent_with_continue():
    """Test LoopAgent with continue scenario."""
    planner = MockPlanner()
    judge = MockJudge(scenario="continue")
    core_agent = MockCoreAgent()

    config = MagicMock()
    config.agentic.max_iterations = 8

    loop_agent = LoopAgent(
        core_agent=core_agent,
        planner=planner,
        judge=judge,
        config=config,
    )

    # Run loop
    result = await loop_agent.run(
        goal="Test goal with continue",
        thread_id="test_thread",
        max_iterations=8,
    )

    # Verify result
    assert result.status == "done"
    assert planner.decision_count == 1  # Decision reused
    assert judge.judge_count == 2


@pytest.mark.asyncio
async def test_loop_agent_max_iterations():
    """Test LoopAgent respects max iterations."""

    class NeverDoneJudge:
        """Judge that never completes."""

        def __init__(self):
            self.judge_count = 0

        async def judge(self, goal, evidence, steps):
            self.judge_count += 1
            return JudgeResult(
                status="continue",
                evidence_summary="Not done yet",
                goal_progress=0.1,
                confidence=0.5,
                reasoning="Need more work",
            )

    planner = MockPlanner()
    judge = NeverDoneJudge()
    core_agent = MockCoreAgent()

    config = MagicMock()
    config.agentic.max_iterations = 3

    loop_agent = LoopAgent(
        core_agent=core_agent,
        planner=planner,
        judge=judge,
        config=config,
    )

    # Run loop with max 3 iterations
    result = await loop_agent.run(
        goal="Never ending task",
        thread_id="test_thread",
        max_iterations=3,
    )

    # Should hit max iterations
    assert judge.judge_count == 3
    assert result.status == "continue"  # Not done


@pytest.mark.asyncio
async def test_loop_agent_parallel_execution():
    """Test LoopAgent with parallel execution mode."""

    class ParallelPlanner:
        """Planner that returns parallel execution."""

        async def decide_steps(self, goal, context, previous_judgment=None):
            return AgentDecision(
                type="execute_steps",
                steps=[
                    StepAction(
                        id=f"s{i}",
                        description=f"Parallel step {i}",
                        expected_output=f"Output {i}",
                    )
                    for i in range(3)
                ],
                execution_mode="parallel",
                reasoning="Execute in parallel",
            )

    planner = ParallelPlanner()
    judge = MockJudge(scenario="success")
    core_agent = MockCoreAgent()

    config = MagicMock()
    config.agentic.max_iterations = 8

    loop_agent = LoopAgent(
        core_agent=core_agent,
        planner=planner,
        judge=judge,
        config=config,
    )

    # Run loop
    result = await loop_agent.run(
        goal="Parallel task",
        thread_id="test_thread",
        max_iterations=8,
    )

    # Verify parallel execution (3 concurrent calls)
    assert core_agent.call_count == 3
    assert result.status == "done"
