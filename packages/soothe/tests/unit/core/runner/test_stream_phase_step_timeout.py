"""LLM timeout during plan DAG steps should fail the step only (IG-393)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner
from soothe.core.runner._runner_shared import _custom
from soothe.core.runner._types import RunnerState
from soothe.utils.error_format import emit_error_event


@pytest.mark.asyncio
async def test_stream_phase_timeout_emits_global_error_by_default() -> None:
    runner = object.__new__(SootheRunner)
    runner._config = SootheConfig()
    runner._durability = MagicMock()
    runner._durability.get_thread = AsyncMock(return_value=None)
    runner._ensure_checkpointer_initialized = AsyncMock()

    async def _raising_astream(*_a: object, **_kw: object):
        raise TimeoutError()
        yield ((), "messages", ())  # pragma: no cover

    runner._agent = MagicMock()
    runner._agent.astream = _raising_astream
    runner._build_enriched_input = MagicMock(return_value=[HumanMessage(content="hi")])

    state = RunnerState()
    state.thread_id = "tid-a"

    chunks: list = []
    async for chunk in runner._stream_phase("hello", state):
        chunks.append(chunk)

    assert state.stream_error == ""
    assert len(chunks) == 1
    assert chunks[0] == _custom(emit_error_event(TimeoutError()))


@pytest.mark.asyncio
async def test_stream_phase_timeout_suppresses_global_error_for_step_scope() -> None:
    runner = object.__new__(SootheRunner)
    runner._config = SootheConfig()
    runner._durability = MagicMock()
    runner._durability.get_thread = AsyncMock(return_value=None)
    runner._ensure_checkpointer_initialized = AsyncMock()

    async def _raising_astream(*_a: object, **_kw: object):
        raise TimeoutError()
        yield ((), "messages", ())  # pragma: no cover

    runner._agent = MagicMock()
    runner._agent.astream = _raising_astream
    runner._build_enriched_input = MagicMock(return_value=[HumanMessage(content="hi")])

    state = RunnerState()
    state.thread_id = "tid-b"

    chunks: list = []
    async for chunk in runner._stream_phase(
        "hello",
        state,
        suppress_global_error_on_llm_timeout=True,
    ):
        chunks.append(chunk)

    assert state.stream_error == ""
    assert chunks == []


@pytest.mark.asyncio
async def test_stream_phase_suppress_does_not_hide_other_errors() -> None:
    runner = object.__new__(SootheRunner)
    runner._config = SootheConfig()
    runner._durability = MagicMock()
    runner._durability.get_thread = AsyncMock(return_value=None)
    runner._ensure_checkpointer_initialized = AsyncMock()

    async def _raising_astream(*_a: object, **_kw: object):
        raise ValueError("boom")
        yield ((), "messages", ())  # pragma: no cover

    runner._agent = MagicMock()
    runner._agent.astream = _raising_astream
    runner._build_enriched_input = MagicMock(return_value=[HumanMessage(content="hi")])

    state = RunnerState()
    state.thread_id = "tid-c"

    chunks: list = []
    async for chunk in runner._stream_phase(
        "hello",
        state,
        suppress_global_error_on_llm_timeout=True,
    ):
        chunks.append(chunk)

    assert "boom" in (state.stream_error or "")
    assert len(chunks) == 1
