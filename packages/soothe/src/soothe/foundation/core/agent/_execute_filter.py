"""Remove deepagents ``execute`` from agent tool surfaces.

Soothe uses host execution tools (``run_command``, ``run_python``,
``run_background``, ``tail_background_log``, ``kill_process``) instead of
deepagents' sandbox-backed ``execute`` tool.

``create_deep_agent`` and ``FilesystemMiddleware`` register ``execute`` by
default; this module strips it at build time and via a runtime patch on
``FilesystemMiddleware`` initialization.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

_T = TypeVar("_T")

_DEEPAGENTS_EXECUTE_TOOL = "execute"


def tool_entry_name(item: Any) -> str | None:
    """Best-effort tool name for list entries passed to agent factories."""
    if isinstance(item, dict):
        return item.get("name") if isinstance(item.get("name"), str) else None
    return getattr(item, "name", None)


def without_deepagents_execute_tool(items: Sequence[_T]) -> list[_T]:
    """Return a shallow copy with deepagents ``execute`` removed."""
    return [t for t in items if tool_entry_name(t) != _DEEPAGENTS_EXECUTE_TOOL]


def _patch_filesystem_middleware_strips_execute() -> None:
    """Strip ``execute`` from ``FilesystemMiddleware.tools`` after init."""
    try:
        from deepagents.middleware.filesystem import FilesystemMiddleware
    except ImportError:
        return

    if getattr(FilesystemMiddleware.__init__, "_soothe_no_execute_patched", False):
        return

    original_init = FilesystemMiddleware.__init__

    def patched_init(self, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.tools = [t for t in self.tools if getattr(t, "name", None) != _DEEPAGENTS_EXECUTE_TOOL]

    patched_init._soothe_no_execute_patched = True  # type: ignore[attr-defined]
    FilesystemMiddleware.__init__ = patched_init  # type: ignore[method-assign]


def apply_execute_tool_removal_patch() -> None:
    """Apply patches that keep deepagents ``execute`` off agent tool catalogs."""
    _patch_filesystem_middleware_strips_execute()


__all__ = [
    "apply_execute_tool_removal_patch",
    "tool_entry_name",
    "without_deepagents_execute_tool",
]
