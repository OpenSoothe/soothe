"""Tool call args recording middleware (IG-519).

Lightweight middleware that captures tool-call kwargs for display purposes.
Extracted from ToolConcurrencyMiddleware when the semaphore functionality
was removed (limit=64 was ineffective).
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.middleware.tool_call_args_registry import (
    coerce_tool_call_args,
    record_tool_call_args_from_request,
)

logger = logging.getLogger(__name__)

_CACHEABLE_LOOKUP_TOOLS = frozenset({"read_file", "glob", "grep"})
_CACHE_INVALIDATING_TOOLS = frozenset(
    {
        "edit_file",
        "edit_lines",
        "insert_lines",
        "delete_lines",
        "write_file",
        "move_file",
        "delete_file",
        "run_command",
        "run_python",
    }
)


@dataclass(slots=True)
class _ToolReuseState:
    """Per-execution-scope deterministic tool lookup reuse state."""

    scope_id: str = ""
    cache: dict[str, tuple[Any, str | None]] = field(default_factory=dict)
    last_signature: str | None = None
    repeated_signature_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


_tool_reuse_state: ContextVar[_ToolReuseState | None] = ContextVar(
    "tool_reuse_state",
    default=None,
)


def _runtime_config_from_request(request: ToolCallRequest) -> dict[str, Any]:
    runtime = getattr(request, "runtime", None)
    cfg = getattr(runtime, "config", None)
    return cfg if isinstance(cfg, dict) else {}


def _scope_id_for_request(request: ToolCallRequest) -> str:
    """Build a deterministic scope id for per-step lookup reuse cache."""
    cfg = _runtime_config_from_request(request)
    configurable = cfg.get("configurable", {})
    if not isinstance(configurable, dict):
        configurable = {}
    thread_id = str(configurable.get("thread_id") or "")
    checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
    return f"{thread_id}:{checkpoint_ns}"


def _normalize_args_for_signature(args: dict[str, Any]) -> str:
    """Canonical JSON for deterministic signature matching."""
    try:
        return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except TypeError:
        return str(args)


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.types import Command


class ToolCallArgsMiddleware(AgentMiddleware):
    """Middleware that records tool call args for display purposes.

    Captures kwargs from ToolCallRequest at invocation time so downstream
    stream code can attach them to unified wire ids (subagent display).

    This is a lightweight replacement for ToolConcurrencyMiddleware's
    registry functionality, without the ineffective semaphore (IG-519).
    """

    name = "ToolCallArgsMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Record tool call args before execution.

        Args:
            request: The tool call request.
            handler: The next handler (actual tool execution).

        Returns:
            Tool execution result.
        """
        # Fast path: skip recording for batched operations (IG-517)
        metadata = getattr(request, "metadata", None) or {}
        if metadata.get("_batched"):
            return await handler(request)

        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name") or "").strip()
        tool_args = coerce_tool_call_args(tool_call.get("args"))
        tool_call_id = str(tool_call.get("id") or "")

        state = _tool_reuse_state.get()
        if state is None:
            state = _ToolReuseState()
            _tool_reuse_state.set(state)
        scope_id = _scope_id_for_request(request)
        if state.scope_id != scope_id:
            state.scope_id = scope_id
            state.cache.clear()
            state.last_signature = None
            state.repeated_signature_calls = 0
            state.cache_hits = 0
            state.cache_misses = 0

        record_tool_call_args_from_request(request)

        signature: str | None = None
        if tool_name in _CACHEABLE_LOOKUP_TOOLS:
            signature = f"{tool_name}:{_normalize_args_for_signature(tool_args)}"
            if signature == state.last_signature:
                state.repeated_signature_calls += 1
            cached = state.cache.get(signature)
            if cached is not None:
                state.cache_hits += 1
                cached_content, cached_status = cached
                logger.debug(
                    "[ToolReuse] cache hit scope=%s tool=%s hits=%d repeated=%d",
                    scope_id,
                    tool_name,
                    state.cache_hits,
                    state.repeated_signature_calls,
                )
                return ToolMessage(
                    content=cached_content,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    status=cached_status,
                )
            state.cache_misses += 1

        result = await handler(request)

        if tool_name in _CACHE_INVALIDATING_TOOLS:
            state.cache.clear()
            state.last_signature = None
            return result

        if signature is not None:
            state.last_signature = signature
            if isinstance(result, ToolMessage):
                state.cache[signature] = (
                    result.content,
                    getattr(result, "status", None),
                )

        return result


__all__ = ["ToolCallArgsMiddleware"]
