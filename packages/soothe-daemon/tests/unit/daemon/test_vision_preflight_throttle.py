"""Tests for daemon vision preflight concurrency cap."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from soothe_daemon.query import QueryEngine
from soothe_daemon.query import engine as query_engine_module


@pytest.mark.asyncio
async def test_enrich_with_vision_throttled_respects_semaphore(monkeypatch: Any) -> None:
    """At most N coroutines run enrich concurrently when semaphore limit is N."""
    concurrent = 0
    peak = 0
    gate = asyncio.Lock()

    async def fake_enrich(
        _config: Any, _text: str, _attachments: list[dict[str, str]], **_kw: Any
    ) -> str:
        nonlocal concurrent, peak
        async with gate:
            concurrent += 1
            peak = max(peak, concurrent)
        await asyncio.sleep(0.06)
        async with gate:
            concurrent -= 1
        return "enriched"

    monkeypatch.setattr(query_engine_module, "enrich_user_text_with_vision", fake_enrich)

    sem = asyncio.Semaphore(2)
    daemon = SimpleNamespace(_vision_preflight_semaphore=sem)
    qe = QueryEngine(daemon)

    attachments: list[dict[str, str]] = [{"mime_type": "image/png", "data": "e30="}]
    await asyncio.gather(
        *[qe._enrich_with_vision_throttled(None, "hi", attachments) for _ in range(6)]
    )

    assert peak <= 2


@pytest.mark.asyncio
async def test_enrich_with_vision_throttled_unlimited_when_no_semaphore(
    monkeypatch: Any,
) -> None:
    """When daemon has no semaphore, all enrich calls proceed without throttling."""
    concurrent = 0
    peak = 0
    gate = asyncio.Lock()

    async def fake_enrich(
        _config: Any, _text: str, _attachments: list[dict[str, str]], **_kw: Any
    ) -> str:
        nonlocal concurrent, peak
        async with gate:
            concurrent += 1
            peak = max(peak, concurrent)
        await asyncio.sleep(0.02)
        async with gate:
            concurrent -= 1
        return "x"

    monkeypatch.setattr(query_engine_module, "enrich_user_text_with_vision", fake_enrich)

    daemon = SimpleNamespace(_vision_preflight_semaphore=None)
    qe = QueryEngine(daemon)

    attachments: list[dict[str, str]] = [{"mime_type": "image/png", "data": "e30="}]
    await asyncio.gather(
        *[qe._enrich_with_vision_throttled(None, "hi", attachments) for _ in range(5)]
    )

    assert peak == 5
