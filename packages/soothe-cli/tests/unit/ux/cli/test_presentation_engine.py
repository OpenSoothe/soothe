"""Tests for unified presentation engine policies."""

from __future__ import annotations

from soothe_sdk.core.verbosity import VerbosityTier, should_show

from soothe_cli.shared.presentation_engine import PresentationEngine


def test_reason_dedup_within_window() -> None:
    engine = PresentationEngine()
    assert engine.should_emit_reason(
        content="Searching README files (80% sure)", step_id="1", now_s=10.0
    )
    assert not engine.should_emit_reason(
        content="Searching README files (90% sure)", step_id="1", now_s=12.0
    )


def test_reason_rate_limit_by_step() -> None:
    engine = PresentationEngine()
    assert engine.should_emit_reason(content="Counting files", step_id="step-a", now_s=10.0)
    assert not engine.should_emit_reason(
        content="Counting files in full tree", step_id="step-a", now_s=12.0
    )
    assert engine.should_emit_reason(
        content="Counting files in full tree", step_id="step-a", now_s=16.0
    )


def test_tool_result_structured_payload_summary() -> None:
    engine = PresentationEngine()
    result = engine.summarize_tool_result("['a', 'b', 'c']")
    assert "structured payload" in result


def test_final_answer_lock_and_reset_turn() -> None:
    engine = PresentationEngine()
    assert not engine.final_answer_locked
    engine.mark_final_answer_locked()
    assert engine.final_answer_locked
    engine.reset_turn()
    assert not engine.final_answer_locked


def test_tier_visible_matches_should_show() -> None:
    engine = PresentationEngine()
    for verbosity in ("quiet", "normal", "detailed", "debug"):
        for tier in (
            VerbosityTier.QUIET,
            VerbosityTier.NORMAL,
            VerbosityTier.DETAILED,
            VerbosityTier.DEBUG,
        ):
            assert engine.tier_visible(tier, verbosity) == should_show(tier, verbosity)
