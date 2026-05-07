"""Remove deepagents ``execute`` when command sandbox is off (IG-sandbox).

``create_deep_agent`` registers ``execute`` only when a sandbox-capable backend is
available. Soothe's default filesystem backend does not implement command execution;
``security.sandbox`` gates whether that tool is advertised to the model.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

_T = TypeVar("_T")


def tool_entry_name(item: Any) -> str | None:
    """Best-effort tool name for list entries passed to agent factories."""
    if isinstance(item, dict):
        return item.get("name") if isinstance(item.get("name"), str) else None
    return getattr(item, "name", None)


def without_execute_tool_when_sandbox_disabled(
    items: Sequence[_T],
    *,
    security_sandbox_enabled: bool,
) -> list[_T]:
    """Return a shallow copy, dropping tools named ``execute`` when sandbox is disabled.

    Args:
        items: Tool objects, callables, or dict specs with a ``name`` key.
        security_sandbox_enabled: ``SootheConfig.security.sandbox``.

    Returns:
        Filtered list suitable for ``create_deep_agent(tools=...)`` and similar.
    """
    if security_sandbox_enabled:
        return list(items)
    return [t for t in items if tool_entry_name(t) != "execute"]
