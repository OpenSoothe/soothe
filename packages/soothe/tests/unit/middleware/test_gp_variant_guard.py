"""Tests for GeneralPurposeVariantGuardMiddleware redirect logic."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from langchain.tools.tool_node import ToolCallRequest

from soothe.sloop.middleware.gp_variant_guard import (
    GeneralPurposeVariantGuardMiddleware,
)


@dataclass
class _StubRuntime:
    config: dict[str, Any]


def _make_request(
    mode: str | None,
    subagent_type: str = "general-purpose",
    tool_name: str = "task",
) -> ToolCallRequest:
    configurable = {"soothe_interaction_mode": mode} if mode is not None else {}
    return ToolCallRequest(
        tool_call={
            "name": tool_name,
            "args": {"subagent_type": subagent_type, "description": "x"},
            "id": "tc1",
        },
        tool=None,
        state={},
        runtime=_StubRuntime({"configurable": configurable}),
    )


def _run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


async def _return_subagent_type(request: ToolCallRequest) -> str:
    return request.tool_call["args"]["subagent_type"]  # type: ignore[index]


class TestRedirect:
    def test_plan_mode_redirects_to_readonly(self) -> None:
        mw = GeneralPurposeVariantGuardMiddleware()
        result = _run(mw.awrap_tool_call(_make_request("plan"), _return_subagent_type))
        assert result == "general-purpose-readonly"

    def test_ask_mode_redirects_to_readonly(self) -> None:
        mw = GeneralPurposeVariantGuardMiddleware()
        result = _run(mw.awrap_tool_call(_make_request("ask"), _return_subagent_type))
        assert result == "general-purpose-readonly"

    def test_agent_mode_keeps_full(self) -> None:
        mw = GeneralPurposeVariantGuardMiddleware()
        result = _run(mw.awrap_tool_call(_make_request("agent"), _return_subagent_type))
        assert result == "general-purpose"

    def test_unset_mode_keeps_full(self) -> None:
        mw = GeneralPurposeVariantGuardMiddleware()
        result = _run(mw.awrap_tool_call(_make_request(None), _return_subagent_type))
        assert result == "general-purpose"

    def test_non_gp_subagent_untouched(self) -> None:
        mw = GeneralPurposeVariantGuardMiddleware()
        result = _run(
            mw.awrap_tool_call(
                _make_request("plan", subagent_type="deep_research"),
                _return_subagent_type,
            )
        )
        assert result == "deep_research"

    async def _passthrough(self, request: ToolCallRequest) -> str:
        return "passthrough"

    def test_non_task_tool_passes_through(self) -> None:
        mw = GeneralPurposeVariantGuardMiddleware()
        result = _run(
            mw.awrap_tool_call(
                _make_request("plan", tool_name="read_file"),
                self._passthrough,
            )
        )
        assert result == "passthrough"
