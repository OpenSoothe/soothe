"""Unit tests for LoopRail selector + AutopilotService rail bind (IG-678 P2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.autopilot import AutopilotService
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus
from soothe.rails.selector import resolve_rail_id

from .fakes import IdleFakeFactory


def test_resolve_rail_explicit_wins(tmp_path: Path) -> None:
    marker = tmp_path / ".soothe" / "rails"
    marker.mkdir(parents=True)
    (marker / ".rail-default").write_text("spike\n", encoding="utf-8")
    assert (
        resolve_rail_id("feature-dev", workspace=str(tmp_path), default_rail="hotfix")
        == "feature-dev"
    )


def test_resolve_rail_workspace_default(tmp_path: Path) -> None:
    marker = tmp_path / ".soothe" / "rails"
    marker.mkdir(parents=True)
    (marker / ".rail-default").write_text("# comment\nspike\n", encoding="utf-8")
    assert resolve_rail_id(None, workspace=str(tmp_path), default_rail="hotfix") == "spike"


def test_resolve_rail_config_default() -> None:
    assert resolve_rail_id(None, workspace=None, default_rail="pr-review") == "pr-review"


def test_resolve_rail_none() -> None:
    assert resolve_rail_id(None, workspace=None, default_rail=None) is None


@pytest.mark.asyncio
async def test_submit_task_binds_spike_rail_and_decomposes() -> None:
    svc = AutopilotService(
        ce=ContextEngine(),
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=InternalEventBus(),
        runner_factory=IdleFakeFactory(),
    )
    goal = await svc.submit_task("Spike comparison", rail_id="spike")
    assert goal.rail_id == "spike"
    children = [g for g in await svc.list_goals() if g.parent_id == goal.id]
    assert len(children) >= 1
    assert children[0].role == "scout"
    assert "exploration" in children[0].rail_tags


@pytest.mark.asyncio
async def test_spike_pause_resume_user_intervention_and_jsonl_trace(tmp_path: Path) -> None:
    """Spike rail: scouts → pause → resume fires user_intervention → complete."""
    from soothe.autopilot.rail.guards import ScriptedGuardEvaluator
    from soothe.autopilot.rail.interpreter import LoopRailInterpreter
    from soothe.autopilot.rail.trace_store import JsonlRailTraceStore

    data = tmp_path / "data"
    svc = AutopilotService(
        ce=ContextEngine(),
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=InternalEventBus(),
        runner_factory=IdleFakeFactory(),
    )
    scripts = {
        ("goal_completed", "scouts_done"): [False, True],
        ("dag_idle", "job_complete"): [True],
    }
    trace = JsonlRailTraceStore(root=data / "loops")
    svc._rail_interpreter = LoopRailInterpreter(
        svc._ce,
        guards=ScriptedGuardEvaluator.from_mapping(scripts),
        trace=trace,
    )

    job = await svc.submit_task("Spike compare stores", rail_id="spike")
    scouts = [g for g in await svc.list_goals() if g.parent_id == job.id]
    assert len(scouts) >= 2

    # Complete scouts until pause_for_user fires (second scout matches scouts_done).
    for scout in scouts:
        await svc._ce.complete_goal(scout.id)
        await svc._notify_rail("goal_completed", scout.id)

    root = await svc.get_goal(job.id)
    assert root is not None
    assert root.status == "suspended"

    resumed = await svc.resume_job(job.id)
    assert resumed is not None
    # user_intervention → complete_job
    final = await svc.get_goal(job.id)
    assert final is not None
    assert final.status == "completed"

    records = trace.read(job.id)
    builtins = [r.builtin for r in records if r.builtin and r.guard_result.matched]
    assert "decompose_parallel" in builtins
    assert "pause_for_user" in builtins
    assert "complete_job" in builtins
    assert (data / "loops" / job.id / "rail_trace.jsonl").is_file()


@pytest.mark.asyncio
async def test_maker_checker_send_back_retries_branch() -> None:
    """Maker-checker: goal_send_back with recoverable guard → retry_branch."""
    from soothe.autopilot.rail.guards import ScriptedGuardEvaluator
    from soothe.autopilot.rail.interpreter import LoopRailInterpreter

    svc = AutopilotService(
        ce=ContextEngine(),
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=InternalEventBus(),
        runner_factory=IdleFakeFactory(),
    )
    scripts = {
        ("goal_completed", "needs_check"): [True],
        ("goal_send_back", "checker_failed_recoverable"): [True],
    }
    svc._rail_interpreter = LoopRailInterpreter(
        svc._ce,
        guards=ScriptedGuardEvaluator.from_mapping(scripts),
    )

    job = await svc.submit_task("Sensitive auth change", rail_id="maker-checker")
    # job_start → plan_and_implement
    kids = [g for g in await svc.list_goals() if g.parent_id == job.id]
    assert any(g.role == "planner" for g in kids)
    assert any(g.role == "maker" for g in kids)

    maker = next(g for g in kids if g.role == "maker")
    await svc._ce.complete_goal(maker.id)
    await svc._notify_rail("goal_completed", maker.id)

    checker = next(
        g for g in await svc.list_goals() if g.parent_id == job.id and g.role == "checker"
    )
    await svc._notify_rail("goal_send_back", checker.id, reason="needs fix")

    replants = [
        g
        for g in await svc.list_goals()
        if g.parent_id == job.id and g.role == "maker" and "replant" in (g.rail_tags or [])
    ]
    assert len(replants) >= 1
