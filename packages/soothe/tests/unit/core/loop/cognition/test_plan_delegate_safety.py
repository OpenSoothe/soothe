"""Plan-generate subagent delegate guardrails (Pass 2 alignment)."""

from __future__ import annotations

from soothe.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.sloop.intention.models import RoutingClassification, TaskComplexity
from soothe.sloop.state.schemas import StepAction, strip_unrequested_step_delegates


def test_strip_unrequested_step_delegates_clears_all_wiring() -> None:
    steps = [
        StepAction(
            id="01",
            description="Discover APIs in repo",
            execution_hint="subagent",
            subagent="deep_research",
        ),
        StepAction(id="02", description="Summarize locally"),
    ]
    out = strip_unrequested_step_delegates(steps)
    assert out[0].execution_hint == "auto"
    assert out[0].subagent is None
    assert out[1] is steps[1]


def test_strip_unrequested_clears_catalog_delegate() -> None:
    """IG-656: no plan-wave keep-path — even non-intake delegates are stripped."""
    steps = [
        StepAction(
            id="01",
            description="Run plugin specialist",
            execution_hint="subagent",
            subagent="plugin_agent",
        ),
    ]
    out = strip_unrequested_step_delegates(steps)
    assert out[0].subagent is None
    assert out[0].execution_hint == "auto"


def test_strip_unrequested_clears_intake_only_delegate() -> None:
    for name in ("deep_research", "planner"):
        steps = [
            StepAction(
                id="01",
                description="Specialist work",
                execution_hint="subagent",
                subagent=name,
            ),
        ]
        out = strip_unrequested_step_delegates(steps)
        assert out[0].subagent is None
        assert out[0].execution_hint == "auto"


def test_resolve_user_requested_wire_subagent_from_slash_preferred() -> None:
    assert resolve_user_requested_wire_subagent(preferred_subagent="browser_use") == "browser_use"
    assert resolve_user_requested_wire_subagent(preferred_subagent="plugin_agent") is None


def test_resolve_user_requested_wire_subagent_from_slash_routing() -> None:
    routing = RoutingClassification(
        task_complexity=TaskComplexity.MEDIUM,
        preferred_subagent="deep_research",
        routing_hint="subagent",
    )
    assert resolve_user_requested_wire_subagent(routing_classification=routing) == "deep_research"


def test_build_plan_generate_message_includes_subagent_routing_block() -> None:
    from soothe.sloop.prompts.user_message import UserMessageBuilder

    msg = UserMessageBuilder().build_plan_generate_message("analyze local repo")
    assert "SUBAGENT ROUTING" in msg
    assert "Leave delegate null" in msg
    assert "intake-only" in msg


def test_build_plan_generate_message_includes_approved_plan_section() -> None:
    from soothe.sloop.prompts.user_message import UserMessageBuilder

    msg = UserMessageBuilder().build_plan_generate_message(
        "migrate auth",
        approved_plan_path="/ws/.soothe/plans/demo.md",
        approved_plan_markdown="# Solution\n\nUse OAuth.\n",
    )
    assert "APPROVED PLAN" in msg
    assert "path: /ws/.soothe/plans/demo.md" in msg
    assert "Use OAuth" in msg
    assert "do not re-litigate" in msg
