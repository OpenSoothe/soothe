"""Plan-generate subagent delegate guardrails (Pass 2 alignment)."""

from __future__ import annotations

from soothe.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    RoutingClassification,
    TaskComplexity,
)
from soothe.sloop.state.schemas import StepAction, strip_unrequested_step_delegates


def test_strip_unrequested_step_delegates_clears_planner_wiring() -> None:
    steps = [
        StepAction(
            id="01",
            description="Discover APIs in repo",
            execution_hint="subagent",
            subagent="deep_research",
            wire_subagent="deep_research",
        ),
        StepAction(id="02", description="Summarize locally"),
    ]
    out = strip_unrequested_step_delegates(steps, user_wire_subagent=None)
    assert out[0].execution_hint == "auto"
    assert out[0].subagent is None
    assert out[0].wire_subagent is None
    assert out[1] is steps[1]


def test_strip_unrequested_step_delegates_keeps_when_user_requested() -> None:
    steps = [
        StepAction(
            id="01",
            description="Run plugin specialist",
            execution_hint="subagent",
            subagent="plugin_agent",
            wire_subagent="plugin_agent",
        ),
    ]
    out = strip_unrequested_step_delegates(steps, user_wire_subagent="plugin_agent")
    assert out[0].wire_subagent == "plugin_agent"


def test_strip_unrequested_treats_intake_only_user_wire_as_absent() -> None:
    steps = [
        StepAction(
            id="01",
            description="Web research",
            execution_hint="subagent",
            subagent="deep_research",
            wire_subagent="deep_research",
        ),
    ]
    out = strip_unrequested_step_delegates(steps, user_wire_subagent="deep_research")
    assert out[0].wire_subagent is None
    assert out[0].execution_hint == "auto"

    planner_steps = [
        StepAction(
            id="01",
            description="Draft plan",
            execution_hint="subagent",
            subagent="planner",
            wire_subagent="planner",
        ),
    ]
    out_planner = strip_unrequested_step_delegates(
        planner_steps, user_wire_subagent="planner"
    )
    assert out_planner[0].wire_subagent is None
    assert out_planner[0].execution_hint == "auto"


def test_resolve_user_requested_wire_subagent_from_intent() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="browser_use",
        task_complexity=TaskComplexity.SIMPLE,
    )
    assert resolve_user_requested_wire_subagent(intent=intent) == "browser_use"


def test_resolve_user_requested_wire_subagent_from_slash_routing() -> None:
    routing = RoutingClassification(
        task_complexity=TaskComplexity.MEDIUM,
        preferred_subagent="deep_research",
        routing_hint="subagent",
    )
    assert resolve_user_requested_wire_subagent(routing_classification=routing) == "deep_research"


def test_build_plan_generate_message_includes_subagent_routing_block() -> None:
    from soothe.sloop.prompts.user_message import UserMessageBuilder

    msg = UserMessageBuilder().build_plan_generate_message(
        "analyze local repo",
        user_wire_subagent=None,
    )
    assert "SUBAGENT ROUTING" in msg
    assert "Leave delegate null" in msg

    msg_explicit = UserMessageBuilder().build_plan_generate_message(
        "use plugin_agent for migration plan",
        user_wire_subagent="plugin_agent",
    )
    assert "User requested wired subagent: plugin_agent" in msg_explicit

    # Intake-only hints never reach plan-generate in production; message falls
    # back to the default catalog guidance.
    msg_intake_only = UserMessageBuilder().build_plan_generate_message(
        "use deep_research for docs",
        user_wire_subagent="deep_research",
    )
    assert "intake-only" in msg_intake_only
    assert "Leave delegate null" in msg_intake_only

    msg_planner = UserMessageBuilder().build_plan_generate_message(
        "use planner for migration plan",
        user_wire_subagent="planner",
    )
    assert "intake-only" in msg_planner
    assert "Leave delegate null" in msg_planner
