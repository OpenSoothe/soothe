"""Middleware: inject decompose prompts / tool on step THREADS (RFC-904)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ModelResponse,
)

from soothe.prompts import (
    THREAD_POLICY_SYSTEM_ADDENDUM,
    WRITE_TODOS_TOOL_DESCRIPTION,
)
from soothe.sloop.decompose.runtime import current_step_id
from soothe.sloop.decompose.tool import build_decompose_task_tool
from soothe.sloop.utils.config_keys import SOOTHE_DECOMPOSE_STEP_ID_KEY

logger = logging.getLogger(__name__)

_DECOMPOSE_TOOL = build_decompose_task_tool()


def _langgraph_configurable() -> dict[str, Any]:
    try:
        from langgraph.config import get_config

        lg_cfg = get_config()
    except Exception:
        return {}
    if not isinstance(lg_cfg, dict):
        return {}
    conf = lg_cfg.get("configurable")
    return conf if isinstance(conf, dict) else {}


def _override_write_todos_description(tools: list[Any]) -> list[Any]:
    out: list[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "get", lambda *_: None)("name")
        if name == "write_todos" and hasattr(tool, "description"):
            try:
                cloned = tool.model_copy(update={"description": WRITE_TODOS_TOOL_DESCRIPTION})
                out.append(cloned)
                continue
            except Exception:
                try:
                    tool.description = WRITE_TODOS_TOOL_DESCRIPTION
                except Exception:
                    pass
        out.append(tool)
    return out


def _ensure_decompose_tool(tools: list[Any]) -> list[Any]:
    names = {getattr(t, "name", None) for t in tools}
    if "decompose_task" in names:
        return tools
    return [*tools, _DECOMPOSE_TOOL]


def _strip_decompose_tool(tools: list[Any]) -> list[Any]:
    return [t for t in tools if getattr(t, "name", None) != "decompose_task"]


class DecomposeTaskMiddleware(AgentMiddleware):
    """Inject ``decompose_task`` + THREAD policy on step threads.

    Active when a StrangeLoop step id is bound (contextvar or LangGraph
    configurable ``soothe_decompose_step_id``). Hidden on non-step threads
    (synthesis, intake specialists, etc.).

    System gets finish-vs-split / write_todos / hygiene policy; tool schemas
    carry the contracts; user envelope stays instance-focused.
    """

    tools = [_DECOMPOSE_TOOL]

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        conf = _langgraph_configurable()
        step_id = current_step_id() or conf.get(SOOTHE_DECOMPOSE_STEP_ID_KEY)
        if not step_id:
            tools = list(request.tools or [])
            stripped = _strip_decompose_tool(tools)
            return request.override(tools=stripped) if len(stripped) != len(tools) else request

        logger.debug("[decompose] injecting decompose_task on step %s thread", step_id)
        tools = list(request.tools or [])
        tools = _override_write_todos_description(tools)
        tools = _ensure_decompose_tool(tools)

        system = request.system_message
        addendum = THREAD_POLICY_SYSTEM_ADDENDUM
        if system is not None and hasattr(system, "content"):
            content = system.content
            if isinstance(content, str) and addendum not in content:
                from langchain_core.messages import SystemMessage

                new_system = SystemMessage(content=f"{content}\n\n{addendum}")
                return request.override(tools=tools, system_message=new_system)
            if isinstance(content, list):
                from langchain_core.messages import SystemMessage

                new_blocks = [
                    *content,
                    {"type": "text", "text": f"\n\n{addendum}"},
                ]
                new_system = SystemMessage(content=new_blocks)
                return request.override(tools=tools, system_message=new_system)

        return request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Apply decompose injection before the sync model call."""
        return handler(self.modify_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Apply decompose injection before the async model call."""
        return await handler(self.modify_request(request))
