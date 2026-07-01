"""Unit tests for loop-continuation context helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from soothe.foundation.sloop.engine.continuation_context import (
    build_continue_bootstrap_step_briefs,
    build_continue_bootstrap_step_description,
    build_prior_goal_completion_block,
    ledger_goal_completion_text,
    resolve_prior_goal_completion,
)
from soothe.foundation.sloop.state.checkpoint import (
    GoalExecutionRecord,
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.foundation.sloop.utils.messages import LoopAIMessage


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


def test_ledger_goal_completion_text_returns_latest_ai_body() -> None:
    ledger = [
        LoopAIMessage(content="old synthesis", phase="goal_completion", thread_id="t"),
        LoopAIMessage(content="final synthesis report", phase="goal_completion", thread_id="t"),
    ]
    assert ledger_goal_completion_text(ledger) == "final synthesis report"


def test_resolve_prior_goal_completion_prefers_checkpoint_match() -> None:
    prior = GoalExecutionRecord(
        goal_id="g0",
        goal_text="analyze trace",
        thread_id="tid",
        status="completed",
        goal_completion="Checkpoint completion body.",
        loop_messages=[],
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
    assert resolved == "Checkpoint completion body."


def test_build_prior_goal_completion_block_truncates() -> None:
    body = "x" * 20_000
    ledger = [LoopAIMessage(content=body, phase="goal_completion", thread_id="t")]
    block = build_prior_goal_completion_block(ledger, max_chars=100)
    assert len(block) <= 100
    assert block.endswith("…")


def test_continue_keyword_bootstrap_step_briefs() -> None:
    briefs = build_continue_bootstrap_step_briefs(user_goal="continue")
    assert briefs.description == "Continue prior goal completion recommendations"
    assert "PRIOR GOAL COMPLETION" in briefs.full_description
    assert "recommended next actions" in briefs.full_description.lower()
    assert (
        build_continue_bootstrap_step_description(user_goal="continue") == briefs.full_description
    )


def test_follow_up_bootstrap_step_briefs_split_description_and_full() -> None:
    briefs = build_continue_bootstrap_step_briefs(user_goal="translate the result to chinese")
    assert briefs.description == "translate the result to chinese"
    assert "translate the result to chinese" in briefs.full_description
    assert "PRIOR GOAL COMPLETION" in briefs.full_description
    assert briefs.description != briefs.full_description
