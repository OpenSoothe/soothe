"""Regression test for ``OpenAICompatModelWrapper._astream`` contract.

``BaseChatModel._astream`` is an async generator (it ``yield``s chunks); the
public ``astream`` iterates it with ``async for chunk in self._astream(...)``.
The wrapper must mirror that contract — delegating by ``yield``-ing each chunk
from the wrapped model. An earlier implementation ``return await
self._model._astream(...)`` made ``_astream`` a value-returning coroutine, so
``async for chunk in <coroutine>`` raised ``'async for' requires an object with
__aiter__`` (direct_llm turns timed out).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe_nano.utils.llm.wrappers import OpenAICompatModelWrapper


def _make_wrapped_model(chunks: list[Any]) -> MagicMock:
    """Build a mock whose ``_astream`` is a real async generator."""

    async def _astream(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        for chunk in chunks:
            yield chunk

    model = MagicMock()
    model._astream = _astream
    return model


def _collect_chunks_sync(chunks: list[Any]) -> list[Any]:
    """Synchronously drain ``_astream`` into a list via a private event loop."""
    import asyncio

    async def _drain() -> list[Any]:
        wrapper = OpenAICompatModelWrapper(_make_wrapped_model(chunks), "test")
        out: list[Any] = []
        async for chunk in wrapper._astream(messages=[], stop=None, run_manager=None):  # noqa: SLF001
            out.append(chunk)
        return out

    return asyncio.new_event_loop().run_until_complete(_drain())


def test_astream_is_async_generator_not_coroutine() -> None:
    """Calling ``_astream`` must return an async iterator, not a coroutine."""
    wrapper = OpenAICompatModelWrapper(_make_wrapped_model(["a", "b"]), "test")

    result = wrapper._astream(messages=[], stop=None, run_manager=None)  # noqa: SLF001
    # Async generators implement __aiter__; coroutines do not.
    assert hasattr(result, "__aiter__"), "_astream must return an async iterator"
    assert not hasattr(result, "__await__"), "_astream must not be a value coroutine"


def test_astream_yields_each_chunk_from_wrapped_model() -> None:
    """Every chunk the wrapped model yields must pass through the wrapper."""
    chunks = ["chunk-0", "chunk-1", "chunk-2"]
    out = _collect_chunks_sync(chunks)
    assert out == chunks


@pytest.mark.asyncio
async def test_astream_is_iterable_with_async_for() -> None:
    """``async for chunk in wrapper._astream(...)`` must work end-to-end."""
    wrapper = OpenAICompatModelWrapper(_make_wrapped_model(["x", "y"]), "test")
    out: list[Any] = []
    async for chunk in wrapper._astream(messages=[], stop=None, run_manager=None):  # noqa: SLF001
        out.append(chunk)
    assert out == ["x", "y"]
