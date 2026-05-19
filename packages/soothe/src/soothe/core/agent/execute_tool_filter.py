"""Remove deepagents ``execute`` when command sandbox is off.

``create_deep_agent`` registers ``execute`` only when a sandbox-capable backend is
available. ``security.sandbox`` gates whether that tool is advertised to the model.

Host-execution tools (``run_command``, ``run_python``, ``run_background``,
``kill_process``) are NOT filtered here — they run on the host via subprocess
and do not require a sandbox backend. They are always resolved in
``_resolver_tools.py`` regardless of the sandbox flag.
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
