"""End-to-end planner-emitted ask_user → policy.answer → resume (IG-462).

Drives ``StrangeLoop.run_with_progress`` with a stub planner that emits a
``kind="ask_user"`` step on the first iteration and a stub
``ClarificationPolicy`` that returns canned answers. Confirms the loop
records a synthesized ``StepResult`` for the ask_user step and the next
planning iteration sees the answered question as completed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.config.models import (
    ExecutePromptLedgerConfig,
    PlanPromptLedgerConfig,
)
from soothe.foundation.sloop import StrangeLoop
from soothe.foundation.sloop.clarification import (
    ClarificationAnswer,
    ClarificationRequest,
)
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    PlanResult,
    StatusAssessment,
    StepAction,
)
from soothe.protocols.planner import PlanContext


class _StubPolicy:
    """Returns canned answers; satisfies ``ClarificationPolicy`` structurally."""

    def __init__(self, answers: tuple[str, ...] = ("json",)) -> None:
        self._answers = answers
        self.call_count = 0
        self.received: list[ClarificationRequest] = []

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        self.call_count += 1
        self.received.append(request)
        return ClarificationAnswer(
            answers=self._answers,
            source="veritas",
            confidence=0.9,
            defer=False,
        )


class _AskUserPlanner:
    """Iteration 0 emits an ``ask_user`` step; iteration 1 declares done."""

    def __init__(self) -> None:
        self._assess_count = 0
        self._generate_count = 0
        self._model = MagicMock()

    async def assess_status(
        self,
        goal: str,
        state: Any,
        context: PlanContext,
        *,
        context_engine: Any | None = None,
        **_kwargs: Any,
    ) -> StatusAssessment:
        self._assess_count += 1
        if self._assess_count == 1:
            return StatusAssessment(
                status="continue",
                goal_progress="none",
                assessment_reasoning="need user input",
                require_goal_completion=False,
            )
        return StatusAssessment(
            status="done",
            goal_progress="complete",
            assessment_reasoning="answer in hand",
            require_goal_completion=True,
        )

    async def generate_from_assessment(
        self,
        goal: str,
        state: Any,
        context: PlanContext,
        assessment: Any,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
        **_kwargs: Any,
    ) -> PlanResult:
        self._generate_count += 1
        if assessment.status == "done":
            return PlanResult(
                status="done",
                plan_action="keep",
                next_action="goal achieved",
                goal_progress=assessment.goal_progress,
            )
        # First wave: a single ask_user step.
        return PlanResult(
            status="continue",
            plan_action="new",
            decision=AgentDecision(
                type="execute_steps",
                steps=[
                    StepAction(
                        id="ASK-01",
                        description="ask about output format",
                        kind="ask_user",
                        questions=["Which output format do you want?"],
                    )
                ],
                execution_mode="parallel",
                reasoning="need user input before we can proceed",
            ),
            next_action="I need to ask the user before proceeding.",
        )

    async def analyze_plan_gap(
        self, goal: str, state: Any, context: PlanContext, *, context_engine: Any | None = None
    ) -> Any:
        """Read-only gap analysis (IG-557); stub returns no gaps."""
        return None

    async def plan(self, goal: str, state: Any, context: PlanContext) -> PlanResult:
        # Legacy unified entry; route through the split methods.
        assessment = await self.assess_status(goal, state, context)
        return await self.generate_from_assessment(goal, state, context, assessment)


class _MockCoreAgent:
    def __init__(self) -> None:
        self.call_count = 0
        self.graph = MagicMock()
        self.graph.checkpointer = None

    @property
    def checkpointer(self) -> None:
        """Mock checkpointer property (always None for tests)."""
        return self.graph.checkpointer

    def astream(self, user_input: str, config: dict, **kwargs: Any):
        async def _stream():
            self.call_count += 1
            yield {"messages": [{"content": "n/a"}]}

        return _stream()

    def execution_astream(self, user_input: str, config: dict, **kwargs: Any):
        """Return an async iterator like ``CoreAgent.execution_astream`` (ephemeral twin graph)."""

        async def _stream():
            self.call_count += 1
            yield {"messages": [{"content": "n/a"}]}

        return _stream()


def _make_config(max_iterations: int = 4) -> Any:
    cfg = MagicMock()
    cfg.subagents = {}
    cfg.agent = MagicMock()
    al = cfg.agent.loop
    al.max_iterations = max_iterations
    al.max_subagent_tasks_per_wave = 16
    al.context_window_limit = 128000
    al.working_memory.enabled = False
    al.working_memory.max_inline_chars = 4000
    al.working_memory.max_entry_chars_before_spill = 500
    # Concurrency config (LoopConcurrencyConfig)
    al.concurrency.max_parallel_steps = 1
    al.concurrency.max_parallel_goals = 1
    al.concurrency.max_parallel_tools = 5
    al.concurrency.max_parallel_subagents = 4
    # Async checkpoint worker config (LoopCheckpointAsyncConfig). Must be real
    # floats — a MagicMock here makes ``asyncio.sleep(flush_interval)`` raise
    # TypeError on every tick, and the worker's ``except Exception`` swallows
    # it with no sleep, producing a ~100% CPU busy-loop that hangs the test.
    al.concurrency.checkpoint.flush_interval = 5.0
    al.concurrency.checkpoint.close_timeout_seconds = 5.0
    al.concurrency.checkpoint.durable_flush_timeout = 5.0
    # Execute/plan prompt-ledger config must be real typed instances — a
    # MagicMock here makes execute-step projection numeric comparisons raise
    # TypeError. Typed defaults satisfy both strange_loop's attribute access
    # and plan_ledger_projection's comparisons.
    al.execute_prompt_ledger = ExecutePromptLedgerConfig()
    al.plan_prompt_ledger = PlanPromptLedgerConfig()
    # Thread switch policy: set on loop config directly, not on limits
    # _get_rate_limit_threshold looks at loop_cfg.thread_switch_policy
    al.thread_switch_policy = MagicMock()
    al.thread_switch_policy.consecutive_rate_limit_threshold = 999
    al.goal_completion_mode = "llm_only"
    al.report_output.synthesis_max_chars = 10000
    al.report_output.synthesis_include_full_outputs = True
    al.report_output.output_summary_max_chars = 1500
    al.synthesis_model = None
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
async def test_planner_ask_user_round_trip_records_answer_as_step_result() -> None:
    planner = _AskUserPlanner()
    policy = _StubPolicy(answers=("json",))
    core_agent = _MockCoreAgent()
    loop_agent = StrangeLoop(core_agent=core_agent, loop_planner=planner, config=_make_config())

    events: list[tuple[str, Any]] = []
    async for evt in loop_agent.run_with_progress(
        goal="convert docs to a known format",
        thread_id="thr-clarif",
        max_iterations=4,
        clarification_policy=policy,
    ):
        events.append(evt)

    # The policy was consulted (multiple times due to split graph flow).
    assert policy.call_count >= 1
    asked = policy.received[0]
    assert asked.questions == ("Which output format do you want?",)
    assert asked.origin_node == "execute"
    assert asked.origin_interrupt_id.startswith("planner-ask:")

    # Plan scoping prepends a 3-char uppercase letter prefix to the planner-supplied id.
    step_completed = [
        e for e in events if e[0] == "step_completed" and e[1].get("step_id", "").endswith("ASK-01")
    ]
    assert len(step_completed) >= 1  # May emit multiple due to split graph flow
    assert step_completed[0][1]["success"] is True

    # The loop reached `done` and emitted a `completed` event with the goal
    # marked complete.
    completed = [e for e in events if e[0] == "completed"]
    assert completed, "loop did not emit a completed event"

    # CoreAgent.astream was NOT invoked for the ask_user step (Branch 2 short-circuit).
    # It might have been invoked for goal-completion synthesis; just confirm it
    # was not called *more* than once (i.e. no extra invocation for the ask_user step).
    assert core_agent.call_count <= 1
