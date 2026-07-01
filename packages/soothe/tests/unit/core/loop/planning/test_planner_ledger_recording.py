"""Integration tests: planner records a compacted human ledger pair (D1).

`LLMPlanner.assess_status` and `LLMPlanner.generate_from_assessment` are the
two callsites that append (LoopHumanMessage, LoopAIMessage) pairs into
`state.loop_messages`. After compaction, the *recorded* copy has ``GOAL:``
rewritten to ``GOAL RECAP:``. Plan-assess AI content stays full-fidelity in ledger.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import soothe.foundation.sloop.state.schemas  # noqa: F401 — break circular import
from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.sloop.cognition.planner import LLMPlanner
from soothe.foundation.sloop.state.schemas import (
    LoopState,
    PlanGenerateStep,
    PlanGeneration,
    StatusAssessment,
)
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.protocols.planner import PlanContext

GOAL = "translate the README into French"

# New scenario-based format for recorded human content
RECORDED_HUMAN_CONTENT = f"GOAL:\n{GOAL}\n\nPRIOR PROGRESS:\nhint=low"


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
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
async def test_assess_status_records_compacted_human_and_preserves_ai_dump() -> None:
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

    ce = _make_ce()
    state = LoopState(goal=GOAL, thread_id="t1", iteration=1)
    goal = GoalNode(description=GOAL)
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    await planner.assess_status(GOAL, state, PlanContext(), context_engine=ce)

    msgs = ce.ledger.get_messages()
    assert len(msgs) == 2
    recorded_human, recorded_ai = msgs

    # D1: GOAL: is rewritten so it doesn't anchor as a directive.
    assert "GOAL:\n" not in recorded_human.content
    assert "GOAL RECAP:" in recorded_human.content
    assert GOAL in recorded_human.content
    # PRIOR PROGRESS is preserved (not a target of C1/D1).
    assert "PRIOR PROGRESS:" in recorded_human.content

    # Plan-assess AI dump is recorded in full for ledger auditing/inspection.
    assert "assessment_reasoning" in recorded_ai.content
    assert "need more evidence" in recorded_ai.content
    # Schema-essential fields still present.
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
        type="execute_steps",
        steps=[
            PlanGenerateStep(
                id="01",
                description="Translate section 1 of the README into French",
                expected_output="French text for section 1",
            )
        ],
        execution_mode="parallel",
        reasoning="I'll translate section by section and keep the model rationale in the dump.",
    )
    planner._generate_plan_with_response = AsyncMock(  # type: ignore[method-assign]
        return_value=(plan_generation, plan_generation)
    )
    planner._finalize_generated_plan_result = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda result, **_: result
    )

    ce = _make_ce()
    state = LoopState(goal=GOAL, thread_id="t1", iteration=1)
    goal = GoalNode(description=GOAL)
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    assessment = StatusAssessment(status="continue", goal_progress="low")
    await planner.generate_from_assessment(
        GOAL, state, PlanContext(), assessment, context_engine=ce
    )

    msgs = ce.ledger.get_messages()
    assert len(msgs) == 2
    recorded_human, recorded_ai = msgs

    # D1 applies to plan-generate humans.
    assert "GOAL:\n" not in recorded_human.content
    assert "GOAL RECAP:" in recorded_human.content

    # A2 does NOT apply to plan-generate: the `steps` list and `reasoning`
    # are the value of the recording, so the AI dump stays verbatim.
    assert "I'll translate section by section and keep the model rationale" in recorded_ai.content
    assert recorded_ai.phase == "plan_generate"


@pytest.mark.asyncio
async def test_recorded_humans_are_cache_stable_across_iterations() -> None:
    """Two assess calls on different iterations record identical human content
    (modulo PRIOR PROGRESS, which is rebuilt per iteration).

    User messages no longer carry volatile timestamps (clock is on the system
    prompt footer), so two calls that share the same goal + PRIOR PROGRESS
    produce byte-identical recordings — the prompt-cache prefix is preserved.
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

    ce_a = _make_ce()
    ce_b = _make_ce()
    state_a = LoopState(goal=GOAL, thread_id="t1", iteration=1)
    state_b = LoopState(goal=GOAL, thread_id="t1", iteration=2)
    goal_a = GoalNode(description=GOAL)
    goal_b = GoalNode(description=GOAL)
    ce_a._dag.add_goal(goal_a)
    ce_b._dag.add_goal(goal_b)
    state_a.bind_ce(ce_a, goal_a.id)
    state_b.bind_ce(ce_b, goal_b.id)
    await planner.assess_status(GOAL, state_a, PlanContext(), context_engine=ce_a)
    # Re-stub with a fresh human matching iter=2; same content is what we want.
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[_make_human("plan_assess")]
    )
    await planner.assess_status(GOAL, state_b, PlanContext(), context_engine=ce_b)

    msgs_a = ce_a.ledger.get_messages()
    msgs_b = ce_b.ledger.get_messages()
    assert msgs_a[0].content == msgs_b[0].content


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

    ce = _make_ce()
    state = LoopState(goal=GOAL, thread_id="t1", iteration=1)
    goal = GoalNode(description=GOAL)
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    await planner.assess_status(GOAL, state, PlanContext(), context_engine=ce)
    assert ce.ledger.get_messages() == []
