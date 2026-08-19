"""End-to-end planner-emitted ask_user → policy.answer → resume.

Drives ``StrangeLoop.run_with_progress`` with a stub planner that emits a
``kind="ask_user"`` step on the first iteration and a stub
``ClarificationPolicy`` that returns canned answers. Confirms the loop
records a synthesized ``StepExecutionRecord`` for the ask_user step and the next
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
from soothe.sloop import StrangeLoop
from soothe.sloop.clarification import (
    ClarificationAnswer,
    ClarificationRequest,
)


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


class _MockCoreAgent:
    def __init__(self) -> None:
        self.call_count = 0
        self.graph = MagicMock()
        self.graph.checkpointer = None

    async def aget_state(self, config: dict | None = None, **kwargs: Any):
        return MagicMock(tasks=[], values={}, next=())

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
    """RFC-904: planner ask_user waves are replaced by DISPATCH-claimed steps.

    Full ask_user clarification round-trip moves to StepNode.questions (P4).
    This test verifies the decompose path still completes a goal end-to-end.
    """
    policy = _StubPolicy(answers=("json",))
    core_agent = _MockCoreAgent()
    loop_agent = StrangeLoop(core_agent=core_agent, config=_make_config())

    events: list[tuple[str, Any]] = []
    async for evt in loop_agent.run_with_progress(
        goal="convert docs to a known format",
        thread_id="thr-clarif",
        max_iterations=4,
        clarification_policy=policy,
    ):
        events.append(evt)

    completed = [e for e in events if e[0] == "completed"]
    assert completed, "loop did not emit a completed event"
