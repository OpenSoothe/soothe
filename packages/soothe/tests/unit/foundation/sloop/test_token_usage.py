"""Tests for loop-scoped token usage helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.outputs import LLMResult

from soothe.foundation.sloop.utils.token_usage import (
    DirectLLMTokenTarget,
    accumulate_loop_tokens_from_llm_result,
    coerce_total_tokens_used,
    direct_llm_token_call_scope,
    loop_token_accumulation_scope,
    merge_direct_llm_tokens_into_state,
)


def test_coerce_total_tokens_used_parses_and_clamps() -> None:
    assert coerce_total_tokens_used("42") == 42
    assert coerce_total_tokens_used(-5) == 0
    assert coerce_total_tokens_used("bad") == 0


def test_merge_direct_llm_tokens_into_state() -> None:
    state = SimpleNamespace(total_tokens_used=100)
    sink = DirectLLMTokenTarget(total_tokens_used=250)
    delta = merge_direct_llm_tokens_into_state(state, sink)
    assert delta == 250
    assert state.total_tokens_used == 350


def test_accumulate_loop_tokens_from_llm_result_requires_direct_scope() -> None:
    target = DirectLLMTokenTarget()
    response = MagicMock(spec=LLMResult)
    assert accumulate_loop_tokens_from_llm_result(response) == 0

    with loop_token_accumulation_scope(target), direct_llm_token_call_scope():
        with patch(
            "soothe.utils.llm.observability.extract_token_counts_from_llm_result",
            return_value={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        ):
            delta = accumulate_loop_tokens_from_llm_result(response)

    assert delta == 15
    assert target.total_tokens_used == 15
