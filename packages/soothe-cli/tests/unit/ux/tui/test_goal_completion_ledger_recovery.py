"""Tests for ledger fallback when goal_completion stream aborts."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe_cli.runtime.transport.session import TuiDaemonSession


@pytest.mark.asyncio
async def test_fetch_goal_completion_text_returns_latest_row() -> None:
    session = object.__new__(TuiDaemonSession)
    session.fetch_conversation_log = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {"kind": "conversation", "phase": "execute_step", "text": "preview"},
            {"kind": "conversation", "phase": "goal_completion", "text": "older"},
            {"kind": "conversation", "phase": "goal_completion", "text": "final report"},
        ]
    )

    text = await session.fetch_goal_completion_text("loop-1")

    assert text == "final report"
    session.fetch_conversation_log.assert_awaited_once_with(
        "loop-1",
        limit=200,
        include_events=False,
    )


@pytest.mark.asyncio
async def test_fetch_goal_completion_text_returns_none_when_missing() -> None:
    session = object.__new__(TuiDaemonSession)
    session.fetch_conversation_log = AsyncMock(return_value=[])  # type: ignore[method-assign]

    assert await session.fetch_goal_completion_text("loop-1") is None
