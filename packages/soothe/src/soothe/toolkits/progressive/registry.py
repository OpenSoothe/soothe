"""Progressive builtin-tool registry (mirrors skills/MCP progressive disclosure)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_CORE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # soothe_deepagents filesystem
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        # soothe_deepagents other
        "write_todos",
        "task",
        # soothe surgical file ops
        "delete",
        "edit_lines",
        "insert_lines",
        "delete_lines",
        "apply_diff",
        "file_info",
        # soothe execution
        "run_command",
        "run_python",
        "run_background",
        "tail_background_log",
        "kill_process",
        # soothe datetime
        "current_datetime",
        # progressive discovery
        "search_tools",
        "search_skills",
        "invoke_skill",
        # MCP progressive disclosure (RFC-412)
        "search_mcp_tools",
        "mcp_resources_list",
        "mcp_resources_read",
    }
)


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Descriptor for a deferred builtin tool."""

    name: str
    description: str


def _tool_name(item: Any) -> str | None:
    if isinstance(item, dict):
        raw = item.get("name")
        return str(raw) if raw else None
    return getattr(item, "name", None)


def _tool_description(item: Any) -> str:
    if isinstance(item, dict):
        raw = item.get("description")
        return str(raw or "")
    return str(getattr(item, "description", None) or "")


def _coerce_name_set(value: Any) -> set[str]:
    if isinstance(value, set):
        return {str(v) for v in value}
    if isinstance(value, (list, tuple)):
        return {str(v) for v in value}
    return set()


def snapshot_tool_activation(activation: dict[str, Any]) -> dict[str, set[str]]:
    """Return a graph-safe copy of ``tool_activation`` for ``Command.update``."""
    return {
        "sent": _coerce_name_set(activation.get("sent")),
        "promoted": _coerce_name_set(activation.get("promoted")),
    }


def merge_tool_activation(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, set[str]]:
    """LangGraph reducer: union ``sent`` and ``promoted`` tool-name sets."""
    merged = ProgressiveToolRegistry.init_activation_state()
    for side in (left, right):
        if not isinstance(side, dict):
            continue
        merged["sent"] |= _coerce_name_set(side.get("sent"))
        merged["promoted"] |= _coerce_name_set(side.get("promoted"))
    return merged


class ProgressiveToolRegistry:
    """Stateless facade; activation state lives in graph ``tool_activation``."""

    def __init__(self, core_tools: Iterable[str] | None = None) -> None:
        self._core = frozenset(core_tools) if core_tools else DEFAULT_CORE_TOOL_NAMES

    @property
    def core_tool_names(self) -> frozenset[str]:
        return self._core

    @staticmethod
    def init_activation_state() -> dict[str, set[str]]:
        return {"sent": set(), "promoted": set()}

    def descriptors_from_tools(self, tools: Sequence[Any]) -> list[ToolDescriptor]:
        out: list[ToolDescriptor] = []
        for tool in tools:
            name = _tool_name(tool)
            if not name:
                continue
            out.append(ToolDescriptor(name=name, description=_tool_description(tool)))
        return sorted(out, key=lambda d: d.name.lower())

    def partition(
        self, descriptors: Sequence[ToolDescriptor]
    ) -> tuple[list[ToolDescriptor], list[ToolDescriptor]]:
        core: list[ToolDescriptor] = []
        deferred: list[ToolDescriptor] = []
        for d in descriptors:
            if d.name in self._core:
                core.append(d)
            else:
                deferred.append(d)
        return core, deferred

    def bound_tool_names(self, activation_state: dict[str, Any]) -> set[str]:
        promoted = activation_state.get("promoted", set())
        if not isinstance(promoted, set):
            promoted = set(promoted)
        return set(self._core) | promoted

    def bound_tools(self, tools: Sequence[Any], activation_state: dict[str, Any]) -> list[Any]:
        allowed = self.bound_tool_names(activation_state)
        return [t for t in tools if (_tool_name(t) or "") in allowed]

    def new_for_thread(
        self,
        activation_state: dict[str, Any],
        deferred: Sequence[ToolDescriptor],
    ) -> list[ToolDescriptor]:
        sent = activation_state.get("sent", set())
        if not isinstance(sent, set):
            sent = set(sent)
        promoted = activation_state.get("promoted", set())
        if not isinstance(promoted, set):
            promoted = set(promoted)
        known = {d.name for d in deferred}
        activation_state["sent"] = {n for n in sent if n in known}
        sent = activation_state["sent"]
        return [d for d in deferred if d.name not in sent and d.name not in promoted]

    def mark_sent(self, activation_state: dict[str, Any], names: Iterable[str]) -> None:
        activation_state.setdefault("sent", set()).update(names)

    def mark_promoted(self, activation_state: dict[str, Any], names: Iterable[str]) -> None:
        activation_state.setdefault("promoted", set()).update(names)

    def search_deferred(
        self,
        query: str,
        deferred: Sequence[ToolDescriptor],
        *,
        limit: int = 10,
    ) -> list[ToolDescriptor]:
        q = query.strip().lower()
        if not q:
            return []
        scored: list[tuple[int, ToolDescriptor]] = []
        for d in deferred:
            hay = f"{d.name} {d.description}".lower()
            if q in hay:
                score = hay.index(q)
                scored.append((score, d))
        scored.sort(key=lambda x: (x[0], x[1].name))
        return [d for _, d in scored[:limit]]
