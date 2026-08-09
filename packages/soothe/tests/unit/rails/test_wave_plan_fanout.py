"""Unit tests for LLM-determined rail fan-out width (SoT = RailJobState)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support.rail_harness import catalog_rail_job_state

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.guards import GuardResult, _structural_short_circuit
from soothe.autopilot.rail.interpreter import LoopRailInterpreter
from soothe.autopilot.rail.wave_plan import (
    WavePlan,
    clamp_slice_list,
    parse_wave_plan_payload,
    resolve_fanout_slices,
)
from soothe.context import ContextEngine
from soothe.rails import LoopRailCatalog


def test_greenfield_rail_declares_llm_fanout_contract() -> None:
    rail = LoopRailCatalog().resolve("greenfield-system")
    assert "artifact" not in rail.fanout
    assert rail.fanout.get("require_plan") is True
    assert "default_modules" not in rail.fanout
    assert int(rail.fanout.get("max_waves") or 0) >= 3
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


def test_legacy_module_keys_rejected() -> None:
    assert parse_wave_plan_payload({"wave_modules": ["frontend", "api"]}, source="t") is None


def test_catalog_rejects_default_modules(tmp_path: Path) -> None:
    from soothe.rails.catalog import RailCatalogError, _normalize_fanout

    with pytest.raises(RailCatalogError, match="default_modules"):
        _normalize_fanout({"default_modules": ["core", "api"]}, path=tmp_path / "x.yml")


def test_catalog_rejects_fanout_artifact(tmp_path: Path) -> None:
    from soothe.rails.catalog import RailCatalogError, _normalize_fanout

    with pytest.raises(RailCatalogError, match="fanout.artifact"):
        _normalize_fanout({"artifact": "{job_id}/wave-plan.json"}, path=tmp_path / "x.yml")


def test_waveplan_efficiency_hint_idempotent() -> None:
    from soothe.rails.verb_defaults import (
        WAVEPLAN_EFFICIENCY_HINT,
        ensure_waveplan_efficiency_hint,
    )

    base = "REQUIRED deliverable: flat WavePlan"
    once = ensure_waveplan_efficiency_hint(base)
    twice = ensure_waveplan_efficiency_hint(once)
    assert once.count("Efficiency:") == 1
    assert twice == once
    assert WAVEPLAN_EFFICIENCY_HINT.strip() in once


@pytest.mark.asyncio
async def test_plan_milestones_description_multiform_transfer(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            require_plan=True,
        )
    )
    result = await ex.invoke("plan_milestones", job_id=root.id)
    arch = await ce.get_goal(result.created_goal_ids[0])
    assert arch is not None
    desc = arch.description
    desc_l = desc.lower()
    assert "wave_plan_path" in desc_l
    assert ".soothe/wave-plan.json" in desc
    assert "rail state" in desc_l
    assert "nested" in desc_l
    assert "record_wave_plan" not in desc
    assert "WavePlan JSON" in desc
    assert "ownership units" in desc_l
    assert "fixed default" in desc_l
    assert "Efficiency:" in desc
    assert "plain string" in desc_l
    assert "markdown" in desc_l
    assert "max_parallel_goals" not in desc
    assert "autopilot" not in desc_l
    assert "those files are ignored" not in desc_l
    assert "docs/FINDINGS" not in desc


@pytest.mark.asyncio
async def test_record_wave_plan_host_api(tmp_path: Path) -> None:
    """Host/executor API applies the plan to rail_state — not a nano tool / file."""
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
    state = await ex.job_state(root.id)
    assert state is not None
    assert state.wave_slices == ["core", "tests"]
    assert (tmp_path / root.id / "wave-plan.json").is_file()
    assert (tmp_path / ".soothe" / "wave-plan.json").is_file()


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
    assert (tmp_path / root.id / "wave-plan.json").is_file()
    assert (tmp_path / ".soothe" / "wave-plan.json").is_file()

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
async def test_plan_milestones_verifies_existing_workspace_dump(tmp_path: Path) -> None:
    """Continue/resume: dump present → pending trivial verify planner; no makers yet."""
    import json

    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            require_plan=True,
            worktrees_enabled=False,
            engine_max_parallel_goals=16,
        )
    )
    dump = {
        "wave_slices": ["core", "api"],
        "independence": "disjoint write-sets per slice",
        "rationale": "mvp continue",
    }
    (tmp_path / ".soothe").mkdir(parents=True)
    (tmp_path / ".soothe" / "wave-plan.json").write_text(json.dumps(dump), encoding="utf-8")

    result = await ex.invoke("plan_milestones", job_id=root.id)
    assert result.status == "success"
    assert "verify existing WavePlan" in result.detail
    assert "reused" not in result.detail
    assert len(result.created_goal_ids) == 1  # verify planner only

    arch = await ce.get_goal(result.created_goal_ids[0])
    assert arch is not None
    assert arch.status == "pending"
    assert arch.intake_scope == "trivial"
    assert "Verify candidate WavePlan" in (arch.description or "")
    assert "wave-plan.json" in (arch.description or "")

    state = await ex.job_state(root.id)
    assert state is not None
    assert state.wave_slices == ["core", "api"]
    root2 = await ce.get_goal(root.id)
    assert root2 is not None
    assert arch.id in (root2.depends_on or [])
    # Makers must wait until the verify planner completes + consensus ingest.
    children = [g for g in await ce.list_goals() if g.parent_id == root.id]
    assert len(children) == 1


@pytest.mark.asyncio
async def test_plan_milestones_no_dump_spawns_pending_planner(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(catalog_rail_job_state(root.id, require_plan=True))
    result = await ex.invoke("plan_milestones", job_id=root.id)
    assert result.status == "success"
    assert "reused" not in result.detail
    assert "verify existing" not in result.detail
    assert len(result.created_goal_ids) == 1
    arch = await ce.get_goal(result.created_goal_ids[0])
    assert arch is not None
    assert arch.status == "pending"
    assert arch.intake_scope is None


@pytest.mark.asyncio
async def test_retry_architecture_does_not_reuse_dump(tmp_path: Path) -> None:
    """After a failed planner, dump on disk must not auto-complete a new planner."""
    import json

    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            require_plan=True,
            worktrees_enabled=False,
        )
    )
    first = await ex.invoke("plan_milestones", job_id=root.id)
    arch_id = first.created_goal_ids[0]
    await ce.fail_goal(arch_id, error="no wave plan")

    (tmp_path / ".soothe").mkdir(parents=True)
    (tmp_path / ".soothe" / "wave-plan.json").write_text(
        json.dumps(
            {
                "wave_slices": ["core"],
                "independence": "disjoint",
                "rationale": "late dump",
            }
        ),
        encoding="utf-8",
    )

    result = await ex.invoke("retry_architecture", job_id=root.id, trigger_goal_id=arch_id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 1
    new_arch = await ce.get_goal(result.created_goal_ids[0])
    assert new_arch is not None
    assert new_arch.status == "pending"
    assert new_arch.intake_scope is None
    assert "Reused existing WavePlan" not in (new_arch.description or "")
    assert "Verify candidate WavePlan" not in (new_arch.description or "")


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


def test_parse_wave_plan_unwraps_nested_wave_plan_key() -> None:
    from soothe.autopilot.rail.wave_plan import parse_wave_plan_payload

    wrapped = {
        "job_id": "85fce19d",
        "created": "2026-08-07",
        "wave_plan": {
            "wave_slices": ["S1-foundation", "S2-session", "S3-chat"],
            "independence": "disjoint write-sets",
            "rationale": "feature domains",
        },
    }
    plan = parse_wave_plan_payload(wrapped, source="t")
    assert plan is not None
    assert plan.resolved_slice_ids() == ["S1-foundation", "S2-session", "S3-chat"]


def test_wave_plan_to_findings_json_roundtrip() -> None:
    from soothe.autopilot.rail.wave_plan import (
        parse_wave_plan_payload,
        wave_plan_to_findings_json,
    )

    plan = parse_wave_plan_payload(
        {
            "wave_slices": ["a", "b"],
            "independence": "disjoint",
            "rationale": "r",
        },
        source="t",
    )
    assert plan is not None
    bare = wave_plan_to_findings_json(plan)
    again = parse_wave_plan_payload(bare, source="roundtrip")
    assert again is not None
    assert again.resolved_slice_ids() == ["a", "b"]


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
    sa = await ex.job_state(job_a.id)
    sb = await ex.job_state(job_b.id)
    assert sa is not None and sb is not None
    assert sa.wave_slices == ["alpha", "beta"]
    assert sb.wave_slices == ["gamma", "delta", "epsilon"]
    assert (jobs_root / job_a.id / "wave-plan.json").is_file()
    assert (jobs_root / job_b.id / "wave-plan.json").is_file()


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
        )
    )
    await ex.record_wave_plan(root.id, wave_slices=[f"m{i}" for i in range(10)])
    arch = await ce.create_goal("Arch", parent_id=root.id, source="decomposition")
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    # Streaming spawn materializes all ready slices; pool enforces concurrency.
    assert len(result.created_goal_ids) == 10
    assert "spawned 10 ready makers" in result.detail


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
async def test_spawn_rich_slices_use_description_and_list_order(tmp_path: Path) -> None:
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
                "slice": "first",
                "description": "First slice write-set: apps/first/**",
                "priority": 40,  # ignored on WavePlan wire
                "tags": ["feature"],
            },
            {
                "slice": "second",
                "description": "Second slice write-set: apps/second/**",
                "priority": 90,
                "tags": ["feature"],
            },
            {
                "slice": "third",
                "description": "Third slice write-set: apps/third/**",
                "priority": 60,
            },
        ],
        rationale="list order fan-out",
    )
    arch = await ce.create_goal("Arch", parent_id=root.id, source="decomposition")
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 3
    makers = [await ce.get_goal(gid) for gid in result.created_goal_ids]
    assert makers[0] is not None and makers[1] is not None and makers[2] is not None
    # Host uses WavePlan priority when numeric; else default 75.
    assert makers[0].priority == 40
    assert makers[1].priority == 90
    assert "First slice write-set" in (makers[0].description or "")
    assert "Second slice write-set" in (makers[1].description or "")


def test_diagnose_ignores_wire_priority_on_rich_slices() -> None:
    from soothe.autopilot.rail.wave_plan import diagnose_wave_plan_payload

    result = diagnose_wave_plan_payload(
        {
            "wave_slices": [
                {
                    "slice_id": "SLC-001",
                    "slice_name": "Auth",
                    "priority": "P0",
                    "description": "auth ownership",
                },
                {
                    "slice_id": "SLC-002",
                    "priority": "high",
                },
            ],
            "independence": "disjoint",
            "rationale": "efd0ad70-shaped dump",
        },
        source="t",
    )
    assert result.plan is not None
    assert result.plan.resolved_slice_ids() == ["SLC-001", "SLC-002"]
    # Non-numeric wire priority is coerced away (None), not stored as noise.
    assert result.plan.slices[0].priority is None
    assert "priority" not in result.plan.as_decompose_plan()[0]


def test_prefer_ingest_detail_keeps_schema_over_findings_noise() -> None:
    from soothe.autopilot.rail.wave_plan import _prefer_ingest_detail

    schema = "slices.0.priority: Input should be a valid integer (source=workspace_dump:x)"
    noise = "not a JSON object (source=findings[2])"
    assert _prefer_ingest_detail(schema, noise) == schema
    assert "nested" in _prefer_ingest_detail(noise, "nested waves forbidden (source=t)").lower()


def test_diagnose_rejects_wave_slices_dict_nesting() -> None:
    from soothe.autopilot.rail.wave_plan import diagnose_wave_plan_payload

    result = diagnose_wave_plan_payload(
        {
            "wave_slices": {
                "WAVE-0": {"name": "Foundation", "slices": ["a", "b"]},
            },
            "rationale": "nested",
        },
        source="t",
    )
    assert result.plan is None
    assert "nested" in result.detail.lower()
    assert "dict" in result.detail.lower() or "object" in result.detail.lower()


def test_diagnose_rejects_wave_object_list_nesting() -> None:
    from soothe.autopilot.rail.wave_plan import diagnose_wave_plan_payload

    result = diagnose_wave_plan_payload(
        {
            "wave_slices": [
                {
                    "wave_id": "WAVE-0",
                    "name": "Foundation",
                    "slices": ["auth", "shell"],
                }
            ],
        },
        source="t",
    )
    assert result.plan is None
    assert "nested" in result.detail.lower()


def test_diagnose_rejects_object_rationale() -> None:
    from soothe.autopilot.rail.wave_plan import diagnose_wave_plan_payload

    result = diagnose_wave_plan_payload(
        {
            "wave_slices": ["a", "b"],
            "rationale": {"wave_strategy": "layered"},
        },
        source="t",
    )
    assert result.plan is None
    assert "rationale" in result.detail.lower()


def test_coerce_flat_slice_name_alias() -> None:
    from soothe.autopilot.rail.wave_plan import diagnose_wave_plan_payload

    result = diagnose_wave_plan_payload(
        {
            "slices": [{"name": "auth", "description": "login"}],
            "independence": "disjoint",
        },
        source="t",
    )
    assert result.plan is not None
    assert result.plan.resolved_slice_ids() == ["auth"]


def test_architecture_send_back_reason_includes_detail() -> None:
    from soothe.autopilot.rail.wave_plan import architecture_wave_plan_send_back_reason

    text = architecture_wave_plan_send_back_reason(
        "nested waves forbidden (wave_slices is an object/dict)"
    )
    assert "flat WavePlan" in text
    assert "Detail:" in text
    assert "nested waves forbidden" in text
