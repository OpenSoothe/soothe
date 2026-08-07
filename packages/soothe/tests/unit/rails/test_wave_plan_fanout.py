"""Unit tests for LLM-determined rail fan-out width."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support.rail_harness import catalog_rail_job_state

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.guards import GuardResult, _structural_short_circuit
from soothe.autopilot.rail.interpreter import LoopRailInterpreter
from soothe.autopilot.rail.wave_plan import (
    DEFAULT_WAVE_PLAN_ARTIFACT,
    WavePlan,
    clamp_slice_list,
    load_wave_plan,
    resolve_fanout_slices,
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
            "wave_slices": ["frontend", "ir", "passes", "backend", "driver", "tests"],
            "independence": "disjoint",
            "rationale": "crate boundaries",
        }
    )
    assert len(plan.resolved_slice_ids()) == 6
    r = resolve_fanout_slices(
        wave_slices=None,
        decompose_plan=None,
        plan=plan,
        max_slices=16,
        require_plan=True,
    )
    assert r.source == "wave_plan"
    assert r.slices == plan.resolved_slice_ids()


def test_missing_plan_fails_closed() -> None:
    slices, from_n = clamp_slice_list(["a", "b", "a", "c"], max_slices=2)
    assert slices == ["a", "b"]
    assert from_n == 3

    r = resolve_fanout_slices(
        wave_slices=None,
        decompose_plan=None,
        plan=None,
        max_slices=8,
        require_plan=True,
    )
    assert r.source == "missing_plan"
    assert r.slices == []


def test_load_wave_plan_file(tmp_path: Path) -> None:
    path = resolve_wave_plan_path(
        jobs_root=tmp_path, job_id="job-abc", artifact=DEFAULT_WAVE_PLAN_ARTIFACT
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "slices": [
                    {"slice": "frontend", "description": "UI"},
                    {"slice": "api", "priority": 70},
                ]
            }
        ),
        encoding="utf-8",
    )
    plan = load_wave_plan(path)
    assert plan is not None
    assert plan.resolved_slice_ids() == ["frontend", "api"]


def test_legacy_module_keys_rejected(tmp_path: Path) -> None:
    path = resolve_wave_plan_path(
        jobs_root=tmp_path, job_id="job-legacy", artifact=DEFAULT_WAVE_PLAN_ARTIFACT
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"wave_modules": ["frontend", "api"], "rationale": "legacy"}),
        encoding="utf-8",
    )
    assert load_wave_plan(path) is None


def test_catalog_rejects_default_modules(tmp_path: Path) -> None:
    from soothe.rails.catalog import RailCatalogError, _normalize_fanout

    with pytest.raises(RailCatalogError, match="default_modules"):
        _normalize_fanout({"default_modules": ["core", "api"]}, path=tmp_path / "x.yml")


def test_normalize_rewrites_legacy_workspace_artifact() -> None:
    from soothe.autopilot.rail.wave_plan import normalize_wave_plan_artifact

    assert normalize_wave_plan_artifact(".soothe/wave-plan.json") == DEFAULT_WAVE_PLAN_ARTIFACT
    assert normalize_wave_plan_artifact("wave-plan.json") == DEFAULT_WAVE_PLAN_ARTIFACT
    assert normalize_wave_plan_artifact("docs/wave-plan.json") == DEFAULT_WAVE_PLAN_ARTIFACT
    assert normalize_wave_plan_artifact("{job_id}/wave-plan.json") == DEFAULT_WAVE_PLAN_ARTIFACT


@pytest.mark.asyncio
async def test_plan_milestones_description_hides_artifact_path(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
            require_plan=True,
        )
    )
    result = await ex.invoke("plan_milestones", job_id=root.id)
    arch = await ce.get_goal(result.created_goal_ids[0])
    assert arch is not None
    assert "jobs/" not in arch.description
    assert ".soothe/wave-plan" in arch.description  # forbid list, not path SoT
    assert "docs/wave-plan.json" in arch.description
    assert "record_wave_plan" not in arch.description
    assert "project workspace tree" in arch.description
    assert "WavePlan JSON" in arch.description
    assert "ownership units" in arch.description.lower()
    assert "fixed default" in arch.description.lower()
    assert "host persists" not in arch.description.lower()
    assert "max_parallel_goals" not in arch.description
    assert "autopilot" not in arch.description.lower()


@pytest.mark.asyncio
async def test_record_wave_plan_host_api(tmp_path: Path) -> None:
    """Host/executor API persists the plan — not a nano agent tool."""
    ce = ContextEngine()
    root = await ce.create_goal("Build", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.4",
            require_plan=True,
        )
    )
    plan = await ex.record_wave_plan(
        root.id,
        wave_slices=["core", "tests"],
        rationale="mvp",
    )
    assert plan is not None
    assert plan.resolved_slice_ids() == ["core", "tests"]
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
            rail_version="1.4",
            worktrees_enabled=False,
            engine_max_parallel_goals=16,
            require_plan=True,
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
        )
    )
    recorded = await ex.record_wave_plan(
        root.id,
        wave_slices=[
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
async def test_retry_architecture_replants_planner(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            require_plan=True,
            wave_slices=["stale"],
        )
    )
    first = await ex.invoke("plan_milestones", job_id=root.id)
    arch_id = first.created_goal_ids[0]
    await ce.fail_goal(arch_id, error="no wave plan")

    result = await ex.invoke("retry_architecture", job_id=root.id, trigger_goal_id=arch_id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 1
    new_id = result.created_goal_ids[0]
    assert new_id != arch_id
    root2 = await ce.get_goal(root.id)
    assert root2 is not None
    assert arch_id not in (root2.depends_on or [])
    assert new_id in (root2.depends_on or [])
    state = await ex.job_state(root.id)
    assert state is not None
    assert state.wave_slices is None
    pruned = state.annotations.get(arch_id)
    assert pruned is not None and pruned.branch_status == "pruned"


def test_architecture_failed_guard() -> None:
    matched = _structural_short_circuit(
        condition_name="architecture_failed",
        event="goal_failed",
        trigger_tags=["architecture", "planning", "milestones"],
        structural={"architecture_goal_ids": ["a1"], "pending_or_active_count": 0},
    )
    assert matched is not None and matched.matched is True

    skip_maker = _structural_short_circuit(
        condition_name="architecture_failed",
        event="goal_failed",
        trigger_tags=["implementation", "maker"],
        structural={"architecture_goal_ids": ["a1"], "pending_or_active_count": 0},
    )
    assert skip_maker is not None and skip_maker.matched is False

    # Bare planning (scout/plan rails) must not trigger architecture retry.
    skip_planning = _structural_short_circuit(
        condition_name="architecture_failed",
        event="goal_failed",
        trigger_tags=["planning"],
        structural={"pending_or_active_count": 0},
    )
    assert skip_planning is not None and skip_planning.matched is False


def test_parse_wave_plan_from_nested_embed() -> None:
    from soothe.autopilot.rail.wave_plan import parse_wave_plan_from_findings

    text = (
        "Here is the plan:\n"
        '{"wave_slices":["frontend","ir","passes"],'
        '"independence":"disjoint",'
        '"rationale":"crate map",'
        '"slices":[{"slice":"frontend","description":"UI layer"}]}'
    )
    plan = parse_wave_plan_from_findings([text])
    assert plan is not None
    assert "frontend" in plan.resolved_slice_ids()


@pytest.mark.asyncio
async def test_two_jobs_same_workspace_isolated_wave_plans(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    jobs_root = tmp_path / "jobs"
    ce = ContextEngine()
    job_a = await ce.create_goal("Job A", workspace=str(workspace), priority=70)
    job_b = await ce.create_goal("Job B", workspace=str(workspace), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=jobs_root)

    for job, slices in (
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
        await ex.record_wave_plan(job.id, wave_slices=slices)
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
    await ex.record_wave_plan(root.id, wave_slices=[f"m{i}" for i in range(10)])
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
    assert state.wave_slices is None
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
        json.dumps({"wave_slices": ["core", "cli", "tests"], "rationale": "mvp"}),
    ]
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 3


@pytest.mark.asyncio
async def test_spawn_rich_slices_use_description_and_priority(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.7",
            worktrees_enabled=False,
            require_plan=True,
            engine_max_parallel_goals=2,
        )
    )
    await ex.record_wave_plan(
        root.id,
        slices=[
            {
                "slice": "low-prio",
                "description": "Low slice write-set: apps/low/**",
                "priority": 40,
                "tags": ["feature"],
            },
            {
                "slice": "high-prio",
                "description": "High slice write-set: apps/high/**",
                "priority": 90,
                "tags": ["feature"],
            },
            {
                "slice": "mid-prio",
                "description": "Mid slice write-set: apps/mid/**",
                "priority": 60,
            },
        ],
        rationale="priority clamp",
    )
    arch = await ce.create_goal("Arch", parent_id=root.id, source="decomposition")
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 2
    makers = [await ce.get_goal(gid) for gid in result.created_goal_ids]
    assert makers[0] is not None and makers[1] is not None
    assert makers[0].priority == 90
    assert makers[1].priority == 60
    assert "High slice write-set" in (makers[0].description or "")
    assert "Mid slice write-set" in (makers[1].description or "")
    assert "module ownership" not in (makers[0].description or "").lower()
    assert "clamped_from=3" in result.detail
