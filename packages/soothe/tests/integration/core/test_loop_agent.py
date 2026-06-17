"""Integration tests for Layer 2 StrangeLoop (RFC-0008)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.foundation.loop import StrangeLoop
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    PlanResult,
    StatusAssessment,
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
        execution_mode="parallel",
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


class MockLoopPlanner:
    """Drives Plan phase for tests (one LLM call per outer iteration)."""

    def __init__(self, scenario: str = "success") -> None:
        self.scenario = scenario
        self.plan_count = 0
        self._assess_count = 0
        self._generate_count = 0
        # StrangeLoop goal completion constructs ``SynthesisGenerator(loop_planner._model, ...)``.
        self._model = MagicMock()

    async def assess_status(
        self, goal: str, state, context: PlanContext, *, context_engine: Any | None = None
    ):
        """Assess-only call for split graph flow."""
        from soothe.foundation.loop.state.schemas import StatusAssessment

        self._assess_count += 1

        if self.scenario == "success":
            # First assess: need work, second assess: done
            if self._assess_count == 1:
                return StatusAssessment(
                    status="continue",
                    goal_progress="none",
                    assessment_reasoning="Starting work",
                    require_goal_completion=False,
                )
            return StatusAssessment(
                status="done",
                goal_progress="complete",
                assessment_reasoning="All work complete",
                require_goal_completion=True,
            )

        if self.scenario == "replan":
            # Three iterations: continue -> replan -> done
            if self._assess_count == 1:
                return StatusAssessment(
                    status="continue",
                    goal_progress="none",
                    assessment_reasoning="Starting first approach",
                    require_goal_completion=False,
                )
            if self._assess_count == 2:
                return StatusAssessment(
                    status="replan",
                    goal_progress="low",
                    assessment_reasoning="First approach failed, need replan",
                    require_goal_completion=False,
                )
            return StatusAssessment(
                status="done",
                goal_progress="complete",
                assessment_reasoning="Revised plan succeeded",
                require_goal_completion=True,
            )

        if self.scenario == "continue":
            # Two iterations: continue -> done
            if self._assess_count == 1:
                return StatusAssessment(
                    status="continue",
                    goal_progress="none",
                    assessment_reasoning="Starting work",
                    require_goal_completion=False,
                )
            return StatusAssessment(
                status="done",
                goal_progress="complete",
                assessment_reasoning="Work complete",
                require_goal_completion=True,
            )

        return StatusAssessment(
            status="done",
            goal_progress="complete",
            assessment_reasoning="Default done",
            require_goal_completion=True,
        )

    async def generate_from_assessment(
        self,
        goal: str,
        state,
        context: PlanContext,
        assessment,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
    ):
        """Generate plan after assessment (split graph flow)."""
        self._generate_count += 1

        if assessment.status == "done":
            return PlanResult(
                status="done",
                plan_action="keep",
                next_action="Goal achieved",
                goal_progress=assessment.goal_progress,
            )

        if self.scenario == "success":
            if self._generate_count == 1:
                return PlanResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll run these three steps next.",
                    reasoning="First pass",
                )

        if self.scenario == "replan":
            if self._generate_count == 1:
                return PlanResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll start with this three-step approach.",
                    reasoning="v1",
                )
            if self._generate_count == 2:
                return PlanResult(
                    status="replan",
                    plan_action="new",
                    decision=_two_step_replan_decision(),
                    next_action="I'll switch to a tighter two-step plan.",
                    reasoning="replan",
                    goal_progress="low",
                )

        if self.scenario == "continue":
            if self._generate_count == 1:
                return PlanResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll execute the first chunk of work now.",
                    reasoning="start",
                )

        # Fallback
        return PlanResult(
            status="continue",
            plan_action="new",
            decision=_three_step_decision(),
            next_action="Working on it",
            reasoning="fallback",
        )

    async def plan(self, goal: str, state, context: PlanContext) -> PlanResult:
        """Legacy unified plan method (not used by split graph flow)."""
        self.plan_count += 1

        if self.scenario == "success":
            if self.plan_count == 1:
                return PlanResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll run these three steps next.",
                    reasoning="First pass",
                )
            return PlanResult(
                status="done",
                plan_action="keep",
                next_action="I'm done and sharing the outcome.",
                reasoning="Done",
                goal_progress="complete",
            )

        if self.scenario == "replan":
            if self.plan_count == 1:
                return PlanResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll start with this three-step approach.",
                    reasoning="v1",
                )
            if self.plan_count == 2:
                return PlanResult(
                    status="replan",
                    plan_action="new",
                    decision=_two_step_replan_decision(),
                    next_action="I'll switch to a tighter two-step plan.",
                    reasoning="replan",
                    goal_progress="low",
                )
            return PlanResult(
                status="done",
                plan_action="keep",
                next_action="I'm wrapping up after the revised plan.",
                goal_progress="complete",
            )

        if self.scenario == "continue":
            if self.plan_count == 1:
                return PlanResult(
                    status="continue",
                    plan_action="new",
                    decision=_three_step_decision(),
                    next_action="I'll execute the first chunk of work now.",
                    reasoning="start",
                )
            return PlanResult(
                status="done",
                plan_action="keep",
                next_action="I'm done with the remaining work.",
                goal_progress="complete",
            )

        return PlanResult(
            status="done",
            plan_action="keep",
            next_action="I'm done.",
            goal_progress="complete",
        )


class MockCoreAgent:
    """Mock CoreAgent for testing."""

    def __init__(self) -> None:
        self.call_count = 0
        # Mock graph attribute for iteration_start anchor capture
        self.graph = MagicMock()
        self.graph.checkpointer = None

    @property
    def checkpointer(self) -> None:
        """Mock checkpointer property (always None for tests)."""
        return self.graph.checkpointer

    def astream(self, user_input: str, config: dict, **kwargs: Any):
        """Return an async iterator like ``CoreAgent.astream`` (not a coroutine)."""

        async def mock_stream():
            self.call_count += 1
            # Use message format expected by strange_loop
            yield {"messages": [{"content": f"Mock output for: {user_input}"}]}

        return mock_stream()

    def execution_astream(self, user_input: str, config: dict, **kwargs: Any):
        """Return an async iterator like ``CoreAgent.execution_astream`` (ephemeral twin graph)."""

        async def mock_stream():
            self.call_count += 1
            # Use message format expected by executor
            yield {"messages": [{"content": f"Mock execute output for: {user_input}"}]}

        return mock_stream()


def _make_config(max_iterations: int = 8) -> MagicMock:
    cfg = MagicMock()
    cfg.subagents = {}
    cfg.agent = MagicMock()
    al = cfg.agent.loop
    al.max_iterations = max_iterations
    al.max_subagent_tasks_per_wave = 16
    al.context_window_limit = 128000
    al.working_memory.max_inline_chars = 4000
    al.working_memory.max_entry_chars_before_spill = 500
    # Concurrency config (LoopConcurrencyConfig)
    al.concurrency.max_parallel_steps = 1
    al.concurrency.max_parallel_goals = 1
    al.concurrency.max_parallel_tools = 5
    al.concurrency.max_parallel_subagents = 4
    # Thread switch policy: set on loop config directly, not on limits
    # _get_rate_limit_threshold looks at loop_cfg.thread_switch_policy
    al.thread_switch_policy = None
    # Goal completion / synthesis config
    al.goal_completion_mode = "llm_only"
    al.report_output.synthesis_max_chars = 10000
    al.report_output.synthesis_include_full_outputs = True
    al.report_output.output_summary_max_chars = 1500
    # Model attribute for SynthesisGenerator
    al.synthesis_model = None  # Will use planner._model
    # Router / observability
    cfg.router.fast = None
    cfg.observability.langfuse.trace_name = None
    cfg.observability.langfuse.enabled = False
    # Persistence backend for ContextEngine (RFC-624 Phase 4)
    cfg.persistence.default_backend = "sqlite"
    # Delete 'home' attribute so strange_loop uses SOOTHE_HOME default
    # (MagicMock creates attributes lazily, so we must explicitly delete)
    del cfg.home
    return cfg


@pytest.mark.asyncio
async def test_loop_agent_success() -> None:
    """Test StrangeLoop with successful execution."""
    planner = MockLoopPlanner(scenario="success")
    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(
        core_agent=core_agent,
        loop_planner=planner,
        config=_make_config(),
    )

    result = await loop_agent.run(
        goal="Test goal",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"
    assert result.goal_progress == "complete"
    # Split graph flow uses assess_status + generate_from_assessment
    assert planner._assess_count == 2  # Two iterations
    assert planner._generate_count == 2  # Each assess triggers a generate call


@pytest.mark.asyncio
async def test_loop_agent_with_replan() -> None:
    """Test StrangeLoop with replan scenario."""
    planner = MockLoopPlanner(scenario="replan")
    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(
        core_agent=core_agent,
        loop_planner=planner,
        config=_make_config(),
    )

    result = await loop_agent.run(
        goal="Test goal that needs replan",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"
    # Replan scenario: 3 iterations (continue -> replan -> done)
    assert planner._assess_count == 3
    assert planner._generate_count == 3  # Each assess triggers a generate call


@pytest.mark.asyncio
async def test_loop_agent_with_continue() -> None:
    """Test StrangeLoop with continue-then-done scenario."""
    planner = MockLoopPlanner(scenario="continue")
    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(
        core_agent=core_agent,
        loop_planner=planner,
        config=_make_config(),
    )

    result = await loop_agent.run(
        goal="Test goal with continue",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"
    # Continue scenario: 2 iterations
    assert planner._assess_count == 2
    assert planner._generate_count == 2  # Each assess triggers a generate call


@pytest.mark.asyncio
async def test_loop_agent_max_iterations() -> None:
    """Test StrangeLoop respects max iterations."""

    class NeverDonePlanner:
        def __init__(self) -> None:
            self.plan_count = 0
            self._assess_count = 0
            self._generate_count = 0

        async def assess_status(self, goal, state, context, *, context_engine: Any | None = None):
            """Assess-only: always needs more work."""
            self._assess_count += 1
            return StatusAssessment(
                status="continue",
                goal_progress="none",
                assessment_reasoning="Always needs more work",
                require_goal_completion=False,
            )

        async def generate_from_assessment(
            self,
            goal,
            state,
            context,
            assessment,
            *,
            plan_manager: Any = None,
            context_engine: Any | None = None,
        ):
            """Generate: always new steps."""
            self._generate_count += 1
            return PlanResult(
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
                    execution_mode="parallel",
                    reasoning="more work",
                ),
                next_action="I'll take another step toward the goal.",
                goal_progress="none",
            )

        async def plan(self, goal, state, context):
            self.plan_count += 1
            return PlanResult(
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
                    execution_mode="parallel",
                    reasoning="more work",
                ),
                next_action="I'll take another step toward the goal.",
                goal_progress="none",
            )

    planner = NeverDonePlanner()
    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(
        core_agent=core_agent,
        loop_planner=planner,
        config=_make_config(max_iterations=3),
    )

    result = await loop_agent.run(
        goal="Never ending task",
        thread_id="test_thread",
        max_iterations=3,
    )

    # Should hit max iterations after 2 assess calls (iteration 3 would exceed max)
    assert planner._assess_count == 2
    assert planner._generate_count == 3  # Extra generate call when max iterations hit
    assert result.status == "continue"


@pytest.mark.asyncio
async def test_loop_agent_parallel_execution() -> None:
    """Test StrangeLoop with parallel execution mode."""

    class ParallelPlanner:
        def __init__(self) -> None:
            self.plan_count = 0
            self._assess_count = 0
            self._generate_count = 0
            self._model = MagicMock()

        async def assess_status(self, goal, state, context, *, context_engine: Any | None = None):
            """Assess-only for parallel execution."""
            self._assess_count += 1
            if self._assess_count == 1:
                return StatusAssessment(
                    status="continue",
                    goal_progress="none",
                    assessment_reasoning="Starting parallel work",
                    require_goal_completion=False,
                )
            return StatusAssessment(
                status="done",
                goal_progress="complete",
                assessment_reasoning="Parallel work complete",
                require_goal_completion=True,
            )

        async def generate_from_assessment(
            self,
            goal,
            state,
            context,
            assessment,
            *,
            plan_manager: Any = None,
            context_engine: Any | None = None,
        ):
            """Generate parallel steps."""
            self._generate_count += 1
            if self._generate_count == 1:
                return PlanResult(
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
            return PlanResult(
                status="done",
                plan_action="keep",
                next_action="I'm finished with the parallel work.",
                goal_progress="complete",
            )

        async def plan(self, goal, state, context):
            self.plan_count += 1
            if self.plan_count == 1:
                return PlanResult(
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
            return PlanResult(
                status="done",
                plan_action="keep",
                next_action="I'm finished with the parallel work.",
                goal_progress="complete",
            )

    planner = ParallelPlanner()
    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(
        core_agent=core_agent,
        loop_planner=planner,
        config=_make_config(),
    )

    result = await loop_agent.run(
        goal="Parallel task",
        thread_id="test_thread",
        max_iterations=8,
    )

    # One CoreAgent stream per parallel step in first Execute wave (3 parallel steps)
    # The synthesis phase may use planner._model directly or ledger passthrough,
    # not core_agent.astream, so we only count the 3 execution calls.
    assert core_agent.call_count == 3
    assert result.status == "done"
