"""Tests for the ``goal_interrupted`` ledger marker writer (RFC-214 carry-forward).

Covers ``append_goal_interrupted_ledger_pair``: the marker is only written when
the interrupted goal produced ``execute_step`` evidence, the AI body is a
deterministic digest (no LLM) that references that evidence, and the
``action_history`` fallback is populated for continuation-assess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.sloop.engine.goal_interrupt_record import (
    append_goal_interrupted_ledger_pair,
)
from soothe.foundation.sloop.state.schemas import LoopState, PriorProgressDigest, WaveStepProgress
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


@dataclass
class _FakeCtx:
    """Minimal stand-in for ``LoopRuntimeContext`` used by the writer."""

    loop_state: LoopState
    ce: Any
    ce_goal_id: str | None = None


def _state_with_execute_rows(goal: str = "find the bug") -> LoopState:
    state = LoopState(goal=goal, thread_id="t1", iteration=2)
    # The CE-backed loop_messages property is read-only; inject via a Bind-free
    # state by writing directly to the local cache the property falls back to.
    state._loop_messages_cache = [  # type: ignore[attr-defined]
        LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t1"),
        LoopAIMessage(
            content="Found the bug in parser.py line 42", phase="execute_step", thread_id="t1"
        ),
        LoopHumanMessage(content="exec h2", phase="execute_step", thread_id="t1"),
        LoopAIMessage(
            content="Wrote a failing test reproducing it", phase="execute_step", thread_id="t1"
        ),
    ]
    return state


@pytest.mark.asyncio
async def test_marker_written_with_execute_evidence() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("find the bug")
    state = _state_with_execute_rows()
    ctx = _FakeCtx(loop_state=state, ce=ce, ce_goal_id=goal.id)

    await append_goal_interrupted_ledger_pair(ctx, reason="user_cancelled")

    ledger = await ce.get_ledger(phases=["goal_interrupted"])
    # Human + AI pair.
    assert len(ledger) == 2
    ai = [m for m in ledger if str(getattr(m, "content", "")).strip()][-1]
    body = str(getattr(ai, "content", ""))
    assert "user_cancelled" in body
    # Digest references the goal's execute evidence (carry-forward signal).
    assert "parser.py line 42" in body or "failing test" in body
    # action_history fallback populated for continuation-assess.
    fetched = await ce.get_goal(goal.id)
    assert fetched.action_history and "user_cancelled" in fetched.action_history[-1]


@pytest.mark.asyncio
async def test_marker_skipped_when_no_execute_evidence() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("empty goal")
    state = LoopState(goal="empty goal", thread_id="t1", iteration=0)
    state._loop_messages_cache = []  # type: ignore[attr-defined]
    ctx = _FakeCtx(loop_state=state, ce=ce, ce_goal_id=goal.id)

    await append_goal_interrupted_ledger_pair(ctx, reason="fatal_error", detail="boom")

    ledger = await ce.get_ledger(phases=["goal_interrupted"])
    assert ledger == []


@pytest.mark.asyncio
async def test_marker_uses_prior_progress_step_summaries() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("multi-step goal")
    state = _state_with_execute_rows()
    state.prior_progress = PriorProgressDigest(
        iteration=2,
        wave_index=1,
        steps_completed=1,
        steps_failed=0,
        step_summaries=[
            WaveStepProgress(
                step_id="s1",
                description="locate the parser bug",
                status="completed",
                outcome_preview="found at line 42",
            ),
            WaveStepProgress(
                step_id="s2",
                description="write repro test",
                status="failed",
                outcome_preview="test crashed",
            ),
        ],
        derived_progress_hint="medium",
    )
    ctx = _FakeCtx(loop_state=state, ce=ce, ce_goal_id=goal.id)

    await append_goal_interrupted_ledger_pair(ctx, reason="max_iterations")

    ledger = await ce.get_ledger(phases=["goal_interrupted"])
    assert len(ledger) == 2
    ai_body = str(getattr(ledger[-1], "content", ""))
    # Step summaries from prior_progress appear in the digest.
    assert "locate the parser bug" in ai_body
    assert "write repro test" in ai_body
    assert "max_iterations" in ai_body


@pytest.mark.asyncio
async def test_marker_does_not_set_goal_status() -> None:
    """The writer only adds the ledger marker; status is the caller's job."""
    ce = ContextEngine()
    goal = await ce.create_goal("status check")
    state = _state_with_execute_rows()
    ctx = _FakeCtx(loop_state=state, ce=ce, ce_goal_id=goal.id)

    await append_goal_interrupted_ledger_pair(ctx, reason="rate_limited")

    fetched = await ce.get_goal(goal.id)
    # Writer must NOT mutate status — caller's terminal path sets cancelled/failed.
    assert fetched.status != "interrupted"
    # CE default after create_goal is "pending" (not yet claimed/active).
    assert fetched.status == "pending"
