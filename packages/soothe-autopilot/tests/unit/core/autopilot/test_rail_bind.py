"""Unit tests for AutopilotService LoopRail bind (P2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus

from soothe_autopilot import AutopilotService

from .fakes import IdleFakeFactory


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
async def test_submit_auto_pick_binds_llm_rail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IG-728: submit without rail_id binds LLM pick before job_start."""
    from soothe.rails.selector import RailAutoPicker, RailAutoPickResponse

    async def fake_pick(
        self: RailAutoPicker,
        description: str,
        cands: object,
        *,
        max_field_chars: int = 400,
    ) -> RailAutoPickResponse:
        return RailAutoPickResponse(
            rail_id="spike",
            confidence=0.92,
            reasoning="exploration before coding",
        )

    monkeypatch.setattr(RailAutoPicker, "pick", fake_pick)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    svc = AutopilotService(
        ce=ContextEngine(),
        config=AutopilotConfig(
            max_loops=2,
            max_parallel_goals=2,
            rail_auto_pick=True,
            rail_auto_pick_min_confidence=0.6,
        ),
        internal_bus=InternalEventBus(),
        runner_factory=IdleFakeFactory(),
        auto_pick_model=object(),
    )
    svc._jobs_root = jobs
    goal = await svc.submit_task("Compare two store backends before implementing")
    assert goal.rail_id == "spike"
    children = [g for g in await svc.list_goals() if g.parent_id == goal.id]
    assert len(children) >= 1
    selection = jobs / goal.id / "rail_selection.json"
    assert selection.is_file()
    assert "llm" in selection.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_spike_pause_resume_user_intervention_and_jsonl_trace(tmp_path: Path) -> None:
    """Spike rail: scouts → pause → resume fires user_intervention → complete.

    Without ``soothe_config``, pause_for_user fails open to CE suspend (legacy
    operator path). Veritas auto-proceed is covered separately.
    """
    from soothe.rails.guards import ScriptedGuardEvaluator
    from soothe.rails.interpreter import LoopRailInterpreter
    from soothe.rails.trace_store import JsonlRailTraceStore

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
    trace = JsonlRailTraceStore(root=data / "jobs", legacy_root=data / "loops")
    svc._rail_interpreter = LoopRailInterpreter(
        svc._ce,
        guards=ScriptedGuardEvaluator.from_mapping(scripts),
        trace=trace,
        jobs_root=data / "jobs",
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
    assert (data / "jobs" / job.id / "rail_trace.jsonl").is_file()


@pytest.mark.asyncio
async def test_spike_veritas_auto_proceed_completes_without_resume(tmp_path: Path) -> None:
    """IG-737: Veritas PROCEED on pause_for_user fires user_intervention → complete."""
    from soothe.rails.builtins_exec import RailBuiltinExecutor
    from soothe.rails.guards import ScriptedGuardEvaluator
    from soothe.rails.interpreter import LoopRailInterpreter
    from soothe.rails.pause_clarify import PauseClarifyDecision
    from soothe.rails.trace_store import JsonlRailTraceStore

    data = tmp_path / "data"
    svc = AutopilotService(
        ce=ContextEngine(),
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=InternalEventBus(),
        runner_factory=IdleFakeFactory(),
    )

    async def fake_clarify(**_kwargs: object) -> PauseClarifyDecision:
        return PauseClarifyDecision(
            outcome="proceed",
            confidence=0.95,
            answers=("PROCEED",),
            rationale="spike checkpoint auto-approved",
        )

    # user_intervention has no when clause (always matches). Only script scouts_done.
    scripts = {
        ("goal_completed", "scouts_done"): [False, True],
    }
    trace = JsonlRailTraceStore(root=data / "jobs", legacy_root=data / "loops")
    builtins = RailBuiltinExecutor(
        svc._ce,
        jobs_root=data / "jobs",
        rail_pause_auto_clarify=True,
        on_user_intervention=svc._on_rail_pause_user_intervention,
        pause_clarify_fn=fake_clarify,
    )
    svc._rail_interpreter = LoopRailInterpreter(
        svc._ce,
        builtins=builtins,
        guards=ScriptedGuardEvaluator.from_mapping(scripts),
        trace=trace,
        jobs_root=data / "jobs",
    )

    job = await svc.submit_task("Spike compare stores", rail_id="spike")
    scouts = [g for g in await svc.list_goals() if g.parent_id == job.id]
    assert len(scouts) >= 2

    for scout in scouts:
        await svc._ce.complete_goal(scout.id)
        await svc._notify_rail("goal_completed", scout.id)

    final = await svc.get_goal(job.id)
    assert final is not None
    assert final.status == "completed"

    records = trace.read(job.id)
    builtins_fired = [r.builtin for r in records if r.builtin and r.guard_result.matched]
    assert "pause_for_user" in builtins_fired
    assert "complete_job" in builtins_fired
    pause_recs = [r for r in records if r.builtin == "pause_for_user"]
    assert pause_recs
    assert pause_recs[-1].builtin_result == "success"


@pytest.mark.asyncio
async def test_maker_checker_send_back_retries_branch() -> None:
    """Maker-checker: goal_send_back with recoverable guard → retry_branch."""
    from soothe.rails.guards import ScriptedGuardEvaluator
    from soothe.rails.interpreter import LoopRailInterpreter

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
