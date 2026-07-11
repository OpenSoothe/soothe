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
async def test_load_ce_goals_reads_persistence_dag(monkeypatch) -> None:
    goal = SimpleNamespace(
        model_dump=lambda *, mode: {  # noqa: ARG005
            "id": "g1",
            "description": "First",
            "status": "active",
            "depends_on": [],
        }
    )
    dag = SimpleNamespace(goals={"g1": goal})
    persistence = SimpleNamespace(load_dag=AsyncMock(return_value=dag), close=AsyncMock())

    monkeypatch.setattr(
        "soothe.foundation.context.persistence.factory.resolve_context_engine_persistence",
        lambda _config, _loop_id: persistence,
    )
    monkeypatch.setattr("soothe_cli.runtime.load_config", lambda: object())

    goals = await context_data.load_ce_goals("loop-123")
    assert [g["id"] for g in goals] == ["g1"]
    persistence.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_ce_goals_returns_empty_when_dag_missing(monkeypatch) -> None:
    persistence = SimpleNamespace(load_dag=AsyncMock(return_value=None), close=AsyncMock())
    monkeypatch.setattr(
        "soothe.foundation.context.persistence.factory.resolve_context_engine_persistence",
        lambda _config, _loop_id: persistence,
    )
    monkeypatch.setattr("soothe_cli.runtime.load_config", lambda: object())

    assert await context_data.load_ce_goals("missing-loop") == []


def test_format_token_usage_includes_breakdown() -> None:
    snapshot = context_data.TokenUsageSnapshot(
        context_tokens=5000,
        conv_tokens=1200,
        model_name="test-model",
        context_limit=128000,
    )
    rendered = context_data.format_token_usage(snapshot)
    assert "test-model" in rendered
    assert "Conversation" in rendered
    assert "System prompt + tools" in rendered


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
async def test_load_token_usage_snapshot_skips_conversation_when_zero(monkeypatch) -> None:
    fetch = AsyncMock(return_value=999)
    monkeypatch.setattr(context_data, "fetch_conversation_token_count", fetch)

    snapshot = await context_data.load_token_usage_snapshot(
        context_tokens=0,
        loop_id="loop-123",
        daemon_session=object(),
        model_name="test-model",
    )

    assert snapshot.context_tokens == 0
    assert snapshot.conv_tokens is None
    fetch.assert_not_called()


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
    assert "Conversation" in context_data.format_token_usage(snapshot)
