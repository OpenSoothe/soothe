"""IG-557 Phase G: CE last_assessment audit without plan_assess ledger pairs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.protocols.planner import PlanContext

import soothe.sloop.state.schemas  # noqa: F401 — break circular import
from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.state.schemas import LoopState, StatusAssessment
from soothe.sloop.utils.messages import LoopHumanMessage

GOAL = "translate the README into French"


def _make_ce() -> ContextEngine:
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


@pytest.mark.asyncio
async def test_set_last_assessment_round_trip() -> None:
    ce = _make_ce()
    goal = GoalNode(description=GOAL)
    ce._dag.add_goal(goal)
    assessment = StatusAssessment(
        status="continue",
        goal_progress="medium",
        assessment_reasoning="More work needed on tests.",
    )
    ce.set_last_assessment(goal.id, assessment, iteration=2)
    stored = ce.get_goal_sync(goal.id)
    assert stored is not None
    assert stored.last_assessment_iteration == 2
    assert stored.last_assessment is not None
    assert stored.last_assessment["status"] == "continue"
    assert stored.last_assessment["goal_progress"] == "medium"


@pytest.mark.asyncio
async def test_set_last_assessment_overwrites_prior() -> None:
    ce = _make_ce()
    goal = GoalNode(description=GOAL)
    ce._dag.add_goal(goal)
    ce.set_last_assessment(
        goal.id,
        StatusAssessment(status="continue", goal_progress="low"),
        iteration=1,
    )
    ce.set_last_assessment(
        goal.id,
        StatusAssessment(status="replan", goal_progress="none"),
        iteration=2,
    )
    stored = ce.get_goal_sync(goal.id)
    assert stored is not None
    assert stored.last_assessment_iteration == 2
    assert stored.last_assessment["status"] == "replan"


@pytest.mark.asyncio
async def test_assess_status_writes_ce_not_ledger() -> None:
    planner = LLMPlanner(MagicMock())
    rendered_human = LoopHumanMessage(
        content=f"GOAL:\n{GOAL}",
        thread_id="t1",
        iteration=1,
        goal_summary=GOAL[:200],
        phase="plan_assess",
    )
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[rendered_human]
    )
    assessment = StatusAssessment(
        status="continue",
        goal_progress="low",
        assessment_reasoning="Need more evidence.",
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
    assert stored.last_assessment["status"] == "continue"
    assert stored.last_assessment["goal_progress"] == "none"
