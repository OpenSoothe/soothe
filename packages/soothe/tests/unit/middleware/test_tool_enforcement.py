"""Tests for ToolEnforcementMiddleware and host goal/step guards."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from soothe_nano.middleware.tool_enforcement import ToolEnforcementMiddleware
from soothe_sdk.intention.models import RoutingClassification

from soothe.sloop.middleware import (
    GoalStepGuardMiddleware,
    IntakeOnlyTaskGuardMiddleware,
)
from soothe.sloop.utils.config_keys import SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY


def _run_through_hook(middleware: object, request: ModelRequest) -> ModelRequest:
    """Drive the real langchain hook so a dead hook name fails the test."""
    seen: dict[str, ModelRequest] = {}

    async def handler(req: ModelRequest) -> str:
        seen["request"] = req
        return "response"

    awrap = getattr(middleware, "awrap_model_call")
    asyncio.run(awrap(request, handler))
    return seen["request"]


def test_wire_subagent_routing_first_hop_narrows_to_task() -> None:
    middleware = ToolEnforcementMiddleware()
    classification = RoutingClassification(
        task_complexity="simple",
        preferred_subagent="plugin_agent",
        routing_hint="subagent",
    )
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="draft a plan")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="search_web"), SimpleNamespace(name="task")],
        state={"routing_classification": classification},
    )

    modified = _run_through_hook(middleware, request)
    assert len(modified.tools) == 1
    assert getattr(modified.tools[0], "name", None) == "task"
    assert modified.state["_subagent_routing_directive"] == "plugin_agent"


def test_wire_subagent_routing_after_first_hop_keeps_full_tools() -> None:
    middleware = ToolEnforcementMiddleware()
    classification = RoutingClassification(
        task_complexity="simple",
        preferred_subagent="plugin_agent",
        routing_hint="subagent",
    )
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="x"), AIMessage(content="delegating")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="search_web"), SimpleNamespace(name="task")],
        state={"routing_classification": classification},
    )

    modified = _run_through_hook(middleware, request)
    assert len(modified.tools) == 2
    assert "_subagent_routing_directive" not in modified.state


def test_intake_only_preferred_subagent_does_not_narrow_tools() -> None:
    """Host guard clears intake-only preferred_subagent before tool enforcement."""
    guard = IntakeOnlyTaskGuardMiddleware()
    middleware = ToolEnforcementMiddleware()
    for name in ("deep_research",):  # planner removed from intake-only set
        classification = RoutingClassification(
            task_complexity="simple",
            preferred_subagent=name,
            routing_hint="subagent",
        )
        request = ModelRequest(
            model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
            messages=[HumanMessage(content="research")],
            system_message=SystemMessage(content="orig"),
            tools=[SimpleNamespace(name="search_web"), SimpleNamespace(name="task")],
            state={"routing_classification": classification},
        )
        scrubbed = _run_through_hook(guard, request)
        modified = _run_through_hook(middleware, scrubbed)
        assert len(modified.tools) == 2
        preferred = getattr(modified.state["routing_classification"], "preferred_subagent", None)
        assert preferred is None


def test_goal_step_guard_keeps_tools_without_synthesis() -> None:
    """Only goal synthesis narrows tools; execute steps keep the full tool set."""
    middleware = GoalStepGuardMiddleware()
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="x"), AIMessage(content="delegating")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="run_command"), SimpleNamespace(name="task")],
        state={"routing_classification": RoutingClassification(task_complexity="simple")},
    )
    with patch("langgraph.config.get_config", return_value={"configurable": {"thread_id": "t1"}}):
        modified = _run_through_hook(middleware, request)

    assert len(modified.tools) == 2
    assert "_subagent_routing_directive" not in modified.state


def test_goal_synthesis_disables_tools() -> None:
    middleware = GoalStepGuardMiddleware()
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="synthesize")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="read_file"), SimpleNamespace(name="task")],
        state={},
    )
    with patch(
        "langgraph.config.get_config",
        return_value={"configurable": {SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY: True}},
    ):
        modified = _run_through_hook(middleware, request)

    assert modified.tools == []
