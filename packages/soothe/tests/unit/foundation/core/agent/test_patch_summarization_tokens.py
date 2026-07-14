"""Tests for SummarizationMiddleware token-count optimization patch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.foundation.core.agent._patch_summarization import (
    _TOOLS_TOKEN_CACHE,
    _cached_tools_token_count,
    _split_conversation_token_count,
    _tools_token_cache_key,
)


def test_tools_token_cache_key_is_stable() -> None:
    tools = [{"name": "ls", "description": "list files"}]
    assert _tools_token_cache_key(tools) == _tools_token_cache_key(tools)


def test_cached_tools_token_count_counts_once() -> None:
    _TOOLS_TOKEN_CACHE.clear()
    counter = MagicMock(side_effect=[99, 99])

    first = _cached_tools_token_count(counter, [{"name": "a"}])
    second = _cached_tools_token_count(counter, [{"name": "a"}])

    assert first == 99
    assert second == 99
    assert counter.call_count == 1


def test_split_conversation_token_count_adds_messages_and_tools() -> None:
    _TOOLS_TOKEN_CACHE.clear()

    def counter(messages, tools=None):
        if tools is not None:
            return 100
        return sum(len(str(getattr(m, "content", ""))) for m in messages)

    total = _split_conversation_token_count(
        counter,
        [MagicMock(content="abc")],
        [{"name": "tool"}],
    )
    assert total == 103


def test_truncate_args_skips_token_count_for_message_trigger() -> None:
    pytest.importorskip("soothe_deepagents")
    from soothe_deepagents.middleware.summarization import SummarizationMiddleware

    middleware = MagicMock()
    middleware._truncate_args_trigger = ("messages", 20)
    messages = [MagicMock()]

    result_messages, modified = SummarizationMiddleware._truncate_args(
        middleware,
        messages,
        1000,  # total_tokens (new signature)
    )

    assert result_messages is messages
    assert modified is False
