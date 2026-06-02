"""Builder threads state.prior_progress to envelope for both plan phases (RFC-227)."""

from __future__ import annotations

from soothe.core.loop.state.schemas import LoopState, PriorProgressDigest, ToolCallHead
from soothe.core.prompts import PromptBuilder
from soothe.protocols.planner import PlanContext


def _digest(iteration: int = 1) -> PriorProgressDigest:
    return PriorProgressDigest(
        iteration=iteration,
        wave_index=0,
        steps_completed=1,
        steps_failed=0,
        tool_calls=[ToolCallHead(name="run_command", head="hello")],
        evidence_excerpts=["found marker 42 in output"],
        derived_progress_hint="high",
    )


def test_assess_phase_includes_prior_progress_when_present() -> None:
    state = LoopState(goal="g", thread_id="t1", iteration=2, prior_progress=_digest(iteration=1))
    ctx = PlanContext()
    msgs = PromptBuilder().build_plan_messages("g", state, ctx, plan_phase="assess")
    assess_human = msgs[-1].content
    assert "<PRIOR_PROGRESS>" in assess_human
    assert "hint=high" in assess_human
    assert "found marker 42" in assess_human


def test_generate_phase_includes_prior_progress_when_present() -> None:
    state = LoopState(goal="g", thread_id="t1", iteration=2, prior_progress=_digest(iteration=1))
    ctx = PlanContext()
    msgs = PromptBuilder().build_plan_messages("g", state, ctx, plan_phase="generate")
    gen_human = msgs[-1].content
    assert "<PRIOR_PROGRESS>" in gen_human
    assert "found marker 42" in gen_human


def test_both_phases_omit_block_when_prior_progress_absent() -> None:
    state = LoopState(goal="g", thread_id="t1", iteration=0)  # default prior_progress=None
    ctx = PlanContext()
    builder = PromptBuilder()
    for phase in ("assess", "generate"):
        msgs = builder.build_plan_messages("g", state, ctx, plan_phase=phase)
        assert "<PRIOR_PROGRESS>" not in msgs[-1].content


def test_stale_digest_omitted_from_both_phases() -> None:
    # Current iteration 5, digest from iteration 1 → delta 4 → stale.
    state = LoopState(goal="g", thread_id="t1", iteration=5, prior_progress=_digest(iteration=1))
    ctx = PlanContext()
    builder = PromptBuilder()
    for phase in ("assess", "generate"):
        msgs = builder.build_plan_messages("g", state, ctx, plan_phase=phase)
        assert "<PRIOR_PROGRESS>" not in msgs[-1].content


def test_response_language_hint_in_plan_system_prompt_not_user_envelope() -> None:
    """Language hint lives in the plan-phase system prompt (cache-stable) with
    an uppercase tag. The per-turn user envelope must NOT carry it."""
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    ctx = PlanContext()
    builder = PromptBuilder()
    for phase in ("assess", "generate"):
        msgs = builder.build_plan_messages("g", state, ctx, plan_phase=phase)
        system_content = msgs[0].content
        user_content = msgs[-1].content
        assert "<RESPONSE_LANGUAGE_HINT>" in system_content
        assert "same natural language as the user's goal" in system_content
        assert "<response_language_hint>" not in system_content
        assert "response_language_hint" not in user_content.lower()
        assert "RESPONSE_LANGUAGE_HINT" not in user_content
