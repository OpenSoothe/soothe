"""Progressive builtin-tool loading middleware."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe.toolkits.progressive.registry import (
    DEFAULT_CORE_TOOL_NAMES,
    ProgressiveToolRegistry,
    ToolDescriptor,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_SEARCH_TOOL_NAME = "search_tools"


class ProgressiveToolMiddleware(AgentMiddleware):
    """Bind core tools on cold start; promote deferred tools on invoke or search."""

    name = "ProgressiveToolMiddleware"

    def __init__(self, config: SootheConfig) -> None:
        super().__init__()
        self._config = config
        pt = config.progressive_tools
        core = list(pt.core_tools) if pt.core_tools else None
        if pt.search_tools_enabled:
            if core is None:
                core = list(DEFAULT_CORE_TOOL_NAMES)
            elif _SEARCH_TOOL_NAME not in core:
                core.append(_SEARCH_TOOL_NAME)
        self._registry = ProgressiveToolRegistry(core_tools=core)
        self._catalog: list[ToolDescriptor] = []
        self._full_tools: list[Any] = []

    def set_tool_catalog(self, tools: list[Any]) -> None:
        """Called at agent build time with the full resolved tool list."""
        self._full_tools = list(tools)
        self._catalog = self._registry.descriptors_from_tools(tools)

    def full_tools_for_listing(self) -> list[Any]:
        """Unfiltered tool list for ``<AVAILABLE_TOOLS>`` (before per-hop binding)."""
        return list(self._full_tools)

    async def abefore_agent(self, state: dict, runtime: Any) -> dict | None:
        if not isinstance(state, dict):
            return None
        if "tool_activation" not in state:
            return {"tool_activation": ProgressiveToolRegistry.init_activation_state()}
        return None

    def _activation(self, state: Any) -> dict[str, set[str]]:
        if not isinstance(state, dict):
            return ProgressiveToolRegistry.init_activation_state()
        activation = state.get("tool_activation")
        if not isinstance(activation, dict):
            activation = ProgressiveToolRegistry.init_activation_state()
            state["tool_activation"] = activation
        return activation

    def _deferred_descriptors(self) -> list[ToolDescriptor]:
        _, deferred = self._registry.partition(self._catalog)
        return deferred

    def _handle_search_tools(
        self,
        query: str,
        limit: int,
        activation: dict[str, set[str]],
    ) -> str:
        deferred = self._deferred_descriptors()
        matches = self._registry.search_deferred(query, deferred, limit=limit)
        if not matches:
            return f"No deferred tools matched query={query!r}."
        self._registry.mark_promoted(activation, [m.name for m in matches])
        lines = [f"- {m.name}: {m.description}" for m in matches]
        return (
            f"Promoted {len(matches)} tool(s) for this thread:\n"
            + "\n".join(lines)
            + "\nThey are now available on subsequent model hops."
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_call = getattr(request, "tool_call", None) or {}
        tool_name = str(tool_call.get("name", ""))
        state = getattr(request, "state", None) or {}
        activation = self._activation(state)

        if tool_name == _SEARCH_TOOL_NAME:
            args = tool_call.get("args", {})
            if not isinstance(args, dict):
                args = {}
            query = str(args.get("query", ""))
            limit = int(args.get("limit", 10) or 10)
            content = self._handle_search_tools(query, limit, activation)
            tool_call_id = str(tool_call.get("id", "") or tool_call.get("tool_call_id", ""))
            return ToolMessage(content=content, tool_call_id=tool_call_id, name=_SEARCH_TOOL_NAME)

        result = await handler(request)

        if tool_name and tool_name not in self._registry.core_tool_names:
            self._registry.mark_promoted(activation, [tool_name])
            logger.debug("[ProgressiveTools] Promoted %s after invocation", tool_name)

        return result

    def _ensure_catalog(self, tools: list[Any]) -> None:
        if not self._catalog and tools:
            self._catalog = self._registry.descriptors_from_tools(tools)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        if not self._config.progressive_tools.enabled:
            return await handler(request)

        state = getattr(request, "state", None) or {}
        activation = self._activation(state)
        tools = getattr(request, "tools", None) or []
        self._ensure_catalog(list(tools))
        bound = self._registry.bound_tools(tools, activation)

        if len(bound) < len(tools):
            logger.debug(
                "[ProgressiveTools] Bound %d/%d tools (core+promoted)",
                len(bound),
                len(tools),
            )
            request = request.override(tools=bound)

        return await handler(request)
