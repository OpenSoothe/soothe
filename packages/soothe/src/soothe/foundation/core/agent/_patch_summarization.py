"""Runtime patches for deepagents SummarizationMiddleware.

These patches fix upstream issues in SummarizationMiddleware that affect
Soothe's execution performance and correctness.

Note: Do not enable PEP 563 (``from __future__ import annotations``) in this module
when adding patches that use ``inspect.signature`` for runtime type checking.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

_TOOLS_TOKEN_CACHE: dict[str, int] = {}
_SOOTHE_SUMMARIZATION_TOKEN_PATCHED = "_soothe_summarization_token_count_patched"


def _patch_summarization_overwrite_handling() -> None:
    """Patch SummarizationMiddleware for Overwrite wrapper handling.

    SummarizationMiddleware._apply_event_to_messages does not
    handle langgraph's Overwrite wrapper that PatchToolCallsMiddleware may
    leave in request.messages. This patch unwraps it so ``list(messages)`` succeeds.

    This is a temporary workaround until fixed upstream.
    """
    try:
        from deepagents.middleware.summarization import SummarizationMiddleware
        from langgraph.types import Overwrite
    except ImportError:
        return

    _original = SummarizationMiddleware._apply_event_to_messages

    @staticmethod  # type: ignore[misc]
    def _patched(messages: Any, event: Any) -> list[Any]:
        if isinstance(messages, Overwrite):
            messages = messages.value
        return _original(messages, event)

    SummarizationMiddleware._apply_event_to_messages = _patched  # type: ignore[assignment]


def _tools_token_cache_key(tools: list[Any] | None) -> str | None:
    """Build a stable cache key for a tool list."""
    if not tools:
        return None
    parts: list[str] = []
    for tool in tools:
        if isinstance(tool, dict):
            parts.append(json.dumps(tool, sort_keys=True, default=str))
        else:
            name = getattr(tool, "name", None) or ""
            description = getattr(tool, "description", None) or ""
            parts.append(f"{name}:{description}")
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return digest[:32]


def _messages_token_cache_key(messages: Iterable[Any]) -> str:
    """Build a lightweight cache key for message lists."""
    parts: list[str] = []
    for message in messages:
        if message is None:
            parts.append("none")
            continue
        message_id = getattr(message, "id", None) or id(message)
        content = getattr(message, "content", "")
        if isinstance(content, str):
            content_len = len(content)
        elif isinstance(content, list):
            content_len = sum(len(str(block)) for block in content)
        else:
            content_len = len(str(content))
        tool_calls = getattr(message, "tool_calls", None) or ()
        parts.append(f"{message_id}:{content_len}:{len(tool_calls)}")
    return "|".join(parts)


def _cached_tools_token_count(
    token_counter: Any,
    tools: list[Any] | None,
) -> int:
    """Count tool schema tokens once per unique tool set."""
    cache_key = _tools_token_cache_key(tools)
    if cache_key is None:
        return 0
    cached = _TOOLS_TOKEN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        count = token_counter([], tools=tools)
    except TypeError:
        count = 0
    _TOOLS_TOKEN_CACHE[cache_key] = count
    return count


def _split_conversation_token_count(
    token_counter: Any,
    messages: Iterable[Any],
    tools: list[Any] | None,
) -> int:
    """Count message and tool tokens separately; cache tool schemas globally."""
    tools_tokens = _cached_tools_token_count(token_counter, tools)
    try:
        message_tokens = token_counter(messages, tools=None)
    except TypeError:
        message_tokens = token_counter(messages)
    return tools_tokens + message_tokens


def _patch_summarization_token_count_optimization() -> None:
    """Speed up SummarizationMiddleware pre-model token counting.

    Upstream ``awrap_model_call`` counts tokens twice per model call (in
    ``_truncate_args`` and again before ``_should_summarize``), and each count
    re-serializes every tool schema. For large tool sets this dominates the
    Langfuse ``model`` span gap (~12s in recent loops).
    """
    try:
        from deepagents.middleware.summarization import SummarizationMiddleware
    except ImportError:
        return

    if getattr(SummarizationMiddleware, _SOOTHE_SUMMARIZATION_TOKEN_PATCHED, False):
        return

    _original_init = SummarizationMiddleware.__init__
    _original_truncate_args = SummarizationMiddleware._truncate_args
    _original_wrap_model_call = SummarizationMiddleware.wrap_model_call
    _original_awrap_model_call = SummarizationMiddleware.awrap_model_call

    def _wrap_token_counter(self: Any, token_counter: Any) -> Any:
        def wrapped_counter(
            messages: Iterable[Any],
            tools: list[Any] | None = None,
        ) -> int:
            per_call_cache = getattr(self, "_soothe_token_count_cache", None)
            cache_key = (_messages_token_cache_key(messages), _tools_token_cache_key(tools))
            if per_call_cache is not None and cache_key in per_call_cache:
                return per_call_cache[cache_key]

            total = _split_conversation_token_count(token_counter, messages, tools)
            if per_call_cache is not None:
                per_call_cache[cache_key] = total
            return total

        return wrapped_counter

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        _original_init(self, *args, **kwargs)
        original_counter = self._lc_helper.token_counter
        self._lc_helper.token_counter = _wrap_token_counter(self, original_counter)

    def patched_truncate_args(
        self: Any,
        messages: list[Any],
        total_tokens: int,
    ) -> tuple[list[Any], bool]:
        truncate_trigger = getattr(self, "_truncate_args_trigger", None)
        if truncate_trigger is not None:
            trigger_type, trigger_value = truncate_trigger
            if trigger_type == "messages" and len(messages) < trigger_value:
                return messages, False

        return _original_truncate_args(self, messages, total_tokens)

    def patched_wrap_model_call(self: Any, request: Any, handler: Any) -> Any:
        self._soothe_token_count_cache = {}
        try:
            return _original_wrap_model_call(self, request, handler)
        finally:
            self._soothe_token_count_cache = {}

    async def patched_awrap_model_call(self: Any, request: Any, handler: Any) -> Any:
        self._soothe_token_count_cache = {}
        try:
            return await _original_awrap_model_call(self, request, handler)
        finally:
            self._soothe_token_count_cache = {}

    SummarizationMiddleware.__init__ = patched_init  # type: ignore[method-assign]
    SummarizationMiddleware._truncate_args = patched_truncate_args  # type: ignore[method-assign]
    SummarizationMiddleware.wrap_model_call = patched_wrap_model_call  # type: ignore[method-assign]
    SummarizationMiddleware.awrap_model_call = patched_awrap_model_call  # type: ignore[method-assign]
    setattr(SummarizationMiddleware, _SOOTHE_SUMMARIZATION_TOKEN_PATCHED, True)


def apply_summarization_patches() -> None:
    """Apply all SummarizationMiddleware patches."""
    _patch_summarization_overwrite_handling()
    _patch_summarization_token_count_optimization()


__all__ = [
    "apply_summarization_patches",
    "_patch_summarization_overwrite_handling",
    "_patch_summarization_token_count_optimization",
    "_tools_token_cache_key",
    "_TOOLS_TOKEN_CACHE",
    "_cached_tools_token_count",
    "_split_conversation_token_count",
]
