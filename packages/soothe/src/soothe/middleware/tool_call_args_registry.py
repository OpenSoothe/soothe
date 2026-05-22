"""Capture tool-call kwargs at invocation time (provider ``tool_call_id``).

LangGraph may stream only ``ToolMessage`` results without preceding ``AIMessage`` tool
metadata (e.g. some fast-model paths). The registry records args from
``ToolCallRequest`` in middleware before tools run so downstream stream code can
attach them to unified wire ids.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest

_registry: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "tool_call_args_registry",
    default=None,
)


def coerce_tool_call_args(raw: Any) -> dict[str, Any]:
    """Normalize tool-call ``args`` from a request or wire payload."""
    if isinstance(raw, dict):
        inp = raw.get("input")
        if isinstance(inp, dict) and inp:
            return dict(inp)
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def init_tool_call_args_registry() -> None:
    """Reset the per-thread invocation registry (call at execute-wave start)."""
    _registry.set({})


def clear_tool_call_args_registry() -> None:
    """Drop the registry for the current context."""
    _registry.set(None)


def record_tool_call_args_from_request(request: ToolCallRequest) -> None:
    """Store kwargs from an in-flight tool invocation keyed by provider ``tool_call_id``."""
    store = _registry.get()
    if store is None:
        return
    tc = getattr(request, "tool_call", None)
    if not isinstance(tc, dict):
        return
    tid = str(tc.get("id") or "").strip()
    args = coerce_tool_call_args(tc.get("args"))
    if tid and args:
        store[tid] = dict(args)


def get_recorded_tool_call_args(tool_call_id: str) -> dict[str, Any]:
    """Return kwargs recorded at invocation for a provider ``tool_call_id``."""
    store = _registry.get()
    if store is None:
        return {}
    key = str(tool_call_id or "").strip()
    if not key:
        return {}
    stored = store.get(key)
    return dict(stored) if isinstance(stored, dict) else {}


__all__ = [
    "clear_tool_call_args_registry",
    "coerce_tool_call_args",
    "get_recorded_tool_call_args",
    "init_tool_call_args_registry",
    "record_tool_call_args_from_request",
]
