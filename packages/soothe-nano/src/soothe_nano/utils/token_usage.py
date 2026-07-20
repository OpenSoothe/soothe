"""Token usage helpers for CoreAgent and direct LLM calls."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import LLMResult


class _TokenTotalTarget(Protocol):
    total_tokens_used: int


@dataclass
class DirectLLMTokenTarget:
    """Mutable token sink for direct (non-CoreAgent-graph) LLM invocations."""

    total_tokens_used: int = 0


_token_target: ContextVar[_TokenTotalTarget | None] = ContextVar(
    "token_target",
    default=None,
)
_direct_llm_token_accumulation: ContextVar[bool] = ContextVar(
    "direct_llm_token_accumulation",
    default=False,
)


@contextmanager
def loop_token_accumulation_scope(target: _TokenTotalTarget):
    """Bind token accumulation to ``target`` for the current async context."""
    token = _token_target.set(target)
    try:
        yield
    finally:
        _token_target.reset(token)


@contextmanager
def direct_llm_token_call_scope():
    """Mark the current call as a direct (non-CoreAgent) LLM invocation."""
    token = _direct_llm_token_accumulation.set(True)
    try:
        yield
    finally:
        _direct_llm_token_accumulation.reset(token)


def merge_direct_llm_tokens_into_state(
    state: _TokenTotalTarget,
    source: _TokenTotalTarget,
) -> int:
    """Fold tokens accumulated before state existed into ``state``."""
    delta = max(0, int(getattr(source, "total_tokens_used", 0) or 0))
    if delta > 0:
        state.total_tokens_used += delta
    return delta


def accumulate_loop_tokens_from_llm_result(response: LLMResult) -> int:
    """Add direct LLM usage into the active token target when scoped."""
    if not _direct_llm_token_accumulation.get():
        return 0
    target = _token_target.get()
    if target is None:
        return 0
    from soothe_nano.utils.llm.observability import extract_token_counts_from_llm_result

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


def _token_counts_from_ai_message(msg: BaseMessage) -> dict[str, int] | None:
    """Return prompt/completion/total for one AI message when usage metadata is present."""
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
            prompt = int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0)
            completion = int(
                token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
            )
            total = int(token_usage.get("total_tokens") or 0) or prompt + completion
            if total > 0:
                return {"prompt": prompt, "completion": completion, "total": total}
    return None


def _sum_token_usage_from_messages(
    messages: list[BaseMessage],
    *,
    include_chunks: bool,
) -> dict[str, int]:
    """Sum usage across AI messages (optionally including stream chunks)."""
    from langchain_core.messages import AIMessage, AIMessageChunk

    prompt = completion = total = 0
    for msg in messages:
        if isinstance(msg, AIMessage):
            counts = _token_counts_from_ai_message(msg)
        elif include_chunks and isinstance(msg, AIMessageChunk):
            counts = _token_counts_from_ai_message(msg)
        else:
            continue
        if counts is None:
            continue
        prompt += counts["prompt"]
        completion += counts["completion"]
        total += counts["total"]
    if total <= 0:
        return {}
    return {"prompt": prompt, "completion": completion, "total": total}


def extract_token_usage_from_messages(messages: list[BaseMessage]) -> dict[str, int]:
    """Sum prompt/completion/total across all CoreAgent AI turns in ``messages``."""
    usage = _sum_token_usage_from_messages(messages, include_chunks=False)
    if usage:
        return usage
    return _sum_token_usage_from_messages(messages, include_chunks=True)


def coerce_total_tokens_used(value: Any) -> int:
    """Parse a non-negative ``total_tokens_used`` field from event payloads."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "DirectLLMTokenTarget",
    "accumulate_loop_tokens_from_llm_result",
    "coerce_total_tokens_used",
    "direct_llm_token_call_scope",
    "extract_token_usage_from_messages",
    "loop_token_accumulation_scope",
    "merge_direct_llm_tokens_into_state",
]
