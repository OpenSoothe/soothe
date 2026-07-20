"""Deterministic tool-call optimization middleware for execute scopes.

Owns lookup reuse/dedup and search-consolidation controls while keeping
step lifecycle semantics in the executor.
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

from soothe_nano.middleware.tool_call_args_registry import coerce_tool_call_args

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.types import Command

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
_NATIVE_SEARCH_TOOLS = frozenset({"glob", "grep"})


@dataclass(slots=True)
class _ToolReuseState:
    """Per-execution-scope deterministic tool lookup reuse state."""

    scope_id: str = ""
    cache: dict[str, tuple[Any, str | None]] = field(default_factory=dict)
    last_signature: str | None = None
    repeated_signature_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    duplicate_signature_blocked: int = 0
    native_search_calls: int = 0
    shell_search_fallback_blocked: int = 0


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


def _tool_message_text(result: Any) -> str:
    """Extract best-effort textual body from a ToolMessage-like result."""
    if not isinstance(result, ToolMessage):
        return str(result)
    content = result.content
    if isinstance(content, str):
        return content
    return str(content)


def _tool_result_has_actionable_output(result: Any) -> bool:
    """True when tool output contains actionable non-error content."""
    text = _tool_message_text(result).strip()
    if not text:
        return False
    lowered = text.lower()
    # Deterministic structural signals from tool output shape.
    if lowered.startswith("error:"):
        return False
    if "no files found" in lowered:
        return False
    if "no matches found" in lowered:
        return False
    if "0 matches" in lowered:
        return False
    if text in ("[]", "{}", "None"):
        return False
    return True


def _scope_metrics(state: _ToolReuseState) -> dict[str, int]:
    """Expose current deterministic reuse metrics for executor telemetry."""
    return {
        "repeated_signature_calls": int(state.repeated_signature_calls),
        "cache_hits": int(state.cache_hits),
        "cache_misses": int(state.cache_misses),
        "duplicate_signature_blocked": int(state.duplicate_signature_blocked),
        "native_search_calls": int(state.native_search_calls),
        "shell_search_fallback_blocked": int(state.shell_search_fallback_blocked),
    }


def get_tool_reuse_metrics_snapshot() -> dict[str, int]:
    """Return per-scope tool reuse metrics from current async context."""
    state = _tool_reuse_state.get()
    if state is None:
        return {
            "repeated_signature_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "duplicate_signature_blocked": 0,
            "native_search_calls": 0,
            "shell_search_fallback_blocked": 0,
        }
    return _scope_metrics(state)


class ToolOptimizationMiddleware(AgentMiddleware):
    """Deterministic tool-call optimization middleware.

    Controls:
    - Lookup cache for deterministic same-args reuse.
    - Duplicate empty-result replay blocking.
    - Native-search-first policy before shell grep fallback.
    """

    name = "ToolOptimizationMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
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
            state.duplicate_signature_blocked = 0
            state.native_search_calls = 0
            state.shell_search_fallback_blocked = 0

        if tool_name in _NATIVE_SEARCH_TOOLS:
            state.native_search_calls += 1

        if tool_name == "run_command" and state.native_search_calls > 0:
            command = str(tool_args.get("command") or "")
            normalized = command.lower()
            if "grep" in normalized or "rg " in normalized or normalized.startswith("rg"):
                state.shell_search_fallback_blocked += 1
                logger.debug(
                    "[ToolOptimization] blocked shell search fallback scope=%s native_search_calls=%d",
                    scope_id,
                    state.native_search_calls,
                )
                return ToolMessage(
                    content=(
                        "Search consolidation: native search tools already ran in this step scope. "
                        "Reuse those results or broaden native grep/glob arguments instead of "
                        "running an equivalent shell search fallback."
                    ),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    status="error",
                )

        signature: str | None = None
        if tool_name in _CACHEABLE_LOOKUP_TOOLS:
            signature = f"{tool_name}:{_normalize_args_for_signature(tool_args)}"
            if signature == state.last_signature:
                state.repeated_signature_calls += 1
            cached = state.cache.get(signature)
            if cached is not None:
                state.cache_hits += 1
                cached_content, cached_status = cached
                cached_msg = ToolMessage(
                    content=cached_content,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    status=cached_status,
                )
                if signature == state.last_signature and not _tool_result_has_actionable_output(
                    cached_msg
                ):
                    state.duplicate_signature_blocked += 1
                    logger.debug(
                        "[ToolOptimization] blocked duplicate empty signature scope=%s tool=%s blocked=%d",
                        scope_id,
                        tool_name,
                        state.duplicate_signature_blocked,
                    )
                    return ToolMessage(
                        content=(
                            "Duplicate lookup blocked: the same tool call with identical arguments "
                            "already returned no actionable result in this step scope. "
                            "Change arguments (path/glob/pattern/offset) before retrying."
                        ),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        status="error",
                    )
                logger.debug(
                    "[ToolOptimization] cache hit scope=%s tool=%s hits=%d repeated=%d",
                    scope_id,
                    tool_name,
                    state.cache_hits,
                    state.repeated_signature_calls,
                )
                return cached_msg
            state.cache_misses += 1

        result = await handler(request)

        if tool_name in _CACHE_INVALIDATING_TOOLS:
            state.cache.clear()
            state.last_signature = None
            return result

        if signature is not None and isinstance(result, ToolMessage):
            state.last_signature = signature
            state.cache[signature] = (
                result.content,
                getattr(result, "status", None),
            )

        return result


__all__ = ["ToolOptimizationMiddleware", "get_tool_reuse_metrics_snapshot"]
