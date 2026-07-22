"""Unit tests for execute-step completion cognition summaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from soothe.sloop.cognition.step_completion_report import (
    summarize_step_completion_report,
)


@pytest.mark.asyncio
async def test_summarize_step_completion_report_returns_llm_text() -> None:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content="I finished reviewing the API docs."))

    result = await summarize_step_completion_report(
        human_content="EXECUTION TASK:\nReview API docs",
        ai_content="Here is the API summary.",
        fast_model=model,
        max_words=50,
    )

    assert result == "I finished reviewing the API docs."
    messages = model.ainvoke.await_args.args[0]
    assert len(messages) == 3
    assert "at most 50 words" in messages[0].content
    assert messages[1].content == "EXECUTION TASK:\nReview API docs"
    assert messages[2].content == "Here is the API summary."


@pytest.mark.asyncio
async def test_summarize_step_completion_report_does_not_truncate_over_limit() -> None:
    long_text = " ".join(f"word{i}" for i in range(60))
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content=long_text))

    result = await summarize_step_completion_report(
        human_content="EXECUTION TASK:\ndo work",
        ai_content="done",
        fast_model=model,
        max_words=50,
    )

    assert result == long_text


@pytest.mark.asyncio
async def test_summarize_step_completion_report_uses_config_word_limit() -> None:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content="I finished the step."))
    config = MagicMock()
    config.agent.loop.step_completion_report_max_words = 50

    await summarize_step_completion_report(
        human_content="EXECUTION TASK:\ndo work",
        ai_content="done",
        fast_model=model,
        soothe_config=config,
    )

    messages = model.ainvoke.await_args.args[0]
    assert "at most 50 words" in messages[0].content


@pytest.mark.asyncio
async def test_summarize_step_completion_report_empty_pair_returns_none() -> None:
    model = MagicMock()
    model.ainvoke = AsyncMock()

    result = await summarize_step_completion_report(
        human_content="",
        ai_content="",
        fast_model=model,
        max_words=50,
    )

    assert result is None
    model.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_step_completion_report_llm_failure_returns_none() -> None:
    model = MagicMock()
    model.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))

    result = await summarize_step_completion_report(
        human_content="EXECUTION TASK:\ndo work",
        ai_content="done",
        fast_model=model,
        max_words=50,
    )

    assert result is None
