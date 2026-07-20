"""IG-557 Phase C: PREVIOUS ASSESSMENT inline from CE last_assessment."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.protocols.planner import PlanContext

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.context.projection import ContextBundle
from soothe.foundation.sloop.prompts import PromptBuilder
from soothe.foundation.sloop.prompts.user_message import UserMessageBuilder
from soothe.foundation.sloop.state.schemas import LoopState, StatusAssessment


def test_previous_assessment_rendered_from_ce_goal() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message_v2(
        goal="multi part goal",
        last_assessment={
            "status": "continue",
            "goal_progress": "medium",
            "assessment_reasoning": "Checked build output; e2e still missing.",
        },
    )
    assert "PREVIOUS ASSESSMENT:" in msg
    assert "Status: continue, Progress: medium" in msg
    assert "e2e still missing" in msg


def test_previous_assessment_omitted_when_none() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message_v2(goal="g", last_assessment=None)
    assert "PREVIOUS ASSESSMENT:" not in msg


def test_build_plan_messages_includes_previous_assessment_from_bundle() -> None:
    goal_node = GoalNode(
        description="g",
        last_assessment=StatusAssessment(
            status="replan",
            goal_progress="low",
            assessment_reasoning="Need another wave.",
        ).model_dump(mode="json"),
        last_assessment_iteration=1,
    )
    bundle = ContextBundle(active_goal=goal_node)
    state = LoopState(goal="g", thread_id="t", iteration=2)
    msgs = PromptBuilder().build_plan_messages(
        "g",
        state,
        PlanContext(),
        plan_phase="assess",
        context_bundle=bundle,
    )
    human = msgs[-1].content
    assert "PREVIOUS ASSESSMENT:" in human
    assert "Status: replan, Progress: low" in human


def test_previous_assessment_survives_ce_round_trip() -> None:
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    goal = GoalNode(description="g")
    ce._dag.add_goal(goal)
    assessment = StatusAssessment(
        status="continue",
        goal_progress="high",
        assessment_reasoning="Most components satisfied.",
    )
    ce.set_last_assessment(goal.id, assessment, iteration=2)
    stored = ce.get_goal_sync(goal.id)
    assert stored is not None
    msg = UserMessageBuilder().build_plan_assess_message_v2(
        goal="g",
        last_assessment=stored.last_assessment,
    )
    assert "PREVIOUS ASSESSMENT:" in msg
    assert "Progress: high" in msg
