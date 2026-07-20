"""Unified workspace resolution for tool and agent execution (RFC-103).

Single source of truth for resolving the effective workspace path from LangGraph
runtime, explicit config/state, ContextVar, or static fallbacks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["resolve_workspace_for_tool_execution"]


def _coerce_workspace(value: Any) -> Path | None:
    """Normalize workspace values to ``Path``."""
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    return None


def _workspace_from_configurable(configurable: Any) -> Path | None:
    """Read workspace from a LangGraph ``configurable`` mapping."""
    if not isinstance(configurable, dict):
        return None
    return _coerce_workspace(configurable.get("workspace"))


def _workspace_from_messages(messages: Any) -> Path | None:
    """Scan message history for the most recent workspace hint."""
    if not isinstance(messages, (list, tuple)):
        return None
    for msg in reversed(messages):
        ws = _coerce_workspace(getattr(msg, "workspace", None))
        if ws is not None:
            return ws
        if isinstance(msg, dict):
            additional = msg.get("additional_kwargs")
            if isinstance(additional, dict):
                ws = _coerce_workspace(additional.get("workspace"))
                if ws is not None:
                    return ws
            ws = _coerce_workspace(msg.get("workspace"))
            if ws is not None:
                return ws
    return None


def _workspace_from_state_dict(state: dict[str, Any] | None) -> Path | None:
    """Resolve workspace from graph state (direct key, then messages)."""
    if not isinstance(state, dict):
        return None
    direct = _coerce_workspace(state.get("workspace"))
    if direct is not None:
        return direct
    return _workspace_from_messages(state.get("messages"))


def _runtime_config(runtime: Any) -> dict[str, Any] | None:
    cfg = getattr(runtime, "config", None)
    return cfg if isinstance(cfg, dict) else None


def _runtime_state(runtime: Any) -> dict[str, Any] | None:
    state = getattr(runtime, "state", None)
    return state if isinstance(state, dict) else None


def resolve_workspace_for_tool_execution(
    *,
    runtime: Any | None = None,
    config: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    fallback: str | Path | None = None,
    use_langgraph_config: bool = True,
) -> Path | None:
    """Resolve the effective workspace for the current tool or agent turn.

    Priority (first match wins):

    1. ``config["configurable"]["workspace"]`` (explicit or from ``runtime``)
    2. ``state["workspace"]`` (explicit or from ``runtime``)
    3. Latest message ``workspace`` in ``state["messages"]`` (RFC-103, IG-300)
    4. LangGraph ``get_config()`` configurable (when ``use_langgraph_config=True``)
    5. ``FrameworkFilesystem.get_current_workspace()`` ContextVar
    6. ``fallback`` static path (e.g. daemon default / toolkit ``workspace_root``)

    Args:
        runtime: Optional LangGraph ``ToolRuntime`` (config + state).
        config: Optional RunnableConfig dict.
        state: Optional agent graph state dict.
        fallback: Static fallback when no dynamic workspace is found.
        use_langgraph_config: When True, consult ``langgraph.config.get_config()``.

    Returns:
        Resolved workspace path, or ``None`` if nothing matched and no fallback.
    """
    effective_config = config if config is not None else _runtime_config(runtime)
    effective_state = state if state is not None else _runtime_state(runtime)

    if isinstance(effective_config, dict):
        ws = _workspace_from_configurable(effective_config.get("configurable"))
        if ws is not None:
            return ws

    ws = _workspace_from_state_dict(effective_state)
    if ws is not None:
        return ws

    if use_langgraph_config:
        try:
            from langgraph.config import get_config

            lg_config = get_config()
            if isinstance(lg_config, dict):
                ws = _workspace_from_configurable(lg_config.get("configurable"))
                if ws is not None:
                    return ws
        except Exception:  # noqa: S110
            pass

    from soothe_nano.workspace.framework_filesystem import FrameworkFilesystem

    current = FrameworkFilesystem.get_current_workspace()
    if current is not None:
        return current

    return _coerce_workspace(fallback)
