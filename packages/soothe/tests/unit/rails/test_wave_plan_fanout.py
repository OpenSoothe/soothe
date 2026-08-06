"""Unit tests for LLM-determined rail fan-out width (IG-699 / IG-700)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.guards import GuardResult, _structural_short_circuit
from soothe.autopilot.rail.interpreter import LoopRailInterpreter
from soothe.autopilot.rail.wave_plan import (
    DEFAULT_WAVE_PLAN_ARTIFACT,
    WavePlan,
    clamp_module_list,
    load_wave_plan,
    resolve_fanout_modules,
    resolve_wave_plan_path,
)
from soothe.context import ContextEngine
from soothe.rails import LoopRailCatalog


def test_greenfield_rail_declares_llm_fanout_contract() -> None:
    rail = LoopRailCatalog().resolve("greenfield-system")
    assert rail.fanout.get("artifact") == "{job_id}/wave-plan.json"
    assert rail.fanout.get("require_plan") is True
    assert "default_modules" not in rail.fanout
    assert rail.fanout.get("max_waves") == 3
    dag_idle = [e for e in rail.flow if e.get("event") == "dag_idle"]
    assert any(e.get("when") == "architecture_ready" for e in dag_idle)


def test_architecture_ready_requires_wave_plan_when_flagged() -> None:
    base = {
        "architecture_goal_ids": ["a1"],
        "all_architecture_terminal": True,
        "implementation_goal_ids": [],
        "require_plan": True,
        "wave_plan_ready": False,
        "pending_or_active_count": 0,
    }
    blocked = _structural_short_circuit(
        condition_name="architecture_ready",
        event="goal_completed",
        trigger_tags=["architecture"],
        structural=base,
    )
    assert isinstance(blocked, GuardResult)
    assert blocked.matched is False

    ready = _structural_short_circuit(
        condition_name="architecture_ready",
        event="goal_completed",
        trigger_tags=["architecture"],
        structural={**base, "wave_plan_ready": True},
    )
    assert ready is not None and ready.matched is True

    idle = _structural_short_circuit(
        condition_name="architecture_ready",
        event="dag_idle",
        trigger_tags=[],
        structural={**base, "wave_plan_ready": True},
    )
    assert idle is not None and idle.matched is True


def test_wave_plan_schema_and_resolve() -> None:
    plan = WavePlan.model_validate(
        {
            "wave_modules": ["frontend", "ir", "passes", "backend", "driver", "tests"],
            "independence": "disjoint",
            "rationale": "crate boundaries",
        }
    )
    assert len(plan.resolved_module_names()) == 6
    r = resolve_fanout_modules(
        wave_modules=None,
        decompose_plan=None,
        plan=plan,
        max_modules=16,
        require_plan=True,
    )
    assert r.source == "wave_plan"
    assert r.modules == plan.resolved_module_names()


def test_missing_plan_fails_closed() -> None:
    mods, from_n = clamp_module_list(["a", "b", "a", "c"], max_modules=2)
    assert mods == ["a", "b"]
    assert from_n == 3

    r = resolve_fanout_modules(
        wave_modules=None,
        decompose_plan=None,
        plan=None,
        max_modules=8,
        require_plan=True,
    )
    assert r.source == "missing_plan"
    assert r.modules == []


def test_load_wave_plan_file(tmp_path: Path) -> None:
    path = resolve_wave_plan_path(
        jobs_root=tmp_path, job_id="job-abc", artifact=DEFAULT_WAVE_PLAN_ARTIFACT
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "modules": [
                    {"module": "frontend", "description": "UI"},
                    {"module": "api", "priority": 70},
                ]
            }
        ),
        encoding="utf-8",
    )
    plan = load_wave_plan(path)
    assert plan is not None
    assert plan.resolved_module_names() == ["frontend", "api"]


def test_catalog_rejects_default_modules(tmp_path: Path) -> None:
    from soothe.rails.catalog import RailCatalogError, _normalize_fanout

    with pytest.raises(RailCatalogError, match="default_modules"):
        _normalize_fanout({"default_modules": ["core", "api"]}, path=tmp_path / "x.yml")


def test_normalize_rewrites_legacy_workspace_artifact() -> None:
    from soothe.autopilot.rail.wave_plan import normalize_wave_plan_artifact

    assert normalize_wave_plan_artifact(".soothe/wave-plan.json") == DEFAULT_WAVE_PLAN_ARTIFACT
    assert normalize_wave_plan_artifact("{job_id}/wave-plan.json") == DEFAULT_WAVE_PLAN_ARTIFACT


@pytest.mark.asyncio
async def test_plan_milestones_description_hides_artifact_path(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.3",
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
            require_plan=True,
        )
    )
    result = await ex.invoke("plan_milestones", job_id=root.id)
    arch = await ce.get_goal(result.created_goal_ids[0])
    assert arch is not None
    assert "jobs/" not in arch.description
    assert ".soothe/wave-plan" not in arch.description
    assert "record_wave_plan" in arch.description
    assert "ownership units" in arch.description.lower()
    assert "fixed default" in arch.description.lower() or "never substitutes" in arch.description


@pytest.mark.asyncio
async def test_record_wave_plan_tool_factory(tmp_path: Path) -> None:
    from soothe.autopilot.rail.wave_plan_tools import make_record_wave_plan_tool

    ce = ContextEngine()
    root = await ce.create_goal("Build", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.3",
            require_plan=True,
        )
    )
    tool = make_record_wave_plan_tool(ex, root.id)
    assert tool.name == "record_wave_plan"
    result = await tool.ainvoke(
        {"wave_modules": ["core", "tests"], "rationale": "mvp"},
    )
    assert "2 modules" in result
    assert resolve_wave_plan_path(jobs_root=tmp_path, job_id=root.id).is_file()


@pytest.mark.asyncio
async def test_spawn_wave_makers_from_record_wave_plan(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.3",
            worktrees_enabled=False,
            engine_max_parallel_goals=16,
            require_plan=True,
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
        )
    )
    recorded = await ex.record_wave_plan(
        root.id,
        wave_modules=[
            "frontend",
            "ir",
            "passes",
            "backend-x86",
            "driver",
            "tests",
        ],
        rationale="compiler crate map",
    )
    assert recorded is not None
    plan_path = resolve_wave_plan_path(
        jobs_root=tmp_path, job_id=root.id, artifact=DEFAULT_WAVE_PLAN_ARTIFACT
    )
    assert plan_path.is_file()
    # Must not write into the project workspace tree.
    assert not (tmp_path / ".soothe" / "wave-plan.json").exists()

    arch = await ce.create_goal(
        "Architecture",
        parent_id=root.id,
        source="decomposition",
        rail_id="greenfield-system",
    )
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture", "planning"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 6


@pytest.mark.asyncio
async def test_two_jobs_same_workspace_isolated_wave_plans(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    jobs_root = tmp_path / "jobs"
    ce = ContextEngine()
    job_a = await ce.create_goal("Job A", workspace=str(workspace), priority=70)
    job_b = await ce.create_goal("Job B", workspace=str(workspace), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=jobs_root)

    for job, modules in (
        (job_a, ["alpha", "beta"]),
        (job_b, ["gamma", "delta", "epsilon"]),
    ):
        await ex.bind_job(
            RailJobState(
                job_id=job.id,
                rail_id="greenfield-system",
                rail_version="1.3",
                worktrees_enabled=False,
                engine_max_parallel_goals=16,
                require_plan=True,
                wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
            )
        )
        await ex.record_wave_plan(job.id, wave_modules=modules)
        arch = await ce.create_goal("Arch", parent_id=job.id, source="decomposition")
        await ce.complete_goal(arch.id)
        await ex.annotate_goal(arch.id, job.id, tags=["architecture"], role="planner")

    ra = await ex.invoke("spawn_wave_makers", job_id=job_a.id)
    rb = await ex.invoke("spawn_wave_makers", job_id=job_b.id)
    assert ra.status == "success" and len(ra.created_goal_ids) == 2
    assert rb.status == "success" and len(rb.created_goal_ids) == 3
    assert resolve_wave_plan_path(jobs_root=jobs_root, job_id=job_a.id).read_text(
        encoding="utf-8"
    ) != resolve_wave_plan_path(jobs_root=jobs_root, job_id=job_b.id).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_spawn_skips_without_llm_plan(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.3",
            worktrees_enabled=False,
            require_plan=True,
        )
    )
    arch = await ce.create_goal("Arch", parent_id=root.id, source="decomposition")
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "skipped"
    assert "wave plan" in result.detail.lower() or "missing" in result.detail.lower()
    goals = [g for g in await ce.list_goals() if g.parent_id == root.id and g.role == "maker"]
    assert goals == []


@pytest.mark.asyncio
async def test_spawn_clamps_llm_plan_to_engine_budget(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.3",
            worktrees_enabled=False,
            engine_max_parallel_goals=3,
            require_plan=True,
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
        )
    )
    await ex.record_wave_plan(root.id, wave_modules=[f"m{i}" for i in range(10)])
    arch = await ce.create_goal("Arch", parent_id=root.id, source="decomposition")
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 3
    assert "clamped_from=10" in result.detail


@pytest.mark.asyncio
async def test_bind_feature_dev_skips_fanout_state(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Feature", workspace=str(tmp_path), priority=70)
    interp = LoopRailInterpreter(ce, jobs_root=tmp_path)
    await interp.bind_job(root.id, rail_id="feature-dev", workspace=str(tmp_path))
    state = await interp.builtins.job_state(root.id)
    assert state is not None
    assert state.require_plan is False
    assert state.wave_modules is None
    # No wave-plan file created for non-fanout rails.
    assert not any(tmp_path.rglob("wave-plan.json"))


@pytest.mark.asyncio
async def test_spawn_from_architecture_findings(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.3",
            worktrees_enabled=False,
            require_plan=True,
            engine_max_parallel_goals=8,
        )
    )
    arch = await ce.create_goal("Arch", parent_id=root.id, source="decomposition")
    arch.findings = [
        json.dumps({"wave_modules": ["core", "cli", "tests"], "rationale": "mvp"}),
    ]
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 3
