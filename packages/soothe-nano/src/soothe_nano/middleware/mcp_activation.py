"""RFC-412: MCP progressive tool activation (search, promote, bind)."""

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

from soothe_nano.mcp.mcp_progressive import (
    ProgressiveMCPRegistry,
    merge_mcp_activation,
    snapshot_mcp_activation,
)
from soothe_nano.mcp.mcp_utils import MCPToolDescriptor, is_mcp_tool_name, parse_mcp_tool_name
from soothe_nano.middleware.tool_name_hints import (
    extract_tool_message_content,
    is_invalid_tool_error,
)

if TYPE_CHECKING:
    from soothe_nano.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)

_SEARCH_MCP_TOOLS = "search_mcp_tools"

_mcp_activation_update: contextvars.ContextVar[dict[str, set[str]] | None] = contextvars.ContextVar(
    "soothe_mcp_activation_update",
    default=None,
)


class MCPActivationState(AgentState[Any]):
    """Graph state channel for progressive MCP tool disclosure."""

    mcp_activation: NotRequired[Annotated[dict[str, Any], merge_mcp_activation]]
    disabled_mcp_servers: NotRequired[set[str]]
    cached_mcp_resources: NotRequired[dict[str, str]]


def stash_mcp_activation_update(activation: dict[str, Any]) -> None:
    """Record a pending ``mcp_activation`` write for ``aafter_model``."""
    _mcp_activation_update.set(snapshot_mcp_activation(activation))


def pop_mcp_activation_update() -> dict[str, set[str]] | None:
    """Return and clear a pending ``mcp_activation`` write, if any."""
    pending = _mcp_activation_update.get()
    _mcp_activation_update.set(None)
    return pending


class MCPActivationMiddleware(AgentMiddleware):
    """Bind always-loaded MCP tools; promote deferred tools on search or invoke."""

    name = "MCPActivationMiddleware"
    state_schema = MCPActivationState

    def __init__(self, mcp_registry: MCPRegistry) -> None:
        super().__init__()
        self._registry = mcp_registry
        core_names = frozenset(
            t.name for t in mcp_registry.always_loaded_tools() if getattr(t, "name", None)
        )
        self._progressive = ProgressiveMCPRegistry(always_loaded_names=core_names)
        self._deferred_descriptors: list[MCPToolDescriptor] = []
        self._deferred_names: set[str] = set()

    def set_tool_catalog(self) -> None:
        """Refresh deferred-tool descriptors from the registry."""
        self._deferred_descriptors = self._registry.deferred_tools()
        self._deferred_names = {d.name for d in self._deferred_descriptors}

    async def abefore_agent(self, state: dict, runtime: Any) -> dict | None:
        if not isinstance(state, dict):
            return None
        updates: dict[str, Any] = {}
        if "mcp_activation" not in state:
            updates["mcp_activation"] = ProgressiveMCPRegistry.init_activation_state()
        if "disabled_mcp_servers" not in state:
            updates["disabled_mcp_servers"] = set()
        if "cached_mcp_resources" not in state:
            updates["cached_mcp_resources"] = {}
        return updates if updates else None

    async def aafter_model(self, state: dict, runtime: Any) -> dict | None:
        pending = pop_mcp_activation_update()
        if pending is not None:
            return {"mcp_activation": pending}
        return None

    def _activation(self, state: Any) -> dict[str, set[str]]:
        if not isinstance(state, dict):
            return ProgressiveMCPRegistry.init_activation_state()
        activation = state.get("mcp_activation")
        if not isinstance(activation, dict):
            activation = ProgressiveMCPRegistry.init_activation_state()
            state["mcp_activation"] = activation
        return activation

    def _disabled_servers(self, state: Any) -> set[str]:
        if not isinstance(state, dict):
            return set()
        disabled = state.get("disabled_mcp_servers", set())
        if not isinstance(disabled, set):
            return set(disabled)
        return disabled

    def _handle_search_mcp_tools(
        self,
        query: str,
        limit: int,
        activation: dict[str, set[str]],
    ) -> str:
        deferred = self._deferred_descriptors or self._registry.deferred_tools()
        matches = self._progressive.search_deferred(query, deferred, limit=limit)
        if not matches:
            return f"No deferred MCP tools matched query={query!r}."
        self._progressive.mark_promoted(activation, [m.name for m in matches])
        try:
            from soothe_nano.mcp.mcp_events import emit_tool_search_queried

            emit_tool_search_queried(query=query, match_count=len(matches))
        except Exception:  # noqa: BLE001
            logger.debug("[MCP] Event emit failed", exc_info=True)
        lines = [f"- {m.name}: {m.description}" for m in matches]
        return (
            f"Promoted {len(matches)} MCP tool(s) for this thread:\n"
            + "\n".join(lines)
            + "\nThey are now available on subsequent model hops."
        )

    def _should_promote_after_invoke(
        self,
        tool_name: str,
        result: ToolMessage | Command[Any],
    ) -> bool:
        if not tool_name or not is_mcp_tool_name(tool_name):
            return False
        if tool_name in self._progressive.always_loaded_names:
            return False
        if tool_name not in self._deferred_names:
            return False
        content = extract_tool_message_content(result)
        return not (content and is_invalid_tool_error(content))

    @staticmethod
    def _command_with_activation(
        result: ToolMessage | Command[Any],
        activation: dict[str, set[str]],
    ) -> Command[Any]:
        update: dict[str, Any] = {"mcp_activation": snapshot_mcp_activation(activation)}
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
        disabled = self._disabled_servers(state)

        if tool_name == _SEARCH_MCP_TOOLS:
            args = tool_call.get("args", {})
            if not isinstance(args, dict):
                args = {}
            query = str(args.get("query", ""))
            limit = int(args.get("limit", 10) or 10)
            content = self._handle_search_mcp_tools(query, limit, activation)
            tool_call_id = str(tool_call.get("id", "") or tool_call.get("tool_call_id", ""))
            message = ToolMessage(
                content=content, tool_call_id=tool_call_id, name=_SEARCH_MCP_TOOLS
            )
            return self._command_with_activation(message, activation)

        if is_mcp_tool_name(tool_name):
            parsed = parse_mcp_tool_name(tool_name)
            if parsed is not None and parsed[0] in disabled:
                tool_call_id = str(tool_call.get("id", "") or tool_call.get("tool_call_id", ""))
                message = ToolMessage(
                    content=f"MCP server {parsed[0]!r} is disabled for this thread.",
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
                return message

        result = await handler(request)

        if self._should_promote_after_invoke(tool_name, result):
            self._progressive.mark_promoted(activation, [tool_name])
            logger.debug("[MCP] Promoted %s after invocation", tool_name)
            return self._command_with_activation(result, activation)

        return result

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        state = getattr(request, "state", None) or {}
        activation = self._activation(state)
        disabled = self._disabled_servers(state)
        tools = getattr(request, "tools", None) or []
        if not self._deferred_descriptors and tools:
            self._deferred_descriptors = self._registry.deferred_tools()
            self._deferred_names = {d.name for d in self._deferred_descriptors}

        bound = self._progressive.bound_tools(tools, activation, disabled_servers=disabled)
        if len(bound) < len(tools):
            promoted_count = len(activation.get("promoted", set()))
            if promoted_count > 0:
                logger.debug(
                    "[MCP] Bound %d/%d tools (always_loaded+promoted=%d)",
                    len(bound),
                    len(tools),
                    promoted_count,
                )
            request = request.override(tools=bound)

        return await handler(request)
