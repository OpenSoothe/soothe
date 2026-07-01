"""Unit tests for resume topic generation (TUI /resume picker)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe.foundation.sloop.state import resume_topic as resume_topic_mod
from soothe.foundation.sloop.state.resume_topic import (
    abbreviate_ledger_for_topic,
    enforce_topic_word_limit,
    generate_and_persist_resume_topic,
    normalize_topic_response,
    schedule_resume_topic_generation,
)


@pytest.fixture(autouse=True)
def _clear_inflight_loop_ids() -> None:
    resume_topic_mod._inflight_loop_ids.clear()
    yield
    resume_topic_mod._inflight_loop_ids.clear()


def test_abbreviate_ledger_for_topic_caps_total_chars() -> None:
    messages = [
        HumanMessage(content="x" * 200),
        AIMessage(content="y" * 200),
        HumanMessage(content="recent user turn"),
        AIMessage(content="recent assistant answer"),
    ]
    text = abbreviate_ledger_for_topic(messages, max_chars=512)
    assert len(text) <= 512
    assert "recent assistant answer" in text


def test_abbreviate_ledger_for_topic_skips_empty_messages() -> None:
    text = abbreviate_ledger_for_topic(
        [HumanMessage(content="  "), AIMessage(content="done")],
        max_chars=512,
    )
    assert text == "A: done"


def test_enforce_topic_word_limit() -> None:
    assert enforce_topic_word_limit("one two three four five six seven eight nine") == (
        "one two three four five six seven eight"
    )


def test_normalize_topic_response_strips_quotes_and_limits_words() -> None:
    assert normalize_topic_response('  "Fix auth bug in API"  ') == "Fix auth bug in API"
    assert len(normalize_topic_response("a " * 20).split()) == 8


@pytest.mark.asyncio
async def test_generate_and_persist_skips_when_topic_already_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resume_topic_mod,
        "_load_existing_resume_topic",
        AsyncMock(return_value="Existing topic"),
    )
    generate_mock = AsyncMock(return_value="New topic")
    monkeypatch.setattr(resume_topic_mod, "generate_resume_topic_from_ledger", generate_mock)

    await generate_and_persist_resume_topic(
        config=SimpleNamespace(),
        loop_id="loop-existing",
        ledger_messages=[HumanMessage(content="hello")],
    )

    generate_mock.assert_not_awaited()


def test_schedule_skips_when_existing_topic_provided() -> None:
    schedule_resume_topic_generation(
        config=SimpleNamespace(),
        loop_id="loop-a",
        ledger_messages=[HumanMessage(content="hello")],
        goals_completed=1,
        existing_resume_topic="Already stored",
    )
    assert "loop-a" not in resume_topic_mod._inflight_loop_ids


def test_schedule_skips_when_generation_already_inflight() -> None:
    resume_topic_mod._inflight_loop_ids.add("loop-b")
    schedule_resume_topic_generation(
        config=SimpleNamespace(),
        loop_id="loop-b",
        ledger_messages=[HumanMessage(content="hello")],
        goals_completed=1,
    )
    assert resume_topic_mod._inflight_loop_ids == {"loop-b"}
