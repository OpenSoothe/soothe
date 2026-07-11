"""Loop-scoped token usage helpers for StrangeLoop state."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import LLMResult

    from soothe.foundation.sloop.state.schemas import LoopState


class _TokenTotalTarget(Protocol):
    total_tokens_used: int


@dataclass
class DirectLLMTokenTarget:
    """Mutable token sink used before ``LoopState`` exists (e.g. pre-graph Pass 1)."""

    total_tokens_used: int = 0


_loop_token_target: ContextVar[_TokenTotalTarget | None] = ContextVar(
    "loop_token_target",
    default=None,
)
_direct_llm_token_accumulation: ContextVar[bool] = ContextVar(
    "direct_llm_token_accumulation",
    default=False,
)


@contextmanager
def loop_token_accumulation_scope(target: _TokenTotalTarget):
    """Bind loop token accumulation to ``target`` for the current async context."""
    token = _loop_token_target.set(target)
    try:
        yield
    finally:
        _loop_token_target.reset(token)


@contextmanager
def direct_llm_token_call_scope():
    """Mark the current call as a direct (non-CoreAgent) LLM invocation."""
    token = _direct_llm_token_accumulation.set(True)
    try:
        yield
    finally:
        _direct_llm_token_accumulation.reset(token)


def merge_direct_llm_tokens_into_state(
    state: LoopState,
    source: _TokenTotalTarget,
) -> int:
    """Fold tokens accumulated before ``LoopState`` existed into ``state``."""
    delta = max(0, int(getattr(source, "total_tokens_used", 0) or 0))
    if delta > 0:
        state.total_tokens_used += delta
    return delta


def accumulate_loop_tokens_from_llm_result(response: LLMResult) -> int:
    """Add direct LLM usage into the active loop token target when scoped."""
    if not _direct_llm_token_accumulation.get():
        return 0
    target = _loop_token_target.get()
    if target is None:
        return 0
    from soothe.utils.llm.observability import extract_token_counts_from_llm_result

    counts = extract_token_counts_from_llm_result(response)
    if not counts:
        return 0
    delta = int(counts.get("total_tokens") or 0)
    if delta <= 0:
        delta = int(counts.get("input_tokens") or 0) + int(counts.get("output_tokens") or 0)
    if delta <= 0:
        return 0
    target.total_tokens_used += delta
    return delta


def extract_token_usage_from_messages(messages: list[BaseMessage]) -> dict[str, int]:
    """Return prompt/completion/total token counts from the latest AI message."""
    from langchain_core.messages import AIMessage, AIMessageChunk

    for msg in reversed(messages):
        if not isinstance(msg, (AIMessage, AIMessageChunk)):
            continue
        usage = getattr(msg, "usage_metadata", None)
        if isinstance(usage, dict) and usage:
            prompt = int(usage.get("input_tokens") or 0)
            completion = int(usage.get("output_tokens") or 0)
            total = int(usage.get("total_tokens") or 0) or prompt + completion
            if total > 0:
                return {"prompt": prompt, "completion": completion, "total": total}
        metadata = getattr(msg, "response_metadata", None) or {}
        if isinstance(metadata, dict):
            token_usage = metadata.get("token_usage")
            if isinstance(token_usage, dict) and token_usage:
                prompt = int(
                    token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
                )
                completion = int(
                    token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
                )
                total = int(token_usage.get("total_tokens") or 0) or prompt + completion
                if total > 0:
                    return {"prompt": prompt, "completion": completion, "total": total}
    return {}


def accumulate_loop_tokens_from_messages(
    state: LoopState,
    messages: list[BaseMessage],
    *,
    output_fallback: str = "",
) -> int:
    """Add token usage from CoreAgent messages into ``state.total_tokens_used``."""
    usage = extract_token_usage_from_messages(messages)
    if usage.get("total"):
        delta = int(usage["total"])
        state.total_tokens_used += delta
        return delta
    if output_fallback:
        from soothe.utils.token_counting import count_tokens

        delta = count_tokens(output_fallback)
        if delta > 0:
            state.total_tokens_used += delta
            return delta
    return 0


def coerce_total_tokens_used(value: Any) -> int:
    """Parse a non-negative ``total_tokens_used`` field from event payloads."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "DirectLLMTokenTarget",
    "accumulate_loop_tokens_from_llm_result",
    "accumulate_loop_tokens_from_messages",
    "coerce_total_tokens_used",
    "direct_llm_token_call_scope",
    "extract_token_usage_from_messages",
    "loop_token_accumulation_scope",
    "merge_direct_llm_tokens_into_state",
]
