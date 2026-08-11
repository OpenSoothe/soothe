"""Unit tests for LoopRail pause_for_user Veritas auto-clarify (IG-737)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from soothe.autopilot.rails.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rails.pause_clarify import (
    PauseClarifyDecision,
    parse_gate_answer_token,
)
from soothe.context import ContextEngine


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        (("PROCEED",), "proceed"),
        (("proceed please",), "proceed"),
        (("yes",), "proceed"),
        (("PAUSE",), "deny"),
        (("pause now",), "deny"),
        (("no",), "deny"),
        (("maybe later",), "defer"),
        ((), "defer"),
        (("",), "defer"),
    ],
)
def test_parse_gate_answer_token(answers: tuple[str, ...], expected: str) -> None:
    assert parse_gate_answer_token(answers) == expected


@pytest.mark.asyncio
async def test_pause_for_user_proceed_skips_suspend_and_fires_callback(
    tmp_path: Path,
) -> None:
    ce = ContextEngine()
    job = await ce.create_goal("demo job", priority=90)
    trigger = await ce.create_goal("qa done", parent_id=job.id, priority=80)
    await ce.complete_goal(trigger.id)

    fired: list[str] = []

    async def on_ui(job_id: str) -> None:
        fired.append(job_id)

    async def fake_clarify(**_kwargs: Any) -> PauseClarifyDecision:
        return PauseClarifyDecision(
            outcome="proceed",
            confidence=0.9,
            rationale="safe to continue",
            answers=("PROCEED",),
        )

    ex = RailBuiltinExecutor(
        ce,
        jobs_root=tmp_path / "jobs",
        rail_pause_auto_clarify=True,
        on_user_intervention=on_ui,
        pause_clarify_fn=fake_clarify,
    )
    await ex.bind_job(RailJobState(job_id=job.id, rail_id="greenfield-system", rail_version="1"))
    result = await ex._do_pause_for_user(job_id=job.id, trigger_goal_id=trigger.id)
    assert result.status == "success"
    assert result.detail == "veritas_auto_proceed"
    root = await ce.get_goal(job.id)
    assert root is not None
    assert root.status != "suspended"
    assert fired == [job.id]
    state = await ex.job_state(job.id)
    assert state is not None
    assert state.suspended is False
    assert state.last_pause_clarify is not None
    assert state.last_pause_clarify["outcome"] == "proceed"


@pytest.mark.asyncio
async def test_pause_for_user_defer_suspends(tmp_path: Path) -> None:
    ce = ContextEngine()
    job = await ce.create_goal("demo job", priority=90)

    async def fake_clarify(**_kwargs: Any) -> PauseClarifyDecision:
        return PauseClarifyDecision(outcome="defer", rationale="low confidence")

    ex = RailBuiltinExecutor(
        ce,
        jobs_root=tmp_path / "jobs",
        rail_pause_auto_clarify=True,
        pause_clarify_fn=fake_clarify,
    )
    await ex.bind_job(RailJobState(job_id=job.id, rail_id="spike", rail_version="1"))
    result = await ex._do_pause_for_user(job_id=job.id, trigger_goal_id=None)
    assert result.status == "success"
    assert "suspended" in result.detail
    root = await ce.get_goal(job.id)
    assert root is not None
    assert root.status == "suspended"
    state = await ex.job_state(job.id)
    assert state is not None
    assert state.suspended is True
    assert state.last_pause_clarify["outcome"] == "defer"


@pytest.mark.asyncio
async def test_pause_for_user_deny_suspends(tmp_path: Path) -> None:
    ce = ContextEngine()
    job = await ce.create_goal("demo job", priority=90)

    async def fake_clarify(**_kwargs: Any) -> PauseClarifyDecision:
        return PauseClarifyDecision(
            outcome="deny",
            confidence=0.95,
            answers=("PAUSE",),
        )

    ex = RailBuiltinExecutor(
        ce,
        jobs_root=tmp_path / "jobs",
        pause_clarify_fn=fake_clarify,
    )
    await ex.bind_job(RailJobState(job_id=job.id, rail_id="hotfix", rail_version="1"))
    result = await ex._do_pause_for_user(job_id=job.id, trigger_goal_id=None)
    assert "deny" in result.detail
    root = await ce.get_goal(job.id)
    assert root is not None
    assert root.status == "suspended"


@pytest.mark.asyncio
async def test_pause_for_user_kill_switch_always_suspends(tmp_path: Path) -> None:
    ce = ContextEngine()
    job = await ce.create_goal("demo job", priority=90)
    called = False

    async def fake_clarify(**_kwargs: Any) -> PauseClarifyDecision:
        nonlocal called
        called = True
        return PauseClarifyDecision(outcome="proceed")

    ex = RailBuiltinExecutor(
        ce,
        jobs_root=tmp_path / "jobs",
        rail_pause_auto_clarify=False,
        pause_clarify_fn=fake_clarify,
    )
    await ex.bind_job(RailJobState(job_id=job.id, rail_id="spike", rail_version="1"))
    await ex._do_pause_for_user(job_id=job.id, trigger_goal_id=None)
    assert called is False
    root = await ce.get_goal(job.id)
    assert root is not None
    assert root.status == "suspended"


@pytest.mark.asyncio
async def test_pause_for_user_no_config_fails_open_to_suspend(tmp_path: Path) -> None:
    ce = ContextEngine()
    job = await ce.create_goal("demo job", priority=90)
    ex = RailBuiltinExecutor(
        ce,
        jobs_root=tmp_path / "jobs",
        rail_pause_auto_clarify=True,
        soothe_config=None,
    )
    await ex.bind_job(RailJobState(job_id=job.id, rail_id="spike", rail_version="1"))
    await ex._do_pause_for_user(job_id=job.id, trigger_goal_id=None)
    root = await ce.get_goal(job.id)
    assert root is not None
    assert root.status == "suspended"
