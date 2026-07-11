"""Token usage extraction and estimation helpers for the TUI."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "extract_stream_message_token_usage",
    "fetch_conversation_token_count",
    "message_has_token_usage_metadata",
]


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _usage_from_mapping(usage: dict[str, Any]) -> tuple[int, int, int]:
    """Return ``(input_tokens, output_tokens, total_tokens)`` from a usage dict."""
    input_toks = _coerce_int(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_toks = _coerce_int(usage.get("output_tokens") or usage.get("completion_tokens"))
    total_toks = _coerce_int(usage.get("total_tokens"))
    if not total_toks and (input_toks or output_toks):
        total_toks = input_toks + output_toks
    return input_toks, output_toks, total_toks


def extract_stream_message_token_usage(message: Any) -> tuple[int, int, int]:
    """Extract token usage from a streamed LangChain or wire-format message.

    Providers vary:
    - LangChain ``usage_metadata`` (``input_tokens`` / ``output_tokens``)
    - OpenAI-style ``response_metadata.token_usage`` (``prompt_tokens`` / ``completion_tokens``)
    - Flat wire dicts with either shape
    """
    if message is None:
        return 0, 0, 0

    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict) and usage:
        return _usage_from_mapping(usage)

    response_metadata = getattr(message, "response_metadata", None)
    if isinstance(response_metadata, dict):
        for key in ("token_usage", "usage"):
            nested = response_metadata.get(key)
            if isinstance(nested, dict) and nested:
                return _usage_from_mapping(nested)

    if isinstance(message, dict):
        from soothe_cli.runtime.wire.message_text import wire_message_body

        bodies = [message]
        nested = wire_message_body(message)
        if nested is not message:
            bodies.append(nested)
        for body in bodies:
            if not isinstance(body, dict):
                continue
            direct_usage = body.get("usage_metadata")
            if isinstance(direct_usage, dict) and direct_usage:
                return _usage_from_mapping(direct_usage)
            response = body.get("response_metadata")
            if isinstance(response, dict):
                for key in ("token_usage", "usage"):
                    nested_usage = response.get(key)
                    if isinstance(nested_usage, dict) and nested_usage:
                        return _usage_from_mapping(nested_usage)

    return 0, 0, 0


def message_has_token_usage_metadata(message: Any) -> bool:
    """Return True when a stream message carries provider token usage."""
    input_toks, output_toks, total_toks = extract_stream_message_token_usage(message)
    return bool(input_toks or output_toks or total_toks)


async def fetch_conversation_token_count(daemon_session: Any, loop_id: str | None) -> int | None:
    """Return approximate conversation-only token count from loop checkpoint messages."""
    raw_loop_id = str(loop_id or "").strip()
    if not raw_loop_id or daemon_session is None:
        return None
    try:
        from langchain_core.messages import messages_from_dict
        from langchain_core.messages.utils import count_tokens_approximately

        snap = await daemon_session.aget_loop_state(raw_loop_id)
        vals = getattr(snap, "values", None)
        if not isinstance(vals, dict):
            return None
        raw = vals.get("messages")
        if not isinstance(raw, list) or not raw:
            return None
        if isinstance(raw[0], dict):
            messages = messages_from_dict(raw)
        else:
            messages = raw
        count = count_tokens_approximately(messages)
        return count if count > 0 else None
    except Exception:
        logger.debug(
            "Failed to retrieve conversation token count for loop %s",
            raw_loop_id,
            exc_info=True,
        )
        return None
