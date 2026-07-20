"""Progressive builtin-tool loading middleware."""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, NotRequired

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    AgentState,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe_nano.middleware.tool_name_hints import (
    extract_tool_message_content,
    is_invalid_tool_error,
)
from soothe_nano.toolkits.progressive.registry import (
    DEFAULT_CORE_TOOL_NAMES,
    ProgressiveToolRegistry,
    ToolDescriptor,
    merge_tool_activation,
    snapshot_tool_activation,
)

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_SEARCH_TOOL_NAME = "search_tools"
_SEARCH_SKILLS_TOOL_NAME = "search_skills"
_INVOKE_SKILL_TOOL_NAME = "invoke_skill"

# Set by SystemPromptMiddleware when <AVAILABLE_TOOLS> marks entries as sent.
_tool_activation_update: contextvars.ContextVar[dict[str, set[str]] | None] = (
    contextvars.ContextVar(
        "soothe_tool_activation_update",
        default=None,
    )
)


class ProgressiveToolState(AgentState[Any]):
    """Graph state channel for progressive builtin-tool activation."""

    tool_activation: NotRequired[Annotated[dict[str, Any], merge_tool_activation]]


def stash_tool_activation_update(activation: dict[str, Any]) -> None:
    """Record a pending ``tool_activation`` write for ``aafter_model``."""
    _tool_activation_update.set(snapshot_tool_activation(activation))


def pop_tool_activation_update() -> dict[str, set[str]] | None:
    """Return and clear a pending ``tool_activation`` write, if any."""
    pending = _tool_activation_update.get()
    _tool_activation_update.set(None)
    return pending


class ProgressiveToolMiddleware(AgentMiddleware):
    """Bind core tools on cold start; promote deferred tools on invoke or search."""

    name = "ProgressiveToolMiddleware"
    state_schema = ProgressiveToolState

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
        if config.progressive_skills.search_skills_enabled:
            if core is None:
                core = list(DEFAULT_CORE_TOOL_NAMES)
            else:
                for name in (_SEARCH_SKILLS_TOOL_NAME, _INVOKE_SKILL_TOOL_NAME):
                    if name not in core:
                        core.append(name)
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

    async def aafter_model(self, state: dict, runtime: Any) -> dict | None:
        pending = pop_tool_activation_update()
        if pending is not None:
            return {"tool_activation": pending}
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

    def _known_tool_names(self) -> set[str]:
        """Registered catalog names plus the always-bound core tier."""
        return {d.name for d in self._catalog} | set(self._registry.core_tool_names)

    def _should_promote_after_invoke(
        self,
        tool_name: str,
        result: ToolMessage | Command[Any],
    ) -> bool:
        """Promote only real deferred tools that executed without invalid-name errors."""
        if not tool_name or tool_name in self._registry.core_tool_names:
            return False
        if tool_name not in self._known_tool_names():
            return False
        content = extract_tool_message_content(result)
        return not (content and is_invalid_tool_error(content))

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

    @staticmethod
    def _command_with_activation(
        result: ToolMessage | Command[Any],
        activation: dict[str, set[str]],
    ) -> Command[Any]:
        update: dict[str, Any] = {"tool_activation": snapshot_tool_activation(activation)}
        if isinstance(result, Command):
            existing = result.update
            if isinstance(existing, dict):
                update = {**existing, **update}
            return Command(update=update)
        update["messages"] = [result]
        return Command(update=update)

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
            message = ToolMessage(
                content=content, tool_call_id=tool_call_id, name=_SEARCH_TOOL_NAME
            )
            if activation.get("promoted"):
                logger.debug(
                    "[ProgressiveTools] search_tools promoted %d tool(s)",
                    len(activation["promoted"]),
                )
            return self._command_with_activation(message, activation)

        result = await handler(request)

        if self._should_promote_after_invoke(tool_name, result):
            self._registry.mark_promoted(activation, [tool_name])
            logger.debug("[ProgressiveTools] Promoted %s after invocation", tool_name)
            return self._command_with_activation(result, activation)

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
            promoted_count = len(activation.get("promoted", set()))
            if promoted_count > 0:
                logger.debug(
                    "[ProgressiveTools] Bound %d/%d tools (core+promoted=%d)",
                    len(bound),
                    len(tools),
                    promoted_count,
                )
            request = request.override(tools=bound)

        return await handler(request)
