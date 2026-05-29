"""Tests for RFC-225/RFC-226 loop-continuation plan_assess paths.

Covers:
- ``build_continue_loop_bootstrap_plan`` shape + terminal_after_execute flag (RFC-226).
- ``seed_loop_ledger_from_prior_goal`` (RFC-225 unchanged behavior).
- ``_prior_goal_summaries`` filtering (RFC-226).
"""

from datetime import UTC, datetime

from soothe.core.loop.orchestrator.nodes.plan_assess import (
    _prior_goal_summaries,
    build_continue_loop_bootstrap_plan,
    seed_loop_ledger_from_prior_goal,
)
from soothe.core.loop.state.checkpoint import (
    AgentLoopCheckpoint,
    GoalExecutionRecord,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage


def _minimal_checkpoint(*, goals: list[GoalExecutionRecord]) -> AgentLoopCheckpoint:
    now = datetime.now(UTC)
    return AgentLoopCheckpoint(
        loop_id="loop-x",
        thread_ids=["tid"],
        current_thread_id="tid",
        status="idle",
        goal_history=list(goals),
        current_goal_index=-1,
        working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
        thread_health_metrics=ThreadHealthMetrics(thread_id="tid", last_updated=now),
        created_at=now,
        updated_at=now,
    )


# ── build_continue_loop_bootstrap_plan ─────────────────────────────────────


def test_build_bootstrap_plan_shape() -> None:
    pr = build_continue_loop_bootstrap_plan("user follow-up")
    assert pr.status == "continue"
    assert pr.plan_action == "new"
    assert pr.decision is not None
    assert pr.decision.type == "execute_steps"
    assert len(pr.decision.steps) == 1
    assert pr.decision.execution_mode == "parallel"
    # RFC-226 default: not terminal
    assert pr.terminal_after_execute is False


def test_build_bootstrap_plan_terminal_flag_propagates() -> None:
    pr = build_continue_loop_bootstrap_plan(
        "translate the result to chinese",
        terminal_after_execute=True,
        reasoning="Pure translation; no new tools needed.",
        goal_progress="low",
    )
    assert pr.terminal_after_execute is True
    assert pr.assessment_reasoning == "Pure translation; no new tools needed."
    assert pr.goal_progress == "low"
    # Step description embeds the actual goal text.
    assert "translate the result to chinese" in pr.decision.steps[0].description


# ── seed_loop_ledger_from_prior_goal (RFC-225) ─────────────────────────────


def test_seed_continuation_copies_prior_ledger() -> None:
    now = datetime.now(UTC)
    prev = GoalExecutionRecord(
        goal_id="g0",
        goal_text="count files",
        thread_id="tid",
        status="completed",
        loop_messages=[
            LoopHumanMessage(content="h", thread_id="tid", phase="execute_step"),
            LoopAIMessage(content="found 3", thread_id="tid", phase="execute_wave"),
        ],
        started_at=now,
        completed_at=now,
    )
    new_g = GoalExecutionRecord(
        goal_id="g1",
        goal_text="translate",
        thread_id="tid",
        loop_messages=[],
        started_at=now,
    )
    ckpt = _minimal_checkpoint(goals=[prev, new_g])
    seed_loop_ledger_from_prior_goal(ckpt, new_g, "tid")
    assert len(new_g.loop_messages) == 2
    assert new_g.loop_messages[0].content == "h"
    assert new_g.loop_messages[1].content == "found 3"
    assert new_g.loop_messages[0] is not prev.loop_messages[0]


def test_seed_continuation_falls_back_to_goal_completion() -> None:
    now = datetime.now(UTC)
    prev = GoalExecutionRecord(
        goal_id="g0",
        goal_text="count files",
        thread_id="tid",
        status="completed",
        loop_messages=[],
        goal_completion="There are 3 README files.",
        started_at=now,
        completed_at=now,
    )
    new_g = GoalExecutionRecord(
        goal_id="g1",
        goal_text="translate",
        thread_id="tid",
        loop_messages=[],
        started_at=now,
    )
    ckpt = _minimal_checkpoint(goals=[prev, new_g])
    seed_loop_ledger_from_prior_goal(ckpt, new_g, "tid")
    assert len(new_g.loop_messages) == 2
    assert "README" in new_g.loop_messages[1].content


# ── _prior_goal_summaries (RFC-226) ────────────────────────────────────────


def test_prior_goal_summaries_excludes_active_and_non_completed() -> None:
    now = datetime.now(UTC)
    g0_completed = GoalExecutionRecord(
        goal_id="g0",
        goal_text="count files",
        thread_id="tid",
        status="completed",
        goal_completion="There are 12 file types.",
        loop_messages=[],
        started_at=now,
        completed_at=now,
    )
    g1_failed = GoalExecutionRecord(
        goal_id="g1",
        goal_text="email bob",
        thread_id="tid",
        status="failed",
        loop_messages=[],
        started_at=now,
    )
    g2_active = GoalExecutionRecord(
        goal_id="g2",
        goal_text="translate the result",
        thread_id="tid",
        status="running",
        loop_messages=[],
        started_at=now,
    )
    ckpt = _minimal_checkpoint(goals=[g0_completed, g1_failed, g2_active])

    summaries = _prior_goal_summaries(ckpt)

    # Active goal (last) is always excluded; failed goal is filtered out.
    assert len(summaries) == 1
    s = summaries[0]
    assert s["goal_id"] == "g0"
    assert s["goal_text"] == "count files"
    assert s["completion"] == "There are 12 file types."
    assert s["step_count"] == 0
    assert s["current_plan_action"] == ""


def test_prior_goal_summaries_empty_when_only_active_goal() -> None:
    now = datetime.now(UTC)
    g0_active = GoalExecutionRecord(
        goal_id="g0",
        goal_text="count files",
        thread_id="tid",
        status="running",
        loop_messages=[],
        started_at=now,
    )
    ckpt = _minimal_checkpoint(goals=[g0_active])
    assert _prior_goal_summaries(ckpt) == []
