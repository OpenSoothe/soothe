"""Unit tests for LLM-structured Eval decision (RFC-905 path B)."""

from __future__ import annotations

import pytest

from soothe.sloop.eval.eval_decision import decide_eval_required
from soothe.sloop.intention.models import IntakeLabel


@pytest.mark.asyncio
async def test_minimal_short_circuits_without_llm() -> None:
    """MINIMAL tasks never call the LLM — short-circuit to should_run_eval=False."""
    decision = await decide_eval_required(
        fast_model=object(),  # would crash if called; proves it isn't
        user_goal="trivial question",
        step_history=[],
        intake_label=IntakeLabel.MINIMAL,
    )
    assert decision.should_run_eval is False


@pytest.mark.asyncio
async def test_no_fast_model_fails_safe_to_run_eval() -> None:
    """When no fast model is available, fail-safe: require Eval."""
    decision = await decide_eval_required(
        fast_model=None,
        user_goal="do work",
        step_history=[],
        intake_label=IntakeLabel.SIMPLE,
    )
    assert decision.should_run_eval is True


@pytest.mark.asyncio
async def test_simple_with_no_fast_model_fails_safe() -> None:
    """SIMPLE + no model → should_run_eval=True (fail-safe, not silent skip)."""
    decision = await decide_eval_required(
        fast_model=None,
        user_goal="build the thing",
        step_history=[],
        intake_label=IntakeLabel.SIMPLE,
    )
    assert decision.should_run_eval is True
    assert "no fast model" in decision.reasoning.lower()
