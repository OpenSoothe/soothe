"""MCP progressive activation state and discovery tool."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from soothe_nano.mcp.mcp_utils import MCPToolDescriptor, is_mcp_tool_name, parse_mcp_tool_name


def _coerce_name_set(value: Any) -> set[str]:
    if isinstance(value, set):
        return {str(v) for v in value}
    if isinstance(value, (list, tuple)):
        return {str(v) for v in value}
    return set()


def snapshot_mcp_activation(activation: dict[str, Any]) -> dict[str, set[str]]:
    """Return a graph-safe copy of mcp_activation for Command.update."""
    return {
        "sent": _coerce_name_set(activation.get("sent")),
        "promoted": _coerce_name_set(activation.get("promoted")),
    }


def merge_mcp_activation(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, set[str]]:
    """LangGraph reducer: union sent and promoted MCP tool-name sets."""
    merged = ProgressiveMCPRegistry.init_activation_state()
    for side in (left, right):
        if not isinstance(side, dict):
            continue
        merged["sent"] |= _coerce_name_set(side.get("sent"))
        merged["promoted"] |= _coerce_name_set(side.get("promoted"))
    return merged


def _tool_name(item: Any) -> str | None:
    if isinstance(item, dict):
        raw = item.get("name")
        return str(raw) if raw else None
    return getattr(item, "name", None)


class ProgressiveMCPRegistry:
    """Stateless facade; activation state lives in graph mcp_activation."""

    def __init__(self, always_loaded_names: Iterable[str] | None = None) -> None:
        self._always_loaded = frozenset(always_loaded_names or ())

    @property
    def always_loaded_names(self) -> frozenset[str]:
        return self._always_loaded

    @staticmethod
    def init_activation_state() -> dict[str, set[str]]:
        return {"sent": set(), "promoted": set()}

    def bound_tool_names(self, activation_state: dict[str, Any]) -> set[str]:
        promoted = activation_state.get("promoted", set())
        if not isinstance(promoted, set):
            promoted = set(promoted)
        return set(self._always_loaded) | promoted

    def bound_tools(
        self,
        tools: Sequence[Any],
        activation_state: dict[str, Any],
        *,
        disabled_servers: set[str] | None = None,
    ) -> list[Any]:
        allowed = self.bound_tool_names(activation_state)
        disabled = disabled_servers or set()
        bound: list[Any] = []
        for tool in tools:
            name = _tool_name(tool) or ""
            if not is_mcp_tool_name(name):
                bound.append(tool)
                continue
            parsed = parse_mcp_tool_name(name)
            if parsed is not None and parsed[0] in disabled:
                continue
            if name in allowed:
                bound.append(tool)
        return bound

    def new_for_thread(
        self,
        activation_state: dict[str, Any],
        deferred: Sequence[MCPToolDescriptor],
    ) -> list[MCPToolDescriptor]:
        sent = activation_state.get("sent", set())
        if not isinstance(sent, set):
            sent = set(sent)
        promoted = activation_state.get("promoted", set())
        if not isinstance(promoted, set):
            promoted = set(promoted)
        known = {descriptor.name for descriptor in deferred}
        activation_state["sent"] = {name for name in sent if name in known}
        sent = activation_state["sent"]
        return [
            descriptor
            for descriptor in deferred
            if descriptor.name not in sent and descriptor.name not in promoted
        ]

    def mark_sent(self, activation_state: dict[str, Any], names: Iterable[str]) -> None:
        activation_state.setdefault("sent", set()).update(names)

    def mark_promoted(self, activation_state: dict[str, Any], names: Iterable[str]) -> None:
        activation_state.setdefault("promoted", set()).update(names)

    def search_deferred(
        self,
        query: str,
        deferred: Sequence[MCPToolDescriptor],
        *,
        limit: int = 10,
    ) -> list[MCPToolDescriptor]:
        q = query.strip().lower()
        if not q:
            return []
        scored: list[tuple[int, MCPToolDescriptor]] = []
        for descriptor in deferred:
            hay = (
                f"{descriptor.name} {descriptor.bare_name} "
                f"{descriptor.description} {descriptor.server}"
            ).lower()
            if q in hay:
                scored.append((hay.index(q), descriptor))
        scored.sort(key=lambda pair: (pair[0], pair[1].name))
        return [descriptor for _, descriptor in scored[:limit]]


class SearchMcpToolsInput(BaseModel):
    """Input schema for search_mcp_tools."""

    query: str = Field(
        description="Substring to match deferred MCP tool names, servers, or descriptions"
    )
    limit: int = Field(default=10, ge=1, le=50, description="Maximum matches to return")


def create_search_mcp_tools_tool() -> StructuredTool:
    """Return search_mcp_tools stub; discovery is handled by MCPActivationMiddleware."""

    def _search_mcp_tools(query: str, limit: int = 10) -> str:
        return (
            "search_mcp_tools is handled by MCPActivationMiddleware. "
            f"Query={query!r} limit={limit}."
        )

    return StructuredTool.from_function(
        func=_search_mcp_tools,
        name="search_mcp_tools",
        description=(
            "Search deferred MCP tools by server name, tool name, or description. "
            "Returns matches and promotes them for subsequent model hops. "
            "Use exact mangled names (mcp__server__tool) when calling."
        ),
        args_schema=SearchMcpToolsInput,
    )
