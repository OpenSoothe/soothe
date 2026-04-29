"""Tests for IG-301 adaptive LLM per-call timeout."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.middleware.llm_rate_limit import (
    compute_effective_llm_call_timeout,
    estimate_model_request_prompt_chars,
)


def test_compute_effective_non_adaptive() -> None:
    assert (
        compute_effective_llm_call_timeout(
            base_seconds=60,
            max_seconds=600,
            prompt_char_estimate=100_000,
            adaptive=False,
        )
        == 60
    )


def test_compute_effective_adaptive_small_prompt() -> None:
    assert (
        compute_effective_llm_call_timeout(
            base_seconds=60,
            max_seconds=600,
            prompt_char_estimate=200,
            adaptive=True,
        )
        == 60
    )


def test_compute_effective_adaptive_large_prompt() -> None:
    # 75k chars -> +187s over base 60 -> 247
    assert (
        compute_effective_llm_call_timeout(
            base_seconds=60,
            max_seconds=600,
            prompt_char_estimate=75_000,
            adaptive=True,
        )
        == 247
    )


def test_compute_effective_respects_cap() -> None:
    assert (
        compute_effective_llm_call_timeout(
            base_seconds=60,
            max_seconds=120,
            prompt_char_estimate=500_000,
            adaptive=True,
        )
        == 120
    )


def test_estimate_model_request_prompt_chars() -> None:
    from langchain.agents.middleware.types import ModelRequest

    request = ModelRequest(
        model=MagicMock(),
        messages=[
            HumanMessage(content="hello"),
            AIMessage(content=[{"type": "text", "text": "world"}]),
        ],
        system_message=SystemMessage(content="sys"),
    )
    n = estimate_model_request_prompt_chars(request)
    assert n == len("sys") + len("hello") + len("world")
