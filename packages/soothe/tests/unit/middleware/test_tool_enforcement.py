"""Tests for ToolEnforcementMiddleware tool-narrowing boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.foundation.sloop.intention import RoutingClassification
from soothe.middleware.tool_enforcement import ToolEnforcementMiddleware


def test_wire_subagent_routing_first_hop_narrows_to_task() -> None:
    middleware = ToolEnforcementMiddleware()
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="planner",
        routing_hint="subagent",
    )
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="draft a plan")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="search_web"), SimpleNamespace(name="task")],
        state={"routing_classification": classification},
    )

    modified = middleware.modify_request(request)
    assert len(modified.tools) == 1
    assert getattr(modified.tools[0], "name", None) == "task"
    assert modified.state["_subagent_routing_directive"] == "planner"


def test_wire_subagent_routing_after_first_hop_keeps_full_tools() -> None:
    middleware = ToolEnforcementMiddleware()
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="planner",
        routing_hint="subagent",
    )
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="x"), AIMessage(content="delegating")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="search_web"), SimpleNamespace(name="task")],
        state={"routing_classification": classification},
    )

    modified = middleware.modify_request(request)
    assert len(modified.tools) == 2
    assert "_subagent_routing_directive" not in modified.state


def test_intake_only_preferred_subagent_does_not_narrow_tools() -> None:
    """IG-601: intake-only preferred_subagent is ignored for CoreAgent task enforcement."""
    middleware = ToolEnforcementMiddleware()
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="deep_research",
        routing_hint="subagent",
    )
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="research")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="search_web"), SimpleNamespace(name="task")],
        state={"routing_classification": classification},
    )
    modified = middleware.modify_request(request)
    assert len(modified.tools) == 2


def test_step_subagent_enforces_task_only_on_all_hops() -> None:
    middleware = ToolEnforcementMiddleware()
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="x"), AIMessage(content="delegating")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="run_command"), SimpleNamespace(name="task")],
        state={"routing_classification": RoutingClassification(task_complexity="medium")},
    )
    with patch(
        "langgraph.config.get_config",
        return_value={"configurable": {"soothe_step_subagent": "planner"}},
    ):
        modified = middleware.modify_request(request)

    assert len(modified.tools) == 1
    assert getattr(modified.tools[0], "name", None) == "task"
    assert modified.state["_subagent_routing_directive"] == "planner"


def test_goal_synthesis_disables_tools() -> None:
    middleware = ToolEnforcementMiddleware()
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="synthesize")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="read_file"), SimpleNamespace(name="task")],
        state={},
    )
    with patch(
        "langgraph.config.get_config",
        return_value={"configurable": {"soothe_goal_synthesis": True}},
    ):
        modified = middleware.modify_request(request)

    assert modified.tools == []
