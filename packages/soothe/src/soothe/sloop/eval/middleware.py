"""Readonly CoreAgent policy for StrangeLoop Eval steps (RFC-905)."""

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
from langchain_core.messages import ToolMessage

from soothe.prompts import EVAL_POLICY_SYSTEM_ADDENDUM
from soothe.sloop.decompose.tool import build_decompose_task_tool
from soothe.sloop.utils.config_keys import SOOTHE_EVAL_STEP_ID_KEY

_DECOMPOSE_TOOL = build_decompose_task_tool()
# Builtin Eval inspect surface; not operator-configurable.
EVAL_READONLY_TOOL_NAMES = frozenset({"read_file", "grep", "glob", "ls", "list_files", "file_info"})


def _langgraph_configurable() -> dict[str, Any]:
    try:
        from langgraph.config import get_config

        config = get_config()
    except Exception:
        return {}
    configurable = config.get("configurable") if isinstance(config, dict) else None
    return configurable if isinstance(configurable, dict) else {}


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
    """Restrict an Eval request to readonly inspection plus decomposition."""

    tools = [_DECOMPOSE_TOOL]

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        configurable = _langgraph_configurable()
        if not configurable.get(SOOTHE_EVAL_STEP_ID_KEY):
            return request
        tools = [
            tool
            for tool in list(request.tools or [])
            if _tool_name(tool) in EVAL_READONLY_TOOL_NAMES
        ]
        if "decompose_task" not in {_tool_name(tool) for tool in tools}:
            tools.append(_DECOMPOSE_TOOL)
        request = request.override(tools=tools)
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
        """Fail closed if a mutating or unknown tool bypasses model filtering."""
        configurable = _langgraph_configurable()
        if not configurable.get(SOOTHE_EVAL_STEP_ID_KEY):
            return await handler(request)
        tool_call = getattr(request, "tool_call", None)
        tool_name = tool_call.get("name") if isinstance(tool_call, dict) else ""
        allowed = EVAL_READONLY_TOOL_NAMES | {"decompose_task"}
        if tool_name in allowed:
            return await handler(request)
        tool_call_id = tool_call.get("id", "") if isinstance(tool_call, dict) else ""
        return ToolMessage(
            content=f"Tool '{tool_name}' is unavailable in this readonly Eval thread.",
            tool_call_id=str(tool_call_id or ""),
            name=str(tool_name or ""),
            status="error",
        )


__all__ = ["EVAL_READONLY_TOOL_NAMES", "EvalStepMiddleware"]
