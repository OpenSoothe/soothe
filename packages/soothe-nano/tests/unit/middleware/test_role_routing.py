"""Unit tests for RoleRoutingMiddleware (IG-545)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from soothe_nano.config.settings import SootheConfig
from soothe_nano.middleware._builder import build_soothe_middleware_stack
from soothe_nano.middleware.role_routing import (
    RoleRoutingMiddleware,
    model_hop_index_since_user,
    resolve_model_role_for_request,
)


def _request(
    *,
    messages: list,
    tools: list | None | object = ...,
    tool_choice: str | None = None,
) -> ModelRequest:
    if tools is ...:
        resolved_tools: list = [SimpleNamespace(name="read_file")]
    else:
        resolved_tools = list(tools) if tools is not None else []
    return ModelRequest(
        model=object(),
        messages=messages,
        system_message=SystemMessage(content="sys"),
        tools=resolved_tools,
        tool_choice=tool_choice,
        state={},
    )


class TestModelHopIndexSinceUser:
    def test_first_hop_after_user(self) -> None:
        msgs = [HumanMessage(content="hi")]
        assert model_hop_index_since_user(msgs) == 0

    def test_second_hop_after_tool_round(self) -> None:
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"id": "1", "name": "read_file", "args": {}}]),
            ToolMessage(content="ok", tool_call_id="1"),
        ]
        assert model_hop_index_since_user(msgs) == 1

    def test_resets_at_new_user_message(self) -> None:
        msgs = [
            HumanMessage(content="first"),
            AIMessage(content="done"),
            HumanMessage(content="second"),
        ]
        assert model_hop_index_since_user(msgs) == 0


class TestResolveModelRoleForRequest:
    def test_no_tools_uses_generation(self) -> None:
        req = _request(messages=[HumanMessage(content="hi")], tools=[])
        role = resolve_model_role_for_request(
            req,
            orchestration_model_role="fast",
            generation_model_role="default",
            max_orchestration_hops=1,
        )
        assert role == "default"

    def test_first_hop_with_tools_uses_orchestration(self) -> None:
        req = _request(messages=[HumanMessage(content="hi")])
        role = resolve_model_role_for_request(
            req,
            orchestration_model_role="fast",
            generation_model_role="default",
            max_orchestration_hops=1,
        )
        assert role == "fast"

    def test_hop_cap_switches_to_generation(self) -> None:
        req = _request(
            messages=[
                HumanMessage(content="hi"),
                AIMessage(content="", tool_calls=[{"id": "1", "name": "read_file", "args": {}}]),
                ToolMessage(content="ok", tool_call_id="1"),
            ]
        )
        role = resolve_model_role_for_request(
            req,
            orchestration_model_role="fast",
            generation_model_role="default",
            max_orchestration_hops=1,
        )
        assert role == "default"

    def test_goal_synthesis_empty_tools_uses_generation(self) -> None:
        """Host goal-synthesis clears tools; empty tools select generation role."""
        req = _request(messages=[HumanMessage(content="synthesize")], tools=[])
        role = resolve_model_role_for_request(
            req,
            orchestration_model_role="fast",
            generation_model_role="default",
            max_orchestration_hops=3,
        )
        assert role == "default"

    def test_tool_choice_none_uses_generation(self) -> None:
        req = _request(messages=[HumanMessage(content="hi")], tool_choice="none")
        role = resolve_model_role_for_request(
            req,
            orchestration_model_role="fast",
            generation_model_role="default",
            max_orchestration_hops=3,
        )
        assert role == "default"


class TestRoleRoutingMiddleware:
    def test_disabled_is_noop(self) -> None:
        config = SootheConfig()
        middleware = RoleRoutingMiddleware(config)
        base_model = object()
        request = ModelRequest(
            model=base_model,
            messages=[HumanMessage(content="hi")],
            system_message=SystemMessage(content="sys"),
            tools=[SimpleNamespace(name="task")],
            state={},
        )
        seen: list[object] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen.append(req.model)
            return ModelResponse(result=[])

        middleware.wrap_model_call(request, handler)
        assert seen == [base_model]

    @pytest.mark.asyncio
    async def test_enabled_swaps_orchestration_model(self) -> None:
        config = SootheConfig(
            agent={
                "runtime": {
                    "role_routing": {
                        "enabled": True,
                        "orchestration_model_role": "fast",
                        "generation_model_role": "default",
                        "max_orchestration_hops": 2,
                    }
                }
            }
        )
        fast_model = object()
        default_model = object()
        middleware = RoleRoutingMiddleware(config)

        def fake_create(_self: SootheConfig, role: str) -> object:
            return fast_model if role == "fast" else default_model

        with patch.object(SootheConfig, "create_chat_model", fake_create):
            request = ModelRequest(
                model=default_model,
                messages=[HumanMessage(content="hi")],
                system_message=SystemMessage(content="sys"),
                tools=[SimpleNamespace(name="read_file")],
                state={},
            )
            seen: list[object] = []

            async def handler(req: ModelRequest) -> ModelResponse:
                seen.append(req.model)
                return ModelResponse(result=[])

            await middleware.awrap_model_call(request, handler)

        assert seen == [fast_model]


def test_main_stack_mounts_role_routing_when_enabled() -> None:
    config = SootheConfig(
        agent={"runtime": {"role_routing": {"enabled": True}}},
    )
    stack = build_soothe_middleware_stack(config, policy=None)
    assert any(mw.name == "RoleRoutingMiddleware" for mw in stack)


def test_main_stack_omits_role_routing_when_disabled() -> None:
    config = SootheConfig()
    stack = build_soothe_middleware_stack(config, policy=None)
    assert not any(mw.name == "RoleRoutingMiddleware" for mw in stack)
