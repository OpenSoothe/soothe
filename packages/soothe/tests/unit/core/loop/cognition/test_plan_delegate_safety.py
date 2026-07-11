"""Plan-generate subagent delegate guardrails (Pass 2 alignment)."""

from __future__ import annotations

from soothe.foundation.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.foundation.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    RoutingClassification,
    TaskComplexity,
)
from soothe.foundation.sloop.state.schemas import StepAction, strip_unrequested_step_delegates


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
            description="Web research",
            execution_hint="subagent",
            subagent="deep_research",
            wire_subagent="deep_research",
        ),
    ]
    out = strip_unrequested_step_delegates(steps, user_wire_subagent="deep_research")
    assert out[0].wire_subagent == "deep_research"


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
    from soothe.foundation.sloop.prompts.user_message import UserMessageBuilder

    msg = UserMessageBuilder().build_plan_generate_message(
        "analyze local repo",
        user_wire_subagent=None,
    )
    assert "SUBAGENT ROUTING" in msg
    assert "Leave delegate null" in msg

    msg_explicit = UserMessageBuilder().build_plan_generate_message(
        "use deep_research for docs",
        user_wire_subagent="deep_research",
    )
    assert "User requested wired subagent: deep_research" in msg_explicit
