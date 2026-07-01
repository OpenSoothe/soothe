"""Tests for prior-progress vs LLM disagreement telemetry (RFC-227)."""

from __future__ import annotations

import logging

from soothe.foundation.sloop.orchestrator.nodes.plan_assess import (
    _log_prior_progress_disagreement,
)
from soothe.foundation.sloop.state.schemas import (
    LoopState,
    PriorProgressDigest,
    StatusAssessment,
    ToolCallHead,
)


def _state_with_hint(hint: str, iteration: int = 1) -> LoopState:
    digest = PriorProgressDigest(
        iteration=iteration,
        wave_index=0,
        steps_completed=1,
        tool_calls=[ToolCallHead(name="run_command", head="x")],
        evidence_excerpts=["found 1"],
        derived_progress_hint=hint,  # type: ignore[arg-type]
    )
    return LoopState(goal="g", thread_id="t1", iteration=iteration, prior_progress=digest)


def _assess(progress: str) -> StatusAssessment:
    return StatusAssessment(
        status="continue",
        goal_progress=progress,  # type: ignore[arg-type]
        assessment_reasoning="test",
    )


def test_log_emitted_when_buckets_differ_by_more_than_one(caplog) -> None:
    caplog.set_level(logging.INFO, logger="soothe.foundation.sloop.orchestrator.nodes.plan_assess")
    state = _state_with_hint("low")
    _log_prior_progress_disagreement(state, _assess("high"))
    assert any("hint=low vs LLM goal_progress=high" in r.message for r in caplog.records), [
        r.message for r in caplog.records
    ]


def test_no_log_when_buckets_equal(caplog) -> None:
    caplog.set_level(logging.INFO, logger="soothe.foundation.sloop.orchestrator.nodes.plan_assess")
    state = _state_with_hint("medium")
    _log_prior_progress_disagreement(state, _assess("medium"))
    assert not [r for r in caplog.records if "hint=" in r.message]


def test_no_log_when_off_by_one_bucket(caplog) -> None:
    caplog.set_level(logging.INFO, logger="soothe.foundation.sloop.orchestrator.nodes.plan_assess")
    state = _state_with_hint("medium")
    _log_prior_progress_disagreement(state, _assess("high"))
    _log_prior_progress_disagreement(state, _assess("low"))
    assert not [r for r in caplog.records if "hint=" in r.message]


def test_log_emitted_when_llm_says_complete_but_hint_low(caplog) -> None:
    caplog.set_level(logging.INFO, logger="soothe.foundation.sloop.orchestrator.nodes.plan_assess")
    state = _state_with_hint("low")
    _log_prior_progress_disagreement(state, _assess("complete"))
    assert any("hint=low vs LLM goal_progress=complete" in r.message for r in caplog.records)


def test_no_log_when_no_prior_progress(caplog) -> None:
    caplog.set_level(logging.INFO, logger="soothe.foundation.sloop.orchestrator.nodes.plan_assess")
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    _log_prior_progress_disagreement(state, _assess("high"))
    assert not [r for r in caplog.records if "hint=" in r.message]
