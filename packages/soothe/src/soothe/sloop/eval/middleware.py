"""Coverage-audit policy for StrangeLoop Eval steps (RFC-905).

Eval steps verify whether the original user goal was fully achieved. Goals that
require execution to verify (run tests, lint, build, query services) need access
to the full tool surface — a read-only Eval cannot catch the "CI passes?" class
of regressions and defaults to "no failure found" (incident: loop adbe, where
an unexecuted ``make lint`` hid a real format/lint failure). Eval threads keep
the coverage-audit system addendum and the ``decompose_task`` escape hatch; they
no longer restrict the tool set.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)

from soothe.prompts import EVAL_POLICY_SYSTEM_ADDENDUM
from soothe.sloop.decompose import runtime as _decompose_runtime
from soothe.sloop.decompose.tool import build_decompose_task_tool
from soothe.sloop.utils.config_keys import SOOTHE_EVAL_STEP_ID_KEY

_DECOMPOSE_TOOL = build_decompose_task_tool()


def _tool_name(tool: Any) -> str:
    name = getattr(tool, "name", None)
    if name is None and isinstance(tool, dict):
        name = tool.get("name")
    return str(name or "")


def _append_system_addendum(request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
    system = request.system_message
    if system is None or not hasattr(system, "content"):
        return request
    content = system.content
    from langchain_core.messages import SystemMessage

    if isinstance(content, str):
        if EVAL_POLICY_SYSTEM_ADDENDUM in content:
            return request
        return request.override(
            system_message=SystemMessage(content=f"{content}\n\n{EVAL_POLICY_SYSTEM_ADDENDUM}")
        )
    if isinstance(content, list):
        return request.override(
            system_message=SystemMessage(
                content=[
                    *content,
                    {"type": "text", "text": f"\n\n{EVAL_POLICY_SYSTEM_ADDENDUM}"},
                ]
            )
        )
    return request


class EvalStepMiddleware(AgentMiddleware):
    """Coverage-audit policy for Eval steps.

    Keeps the full tool surface so the auditor can execute verification commands
    (tests, lint, build) and, when work remains, emit ``decompose_task`` proposals.
    The coverage-audit system addendum is still injected to anchor the thread's
    role: verify, then delegate remaining implementation via decomposition rather
    than performing it inline.
    """

    tools = [_DECOMPOSE_TOOL]

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        configurable = _decompose_runtime.langgraph_configurable()
        if not configurable.get(SOOTHE_EVAL_STEP_ID_KEY):
            return request
        # Keep the full tool surface; only ensure decompose_task is present as the
        # escape hatch for proposing continuation subtasks when work remains.
        tools = list(request.tools or [])
        if "decompose_task" not in {_tool_name(tool) for tool in tools}:
            tools.append(_DECOMPOSE_TOOL)
        request = (
            request.override(tools=tools) if len(tools) != len(request.tools or []) else request
        )
        return _append_system_addendum(request)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(self.modify_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self.modify_request(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        """All tools are permitted on Eval threads — full verification surface."""
        return await handler(request)


__all__ = ["EvalStepMiddleware"]
