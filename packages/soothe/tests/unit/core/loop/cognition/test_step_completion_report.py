"""Unit tests for execute-step completion cognition summaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from soothe.foundation.sloop.cognition.step_completion_report import (
    _enforce_max_words,
    summarize_step_completion_report,
)


def test_enforce_max_words_truncates() -> None:
    text = "one two three four five six"
    assert _enforce_max_words(text, 3) == "one two three"


@pytest.mark.asyncio
async def test_summarize_step_completion_report_returns_trimmed_text() -> None:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content="I finished reviewing the API docs."))

    result = await summarize_step_completion_report(
        human_content="EXECUTION TASK:\nReview API docs",
        ai_content="Here is the API summary.",
        fast_model=model,
        max_words=30,
    )

    assert result == "I finished reviewing the API docs."
    messages = model.ainvoke.await_args.args[0]
    assert len(messages) == 3
    assert messages[1].content == "EXECUTION TASK:\nReview API docs"
    assert messages[2].content == "Here is the API summary."


@pytest.mark.asyncio
async def test_summarize_step_completion_report_empty_pair_returns_none() -> None:
    model = MagicMock()
    model.ainvoke = AsyncMock()

    result = await summarize_step_completion_report(
        human_content="",
        ai_content="",
        fast_model=model,
        max_words=30,
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
        max_words=30,
    )

    assert result is None
