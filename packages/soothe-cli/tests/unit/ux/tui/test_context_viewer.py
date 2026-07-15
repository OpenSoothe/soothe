"""Tests for context viewer goal loading and loop-id display formatting."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from soothe_cli.tui.widgets import context_data, context_viewer


def test_abbreviate_loop_id_uses_prefix_suffix() -> None:
    loop_id = "019f17e6-5432-4a91-b6f2-f265c9876543"
    assert context_viewer._abbreviate_loop_id(loop_id) == "019f17e6...6543"


def test_abbreviate_loop_id_keeps_short_ids() -> None:
    assert context_viewer._abbreviate_loop_id("abc123") == "abc123"


@pytest.mark.asyncio
async def test_load_ce_goals_maps_daemon_history_snapshots() -> None:
    history = SimpleNamespace(
        goals=[
            {
                "goal_id": "g1",
                "goal_text": "First",
                "status": "active",
            }
        ]
    )
    session = SimpleNamespace(fetch_loop_history=AsyncMock(return_value=history))

    goals = await context_data.load_ce_goals("loop-123", session)
    assert goals == [
        {
            "id": "g1",
            "description": "First",
            "status": "active",
            "depends_on": [],
        }
    ]
    session.fetch_loop_history.assert_awaited_once_with("loop-123")


@pytest.mark.asyncio
async def test_load_ce_goals_returns_empty_when_history_missing() -> None:
    session = SimpleNamespace(fetch_loop_history=AsyncMock(return_value=SimpleNamespace(goals=[])))
    assert await context_data.load_ce_goals("missing-loop", session) == []


@pytest.mark.asyncio
async def test_load_ce_goals_returns_empty_without_daemon_session() -> None:
    assert await context_data.load_ce_goals("loop-123") == []
    assert await context_data.load_ce_goals("loop-123", None) == []


def test_format_token_usage_includes_breakdown() -> None:
    snapshot = context_data.TokenUsageSnapshot(
        context_tokens=5000,
        conv_tokens=1200,
        model_name="test-model",
        context_limit=128000,
        input_tokens=3800,
        output_tokens=1200,
    )
    rendered = context_data.format_token_usage(snapshot)
    assert "test-model" in rendered
    assert "tokens used this loop" in rendered
    assert "in:" in rendered
    assert "out:" in rendered
    assert "Conversation (est.)" in rendered


def test_summarize_goal_statuses_counts_all_statuses() -> None:
    goals = [
        {"status": "active"},
        {"status": "validated"},
        {"status": "completed"},
    ]
    total, counts = context_data.summarize_goal_statuses(goals)
    assert total == 3
    assert counts == {"active": 1, "validated": 1, "completed": 1}


@pytest.mark.asyncio
async def test_load_token_usage_snapshot_estimates_when_context_zero(monkeypatch) -> None:
    fetch = AsyncMock(return_value=999)
    monkeypatch.setattr(context_data, "fetch_conversation_token_count", fetch)

    snapshot = await context_data.load_token_usage_snapshot(
        context_tokens=0,
        loop_id="loop-123",
        daemon_session=object(),
        model_name="test-model",
    )

    assert snapshot.context_tokens == 999
    assert snapshot.approximate is True
    assert snapshot.conv_tokens == 999
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_token_usage_snapshot_includes_conversation_breakdown(monkeypatch) -> None:
    monkeypatch.setattr(
        context_data,
        "fetch_conversation_token_count",
        AsyncMock(return_value=1200),
    )

    snapshot = await context_data.load_token_usage_snapshot(
        context_tokens=5000,
        loop_id="loop-123",
        daemon_session=object(),
        model_name="test-model",
        context_limit=128000,
    )

    assert snapshot.conv_tokens == 1200
    assert "Conversation (est.)" in context_data.format_token_usage(snapshot)
