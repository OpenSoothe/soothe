"""Integration tests: planner records a compacted ledger pair (A2 + C1 + D1).

`LLMPlanner.assess_status` and `LLMPlanner.generate_from_assessment` are the
two callsites that append (LoopHumanMessage, LoopAIMessage) pairs into
`state.loop_messages`. After the compaction work, the *recorded* copy must
have its `<CONTEXT_INFO>` stripped, its `<USER_QUERY>` rewritten to
`<GOAL_RECAP>`, and (for plan-assess) its dumped `assessment_reasoning`
dropped.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import soothe.core.loop.state.schemas  # noqa: F401 — break circular import
from soothe.core.loop.planning.planner import LLMPlanner
from soothe.core.loop.state.schemas import (
    LoopState,
    PlanGenerateStep,
    PlanGeneration,
    StatusAssessment,
)
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.protocols.planner import PlanContext

GOAL = "translate the README into French"

RECORDED_HUMAN_CONTENT = (
    f"<USER_QUERY>\n{GOAL}\n</USER_QUERY>\n"
    "<PRIOR_PROGRESS>\nhint=low\n</PRIOR_PROGRESS>\n"
    "<CONTEXT_INFO>\n<timestamp>2026-06-02T10:19:55Z</timestamp>\n<date>2026-06-02</date>\n</CONTEXT_INFO>"
)


def _make_human(phase: str) -> LoopHumanMessage:
    return LoopHumanMessage(
        content=RECORDED_HUMAN_CONTENT,
        thread_id="t1",
        iteration=1,
        goal_summary=GOAL[:200],
        phase=phase,
    )


@pytest.mark.asyncio
async def test_assess_status_records_compacted_human_and_dropped_reasoning() -> None:
    planner = LLMPlanner(MagicMock())
    rendered_human = _make_human("plan_assess")
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[rendered_human]
    )
    assessment = StatusAssessment(
        status="continue",
        goal_progress="low",
        assessment_reasoning="LLM said: need more evidence before deciding.",
        require_goal_completion=False,
    )
    planner._assess_status_with_response = AsyncMock(  # type: ignore[method-assign]
        return_value=(assessment, assessment)
    )

    state = LoopState(goal=GOAL, thread_id="t1", iteration=1)
    await planner.assess_status(GOAL, state, PlanContext())

    assert len(state.loop_messages) == 2
    recorded_human, recorded_ai = state.loop_messages

    # C1: volatile timestamp must be gone from the recorded human.
    assert "<CONTEXT_INFO>" not in recorded_human.content
    assert "<timestamp>" not in recorded_human.content
    # D1: <USER_QUERY> is rewritten so it doesn't anchor as a directive.
    assert "<USER_QUERY>" not in recorded_human.content
    assert "<GOAL_RECAP>" in recorded_human.content
    assert GOAL in recorded_human.content
    # PRIOR_PROGRESS is preserved (not a target of C1/D1).
    assert "<PRIOR_PROGRESS>" in recorded_human.content

    # A2: the LLM's assessment_reasoning must NOT appear in the recorded AI dump.
    assert "assessment_reasoning" not in recorded_ai.content
    assert "need more evidence" not in recorded_ai.content
    # Schema-essential fields survive so plan-generate and auditing still work.
    assert "'status':" in recorded_ai.content and "'continue'" in recorded_ai.content
    assert "'goal_progress':" in recorded_ai.content and "'low'" in recorded_ai.content
    # Phase tagging is preserved (drives projection filtering).
    assert isinstance(recorded_human, LoopHumanMessage)
    assert isinstance(recorded_ai, LoopAIMessage)
    assert recorded_human.phase == "plan_assess"
    assert recorded_ai.phase == "plan_assess"


@pytest.mark.asyncio
async def test_generate_from_assessment_records_compacted_human_preserves_ai() -> None:
    planner = LLMPlanner(MagicMock())
    rendered_human = _make_human("plan_generate")
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[rendered_human]
    )

    plan_generation = PlanGeneration(
        plan_action="new",
        type="execute_steps",
        steps=[
            PlanGenerateStep(
                id="01",
                description="Translate section 1 of the README into French",
                expected_output="French text for section 1",
            )
        ],
        execution_mode="parallel",
        reasoning="model rationale text that should stay in the AI dump",
        next_action="I'll translate section by section.",
    )
    planner._generate_plan_with_response = AsyncMock(  # type: ignore[method-assign]
        return_value=(plan_generation, plan_generation)
    )
    planner._finalize_generated_plan_result = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda result, **_: result
    )

    state = LoopState(goal=GOAL, thread_id="t1", iteration=1)
    assessment = StatusAssessment(status="continue", goal_progress="low")
    await planner.generate_from_assessment(GOAL, state, PlanContext(), assessment)

    assert len(state.loop_messages) == 2
    recorded_human, recorded_ai = state.loop_messages

    # C1 + D1 still apply to plan-generate humans.
    assert "<CONTEXT_INFO>" not in recorded_human.content
    assert "<USER_QUERY>" not in recorded_human.content
    assert "<GOAL_RECAP>" in recorded_human.content

    # A2 does NOT apply to plan-generate: the `steps` list and `reasoning`
    # are the value of the recording, so the AI dump stays verbatim.
    assert "model rationale text that should stay" in recorded_ai.content
    assert recorded_ai.phase == "plan_generate"


@pytest.mark.asyncio
async def test_recorded_humans_are_cache_stable_across_iterations() -> None:
    """Two assess calls on different iterations record identical human content
    (modulo PRIOR_PROGRESS, which is rebuilt by the envelope per iteration).

    The point of C1 is that the *recorded* human stops carrying the volatile
    timestamp, so two calls that share the same goal + PRIOR_PROGRESS produce
    byte-identical recordings — the prompt-cache prefix is preserved.
    """
    planner = LLMPlanner(MagicMock())
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[_make_human("plan_assess")]
    )
    planner._assess_status_with_response = AsyncMock(  # type: ignore[method-assign]
        return_value=(
            StatusAssessment(status="continue", goal_progress="low"),
            StatusAssessment(status="continue", goal_progress="low"),
        )
    )

    state_a = LoopState(goal=GOAL, thread_id="t1", iteration=1)
    state_b = LoopState(goal=GOAL, thread_id="t1", iteration=2)
    await planner.assess_status(GOAL, state_a, PlanContext())
    # Re-stub with a fresh human matching iter=2; same content is what we want.
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[_make_human("plan_assess")]
    )
    await planner.assess_status(GOAL, state_b, PlanContext())

    assert state_a.loop_messages[0].content == state_b.loop_messages[0].content


@pytest.mark.asyncio
async def test_assess_status_does_not_record_when_llm_fallback_yields_no_response() -> None:
    """Pre-existing contract: when `ai_response` is None, no ledger pair is written."""
    planner = LLMPlanner(MagicMock())
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[_make_human("plan_assess")]
    )
    planner._assess_status_with_response = AsyncMock(  # type: ignore[method-assign]
        return_value=(
            StatusAssessment(status="replan", goal_progress="none"),
            None,
        )
    )

    state = LoopState(goal=GOAL, thread_id="t1", iteration=1)
    await planner.assess_status(GOAL, state, PlanContext())
    assert state.loop_messages == []
