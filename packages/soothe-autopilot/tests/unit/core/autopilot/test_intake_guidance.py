"""Unit tests for Autopilot guidance intake (IG-733)."""

from __future__ import annotations

import pytest
from soothe.context import ContextEngine
from soothe.context.models import GoalNode

from soothe_autopilot.intake import (
    absorb_channel_guidance,
    absorb_user_guidance,
    collect_operator_guidance,
)


@pytest.mark.asyncio
async def test_absorb_user_guidance_tags_source() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("Ship OAuth")
    ok = await absorb_user_guidance(ce, goal.id, "Prefer PKCE", scope="goal")
    assert ok is True
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    entry = refreshed.guidance_accumulated[-1]
    assert entry["text"] == "Prefer PKCE"
    assert entry["source"] == "user"
    assert entry["scope"] == "goal"


@pytest.mark.asyncio
async def test_absorb_channel_guidance_tags_source() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("Ship OAuth")
    ok = await absorb_channel_guidance(ce, goal.id, "From telegram", scope="job")
    assert ok is True
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    entry = refreshed.guidance_accumulated[-1]
    assert entry["text"] == "From telegram"
    assert entry["source"] == "channel"
    assert entry["scope"] == "job"


@pytest.mark.asyncio
async def test_absorb_empty_text_rejected() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("Ship")
    assert await absorb_user_guidance(ce, goal.id, "   ") is False


def test_collect_operator_guidance_includes_goal_and_job_scope() -> None:
    root = GoalNode(id="root0001", description="job root")
    root.guidance_accumulated = [
        {"text": "job-wide: use feature branch", "scope": "job"},
        {"text": "root-only note", "scope": "goal"},
    ]
    child = GoalNode(id="child001", description="implement", parent_id="root0001")
    child.guidance_accumulated = [{"text": "focus on login route", "scope": "goal"}]
    goals = {"root0001": root, "child001": child}

    texts = collect_operator_guidance(child, goals)
    assert "focus on login route" in texts
    assert "job-wide: use feature branch" in texts
    assert "root-only note" not in texts
