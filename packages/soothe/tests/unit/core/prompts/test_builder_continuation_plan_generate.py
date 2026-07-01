"""Continuation plan-generate uses prior goal completion, not step ledger."""

from __future__ import annotations

from datetime import UTC, datetime

from soothe.foundation.sloop.prompts import PromptBuilder
from soothe.foundation.sloop.state.checkpoint import (
    GoalExecutionRecord,
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.foundation.sloop.state.schemas import LoopState, StepResult
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.protocols.planner import PlanContext


def _make_checkpoint(*records: GoalExecutionRecord) -> StrangeLoopCheckpoint:
    now = datetime.now(UTC)
    return StrangeLoopCheckpoint(
        loop_id="loop-x",
        thread_ids=["tid"],
        current_thread_id="tid",
        status="idle",
        goal_history=list(records),
        current_goal_index=-1,
        working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
        thread_health_metrics=ThreadHealthMetrics(thread_id="tid", last_updated=now),
        created_at=now,
        updated_at=now,
    )


def _continuation_state(*, iteration: int = 0) -> LoopState:
    return LoopState(
        goal="implement recommended fixes",
        thread_id="tid",
        iteration=iteration,
        continue_loop=True,
        loop_messages=[
            LoopHumanMessage(content="prior execute human", phase="execute_step", thread_id="tid"),
            LoopAIMessage(content="prior execute ai", phase="execute_step", thread_id="tid"),
            LoopAIMessage(
                content="ledger-only completion", phase="goal_completion", thread_id="tid"
            ),
        ],
    )


def test_continuation_plan_generate_skips_ledger_and_uses_checkpoint_completion() -> None:
    prior = GoalExecutionRecord(
        goal_id="g0",
        goal_text="analyze trace",
        thread_id="tid",
        status="completed",
        goal_completion="Checkpoint completion body with recommendations.",
        loop_messages=[],
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    checkpoint = _make_checkpoint(prior)
    state = _continuation_state()

    msgs = PromptBuilder().build_plan_messages(
        state.goal,
        state,
        PlanContext(),
        plan_phase="generate",
        checkpoint=checkpoint,
        exclude_goal_id="g1",
    )

    assert len(msgs) == 2
    human = msgs[-1].content
    assert "PRIOR GOAL COMPLETION:" in human
    assert "Checkpoint completion body with recommendations." in human
    assert "ledger-only completion" not in human
    assert "prior execute human" not in human


def test_non_continuation_plan_generate_still_includes_ledger() -> None:
    state = LoopState(
        goal="read readme",
        thread_id="tid",
        iteration=0,
        continue_loop=False,
        loop_messages=[
            LoopHumanMessage(content="execute human", phase="execute_step", thread_id="tid"),
            LoopAIMessage(content="execute ai", phase="execute_step", thread_id="tid"),
        ],
    )

    msgs = PromptBuilder().build_plan_messages(
        state.goal,
        state,
        PlanContext(),
        plan_phase="generate",
    )

    assert len(msgs) == 4
    assert "PRIOR GOAL COMPLETION:" not in msgs[-1].content
    contents = " ".join(str(getattr(m, "content", "")) for m in msgs)
    assert "execute human" in contents


def test_continuation_replan_includes_ledger_after_execution() -> None:
    state = _continuation_state(iteration=1)
    state.step_results.append(
        StepResult(step_id="01", success=True, duration_ms=1, thread_id="tid")
    )

    msgs = PromptBuilder().build_plan_messages(
        state.goal,
        state,
        PlanContext(),
        plan_phase="generate",
    )

    assert len(msgs) == 5
    assert "prior execute human" in " ".join(str(getattr(m, "content", "")) for m in msgs)
