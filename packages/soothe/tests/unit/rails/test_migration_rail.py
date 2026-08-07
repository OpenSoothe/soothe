"""Unit tests for migration rail v2.0 fan-out (IG-715)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.guards import GuardResult, _structural_short_circuit
from soothe.autopilot.rail.interpreter import LoopRailInterpreter
from soothe.context import ContextEngine
from soothe.rails import LoopRailCatalog


def test_migration_rail_declares_fanout_and_human_gate() -> None:
    rail = LoopRailCatalog().resolve("migration")
    assert rail.version == "2.7"
    assert "artifact" not in rail.fanout
    assert rail.fanout.get("require_plan") is True
    assert "default_modules" not in rail.fanout
    assert rail.fanout.get("max_waves") == 3
    pm = rail.verbs.get("plan_milestones") or {}
    assert isinstance(pm.get("do"), list) and pm["do"]
    spawn = pm["do"][0].get("spawn_goal") or {}
    brief = str(spawn.get("brief") or "")
    assert "Migration architecture" in brief
    assert "slice" in brief.lower() or "schema" in brief.lower()

    thens = [str(e.get("then")) for e in rail.flow]
    assert thens[0] == "plan_milestones"
    assert "spawn_wave_makers" in thens
    assert "spawn_integrate" in thens
    assert "commit_milestone" in thens
    assert "review" in thens
    assert "qa_verify" in thens
    assert "spawn_feedback_cycle" in thens
    assert "retry_architecture" in thens
    assert "pause_for_user" in thens
    assert "decompose_parallel" not in thens
    assert "plan_and_implement" not in thens

    human = [
        e for e in rail.flow if e.get("when") == "needs_human" and e.get("then") == "pause_for_user"
    ]
    assert human
    dag_idle = [e for e in rail.flow if e.get("event") == "dag_idle"]
    assert any(e.get("when") == "architecture_ready" for e in dag_idle)
    assert any(e.get("when") == "wave_makers_done" for e in dag_idle)


def test_ready_for_next_wave_without_architecture_unmatched() -> None:
    """Legacy exploration_done path must not match after condition normalization."""
    r = _structural_short_circuit(
        condition_name="ready_for_next_wave",
        event="goal_completed",
        trigger_tags=["exploration"],
        structural={
            "architecture_goal_ids": [],
            "fanout_enabled": False,
            "require_plan": False,
            "all_exploration_terminal": True,
            "pending_or_active_count": 0,
            "wave_index": 0,
            "max_waves": 3,
        },
    )
    assert isinstance(r, GuardResult)
    assert r.matched is False
    assert "fan-out" in r.reasoning.lower() or "fanout" in r.reasoning.lower()


def test_ready_for_next_wave_architecture_path_still_works() -> None:
    r = _structural_short_circuit(
        condition_name="ready_for_next_wave",
        event="goal_completed",
        trigger_tags=["verify", "feedback"],
        structural={
            "architecture_goal_ids": ["a1"],
            "fanout_enabled": True,
            "require_plan": True,
            "pending_or_active_count": 0,
            "wave_index": 0,
            "max_waves": 3,
            "wave_below_max": True,
            "all_qa_terminal": True,
            "feedback_inflight": False,
            "acceptance_met": False,
            "feedback_round": 1,
            "max_feedback_rounds": 8,
        },
    )
    assert isinstance(r, GuardResult)
    assert r.matched is True


@pytest.mark.asyncio
async def test_bind_migration_stamps_fanout_state(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Migrate schema", workspace=str(tmp_path), priority=70)
    interp = LoopRailInterpreter(ce, jobs_root=tmp_path)
    await interp.bind_job(root.id, rail_id="migration", workspace=str(tmp_path))
    state = await interp.builtins.job_state(root.id)
    assert state is not None
    assert state.require_plan is True
    assert state.max_waves == 3


@pytest.mark.asyncio
async def test_plan_milestones_migration_copy(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Migrate", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    rail = LoopRailCatalog().resolve("migration")
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="migration",
            rail_version=rail.version,
            require_plan=True,
            verb_overrides=dict(rail.verbs),
        )
    )
    result = await ex.invoke("plan_milestones", job_id=root.id)
    arch = await ce.get_goal(result.created_goal_ids[0])
    assert arch is not None
    desc = arch.description.lower()
    assert "migration" in desc
    assert "slice" in desc or "schema" in desc
    assert "ownership units" not in desc
    assert "FINDINGS.md" in arch.description
    assert "goal completion" in desc
    assert "Do NOT write" in arch.description
    assert "nested" in desc
    assert "WavePlan JSON" in arch.description
    assert "record_wave_plan" not in arch.description
    assert "append one findings entry" not in desc
    assert "max_parallel_goals" not in arch.description
    assert "autopilot" not in arch.description.lower()


@pytest.mark.asyncio
async def test_plan_milestones_uses_verb_override_not_rail_id(tmp_path: Path) -> None:
    """Custom brief wins even when rail_id looks like greenfield (RFC-231 M2)."""
    ce = ContextEngine()
    root = await ce.create_goal("Custom", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.6",
            verb_overrides={
                "plan_milestones": {
                    "brief": "Custom slice planner for job {job_id}. schema dual-write.",
                }
            },
        )
    )
    result = await ex.invoke("plan_milestones", job_id=root.id)
    arch = await ce.get_goal(result.created_goal_ids[0])
    assert arch is not None
    assert "Custom slice planner" in arch.description
    assert root.id in arch.description
    assert "ownership units" not in arch.description.lower()


@pytest.mark.asyncio
async def test_migration_spawn_makers_from_architecture_findings(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Migrate", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="migration",
            rail_version="2.0",
            worktrees_enabled=False,
            require_plan=True,
            engine_max_parallel_goals=8,
        )
    )
    arch = await ce.create_goal("Arch", parent_id=root.id, source="decomposition")
    arch.findings = [
        json.dumps(
            {
                "wave_slices": ["schema", "dual-write", "cutover-prep"],
                "rationale": "migration slices",
            }
        ),
    ]
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 3
