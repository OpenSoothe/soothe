"""Unit tests for loop-continuation context helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from soothe.foundation.sloop.engine.continuation_context import (
    build_continue_bootstrap_step_briefs,
    build_prior_goal_completion_block,
    ledger_goal_completion_text,
    resolve_prior_goal_completion,
)
from soothe.foundation.sloop.state.checkpoint import (
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.foundation.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.foundation.sloop.state.schemas import LoopState, StepResult
from soothe.foundation.sloop.utils.messages import LoopAIMessage


def _make_checkpoint(*records: GoalIndexEntry) -> StrangeLoopCheckpoint:
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


def test_ledger_goal_completion_text_returns_latest_ai_body() -> None:
    ledger = [
        LoopAIMessage(content="old synthesis", phase="goal_completion", thread_id="t"),
        LoopAIMessage(content="final synthesis report", phase="goal_completion", thread_id="t"),
    ]
    assert ledger_goal_completion_text(ledger) == "final synthesis report"


def test_resolve_prior_goal_completion_uses_ledger() -> None:
    prior = GoalIndexEntry(
        goal_id="g0",
        thread_id="tid",
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    checkpoint = _make_checkpoint(prior)
    ledger = [
        LoopAIMessage(content="Ledger completion body", phase="goal_completion", thread_id="t"),
    ]
    resolved = resolve_prior_goal_completion(
        loop_messages=ledger,
        checkpoint=checkpoint,
        prior_goal_text="analyze trace",
    )
    assert resolved == "Ledger completion body"


def test_build_prior_goal_completion_block_truncates() -> None:
    body = "x" * 20_000
    ledger = [LoopAIMessage(content=body, phase="goal_completion", thread_id="t")]
    block = build_prior_goal_completion_block(ledger, max_chars=100)
    assert len(block) <= 100
    assert block.endswith("…")


def test_build_prior_goal_completion_block_unlimited_when_max_chars_zero() -> None:
    body = "y" * 500
    ledger = [LoopAIMessage(content=body, phase="goal_completion", thread_id="t")]
    assert build_prior_goal_completion_block(ledger, max_chars=0) == body


def test_polish_continuation_assess_reasoning_collapses_and_truncates() -> None:
    from soothe.foundation.sloop.engine.continuation_context import (
        polish_continuation_assess_reasoning,
    )

    long_reason = "I " + "need " * 80 + "a full planner."
    polished = polish_continuation_assess_reasoning(long_reason, max_chars=240)
    assert len(polished) <= 240
    assert "\n" not in polished


def test_format_prior_goal_completion_section_matches_plan_generate_label() -> None:
    from soothe.foundation.sloop.engine.continuation_context import (
        format_prior_goal_completion_section,
    )

    section = format_prior_goal_completion_section("Full report body.")
    assert section.startswith("PRIOR GOAL COMPLETION:\n")
    assert "Full report body." in section


def test_is_continuation_first_plan_requires_no_step_results() -> None:
    from soothe.foundation.sloop.engine.continuation_context import is_continuation_first_plan

    state = LoopState(goal="g", thread_id="t", iteration=0, continue_loop=True)
    assert is_continuation_first_plan(state) is True

    state.step_results.append(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    assert is_continuation_first_plan(state) is False


def test_build_prior_goal_summaries_uses_ce_action_history() -> None:
    from soothe.foundation.sloop.engine.continuation_context import build_prior_goal_summaries

    prior = GoalIndexEntry(
        goal_id="g0",
        thread_id="tid",
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    checkpoint = _make_checkpoint(prior)

    goal = MagicMock()
    goal.id = "g0"
    goal.description = "analyze trace"
    goal.status = "completed"
    goal.steps.nodes.values.return_value = []
    goal.action_history = ["CE completion body."]

    ce = MagicMock()
    ce.get_all_goals.return_value = [goal]

    summaries = build_prior_goal_summaries(
        ce=ce,
        checkpoint=checkpoint,
        exclude_goal_id="g1",
    )
    assert len(summaries) == 1
    assert summaries[0]["completion"] == "CE completion body."


def test_continue_keyword_bootstrap_step_briefs() -> None:
    briefs = build_continue_bootstrap_step_briefs(user_goal="continue")
    assert briefs.description == "Continue prior goal completion recommendations"
    assert "PRIOR GOAL COMPLETION" in briefs.full_description
    assert "recommended next actions" in briefs.full_description.lower()


def test_follow_up_bootstrap_step_briefs_split_description_and_full() -> None:
    briefs = build_continue_bootstrap_step_briefs(user_goal="translate the result to chinese")
    assert briefs.description == "translate the result to chinese"
    assert "translate the result to chinese" in briefs.full_description
    assert "PRIOR GOAL COMPLETION" in briefs.full_description
    assert briefs.description != briefs.full_description
