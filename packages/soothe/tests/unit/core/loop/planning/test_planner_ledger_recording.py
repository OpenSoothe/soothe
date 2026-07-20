"""Integration tests: planner assess CE audit (IG-557 Phase G).

``LLMPlanner.assess_status`` persists ``StatusAssessment`` on the CE goal node.
``LLMPlanner.generate_from_assessment`` still records plan-generate ledger pairs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.protocols.planner import PlanContext

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
from soothe.foundation.sloop.utils.messages import LoopHumanMessage

GOAL = "translate the README into French"

RECORDED_HUMAN_CONTENT = f"GOAL:\n{GOAL}\n\nPRIOR PROGRESS:\nhint=low"


def _make_ce() -> ContextEngine:
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
async def test_assess_status_persists_ce_last_assessment_not_ledger() -> None:
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

    assert ce.ledger.get_messages() == []
    stored = ce.get_goal_sync(goal.id)
    assert stored is not None
    assert stored.last_assessment_iteration == 1
    assert stored.last_assessment is not None
    assert stored.last_assessment["status"] == "continue"
    assert stored.last_assessment["goal_progress"] == "none"
    assert "need more evidence" in stored.last_assessment["assessment_reasoning"]


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

    assert "GOAL:\n" not in recorded_human.content
    assert "GOAL RECAP:" in recorded_human.content
    assert "I'll translate section by section and keep the model rationale" in recorded_ai.content
    assert recorded_ai.phase == "plan_generate"


@pytest.mark.asyncio
async def test_assess_status_does_not_record_when_llm_fallback_yields_no_response() -> None:
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
    stored = ce.get_goal_sync(goal.id)
    assert stored is not None
    assert stored.last_assessment is None
