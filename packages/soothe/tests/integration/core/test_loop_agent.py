"""Integration tests for Layer 2 AgentLoop (RFC-0008)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.cognition.agent_loop import AgentLoop
from soothe.cognition.agent_loop.schemas import (
    AgentDecision,
    ReasonResult,
    StepAction,
)
from soothe.protocols.planner import PlanContext


def _three_step_decision() -> AgentDecision:
    return AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="s1", description="Step 1", expected_output="Output 1"),
            StepAction(id="s2", description="Step 2", expected_output="Output 2"),
            StepAction(id="s3", description="Step 3", expected_output="Output 3"),
        ],
        execution_mode="sequential",
        reasoning="Initial plan",
    )


def _two_step_replan_decision() -> AgentDecision:
    return AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="s4", description="Revised step 1", expected_output="New output 1"),
            StepAction(id="s5", description="Revised step 2", expected_output="New output 2"),
        ],
        execution_mode="parallel",
        reasoning="Revised plan after replan",
    )


class MockLoopReasoner:
    """Drives Reason phase for tests (one LLM call per outer iteration)."""

    def __init__(self, scenario: str = "success") -> None:
        self.scenario = scenario
        self.reason_count = 0

    async def reason(self, goal: str, state, context: PlanContext) -> ReasonResult:
        self.reason_count += 1

        if self.scenario == "success":
            if self.reason_count == 1:
                return ReasonResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll run these three steps next.",
                    reasoning="First pass",
                )
            return ReasonResult(
                status="done",
                plan_action="keep",
                next_action="I'm done and sharing the outcome.",
                reasoning="Done",
                goal_progress=1.0,
                confidence=0.95,
            )

        if self.scenario == "replan":
            if self.reason_count == 1:
                return ReasonResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll start with this three-step approach.",
                    reasoning="v1",
                )
            if self.reason_count == 2:
                return ReasonResult(
                    status="replan",
                    plan_action="new",
                    decision=_two_step_replan_decision(),
                    next_action="I'll switch to a tighter two-step plan.",
                    reasoning="replan",
                    goal_progress=0.3,
                )
            return ReasonResult(
                status="done",
                plan_action="keep",
                next_action="I'm wrapping up after the revised plan.",
                goal_progress=1.0,
                confidence=0.9,
            )

        if self.scenario == "continue":
            if self.reason_count == 1:
                return ReasonResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll execute the first chunk of work now.",
                    reasoning="start",
                )
            return ReasonResult(
                status="done",
                plan_action="keep",
                next_action="I'm done with the remaining work.",
                goal_progress=1.0,
                confidence=0.95,
            )

        return ReasonResult(
            status="done",
            plan_action="keep",
            next_action="I'm done.",
            goal_progress=1.0,
            confidence=0.9,
        )


class MockCoreAgent:
    """Mock CoreAgent for testing."""

    def __init__(self) -> None:
        self.call_count = 0

    def astream(self, user_input: str, config: dict, **kwargs: Any):
        """Return an async iterator like ``CoreAgent.astream`` (not a coroutine)."""

        async def mock_stream():
            self.call_count += 1
            yield {"content": f"Mock output for: {user_input[:50]}"}

        return mock_stream()


def _make_config(max_iterations: int = 8) -> MagicMock:
    cfg = MagicMock()
    cfg.subagents = {}
    cfg.agentic.max_iterations = max_iterations
    return cfg


@pytest.mark.asyncio
async def test_loop_agent_success() -> None:
    """Test AgentLoop with successful execution."""
    reasoner = MockLoopReasoner(scenario="success")
    core_agent = MockCoreAgent()
    loop_agent = AgentLoop(
        core_agent=core_agent,
        loop_reasoner=reasoner,
        config=_make_config(),
    )

    result = await loop_agent.run(
        goal="Test goal",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"
    assert result.goal_progress == 1.0
    assert reasoner.reason_count == 2


@pytest.mark.asyncio
async def test_loop_agent_with_replan() -> None:
    """Test AgentLoop with replan scenario."""
    reasoner = MockLoopReasoner(scenario="replan")
    core_agent = MockCoreAgent()
    loop_agent = AgentLoop(
        core_agent=core_agent,
        loop_reasoner=reasoner,
        config=_make_config(),
    )

    result = await loop_agent.run(
        goal="Test goal that needs replan",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"
    assert reasoner.reason_count == 3


@pytest.mark.asyncio
async def test_loop_agent_with_continue() -> None:
    """Test AgentLoop with continue-then-done scenario."""
    reasoner = MockLoopReasoner(scenario="continue")
    core_agent = MockCoreAgent()
    loop_agent = AgentLoop(
        core_agent=core_agent,
        loop_reasoner=reasoner,
        config=_make_config(),
    )

    result = await loop_agent.run(
        goal="Test goal with continue",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"
    assert reasoner.reason_count == 2


@pytest.mark.asyncio
async def test_loop_agent_max_iterations() -> None:
    """Test AgentLoop respects max iterations."""

    class NeverDoneReasoner:
        def __init__(self) -> None:
            self.reason_count = 0

        async def reason(self, goal, state, context):
            self.reason_count += 1
            return ReasonResult(
                status="continue",
                plan_action="new",
                decision=AgentDecision(
                    type="execute_steps",
                    steps=[
                        StepAction(
                            id="s_x",
                            description=goal,
                            expected_output="more",
                        )
                    ],
                    execution_mode="sequential",
                    reasoning="more work",
                ),
                next_action="I'll take another step toward the goal.",
                goal_progress=0.1,
                confidence=0.5,
            )

    reasoner = NeverDoneReasoner()
    core_agent = MockCoreAgent()
    loop_agent = AgentLoop(
        core_agent=core_agent,
        loop_reasoner=reasoner,
        config=_make_config(max_iterations=3),
    )

    result = await loop_agent.run(
        goal="Never ending task",
        thread_id="test_thread",
        max_iterations=3,
    )

    assert reasoner.reason_count == 3
    assert result.status == "continue"


@pytest.mark.asyncio
async def test_loop_agent_parallel_execution() -> None:
    """Test AgentLoop with parallel execution mode."""

    class ParallelReasoner:
        def __init__(self) -> None:
            self.reason_count = 0

        async def reason(self, goal, state, context):
            self.reason_count += 1
            if self.reason_count == 1:
                return ReasonResult(
                    status="continue",
                    plan_action="new",
                    decision=AgentDecision(
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
                        reasoning="parallel batch",
                    ),
                    next_action="I'll run these three steps in parallel.",
                )
            return ReasonResult(
                status="done",
                plan_action="keep",
                next_action="I'm finished with the parallel work.",
                goal_progress=1.0,
                confidence=0.95,
            )

    reasoner = ParallelReasoner()
    core_agent = MockCoreAgent()
    loop_agent = AgentLoop(
        core_agent=core_agent,
        loop_reasoner=reasoner,
        config=_make_config(),
    )

    result = await loop_agent.run(
        goal="Parallel task",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert core_agent.call_count == 3
    assert result.status == "done"
