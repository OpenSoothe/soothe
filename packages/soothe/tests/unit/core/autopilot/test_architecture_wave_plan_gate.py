"""Tests for Autopilot host-owned architecture WavePlan ingest and gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from support.rail_harness import catalog_rail_job_state

from soothe.autopilot import AutopilotService
from soothe.autopilot.dispatch.models import Finding, GoalDispatchContextContribution
from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor
from soothe.autopilot.rail.wave_plan import DEFAULT_WAVE_PLAN_ARTIFACT, resolve_wave_plan_path
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus

from .fakes import IdleFakeFactory


def _mock_consensus_model(*, decision: str, reasoning: str) -> MagicMock:
    from soothe.autopilot.verify.consensus import ConsensusVerdict

    verdict = ConsensusVerdict(decision=decision, reasoning=reasoning)  # type: ignore[arg-type]
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=verdict.model_dump())
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=structured)
    return mock_model


@pytest.mark.asyncio
async def test_architecture_gate_accepts_when_wave_plan_in_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOOTHE_DATA_DIR", str(tmp_path))
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(parents=True)

    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=4),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(
            decision="send_back",
            reasoning="should not be consulted",
        ),
        runner_factory=IdleFakeFactory(),
    )
    # Force jobs_root onto the rail executor (service may have created its own).
    if svc._rail_interpreter is not None:
        svc._jobs_root = jobs_root
        svc._rail_interpreter.builtins._jobs_root = jobs_root

    root = await ce.create_goal(
        "Build scaffold",
        workspace=str(tmp_path / "ws"),
        priority=80,
        rail_id="greenfield-system",
    )
    root.role = "root"
    ex: RailBuiltinExecutor = svc._rail_interpreter.builtins
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            require_plan=True,
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
            engine_max_parallel_goals=4,
        )
    )
    spawned = await ex.invoke("plan_milestones", job_id=root.id)
    arch_id = spawned.created_goal_ids[0]
    ce.claim_goal(arch_id, loop_id="w1")

    wave_json = (
        '{"wave_modules":["frontend","ir","passes","backend","driver","tests"],'
        '"independence":"disjoint write-sets",'
        '"rationale":"crate boundaries"}'
    )
    contribution = GoalDispatchContextContribution(
        findings=[Finding(summary=wave_json, relevance_score=1.0)],
    )

    await svc._apply_consensus_and_finalize(
        arch_id,
        evidence_summary="Architecture complete with WavePlan findings entry.",
        contribution=contribution,
    )

    arch = await ce.get_goal(arch_id)
    assert arch is not None
    assert arch.status == "completed"
    assert resolve_wave_plan_path(jobs_root=jobs_root, job_id=root.id).is_file()
    assert ex.is_wave_plan_ready(root.id)


@pytest.mark.asyncio
async def test_architecture_gate_send_back_without_wave_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOOTHE_DATA_DIR", str(tmp_path))
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(parents=True)

    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=4),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(
            decision="accept",
            reasoning="should not accept without WavePlan",
        ),
        runner_factory=IdleFakeFactory(),
    )
    if svc._rail_interpreter is not None:
        svc._jobs_root = jobs_root
        svc._rail_interpreter.builtins._jobs_root = jobs_root

    root = await ce.create_goal(
        "Build scaffold",
        workspace=str(tmp_path / "ws"),
        priority=80,
        rail_id="greenfield-system",
    )
    root.role = "root"
    ex = svc._rail_interpreter.builtins
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            require_plan=True,
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
        )
    )
    spawned = await ex.invoke("plan_milestones", job_id=root.id)
    arch_id = spawned.created_goal_ids[0]
    ce.claim_goal(arch_id, loop_id="w1")

    await svc._apply_consensus_and_finalize(
        arch_id,
        evidence_summary="Step LDK-01: read_file only — no WavePlan JSON.",
        contribution=GoalDispatchContextContribution(
            findings=[Finding(summary="Step LDK-01: read_file", relevance_score=0.5)],
        ),
    )

    arch = await ce.get_goal(arch_id)
    assert arch is not None
    assert arch.status == "pending"
    assert arch.send_back_count == 1
    assert not ex.is_wave_plan_ready(root.id)


@pytest.mark.asyncio
async def test_architecture_gate_never_calls_llm_consensus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """require_plan architecture finalize must not fall through to LLM."""
    monkeypatch.setenv("SOOTHE_DATA_DIR", str(tmp_path))
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(parents=True)

    consensus = _mock_consensus_model(
        decision="accept",
        reasoning="LLM would wrongly accept",
    )
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=4),
        internal_bus=bus,
        consensus_model=consensus,
        runner_factory=IdleFakeFactory(),
    )
    if svc._rail_interpreter is not None:
        svc._jobs_root = jobs_root
        svc._rail_interpreter.builtins._jobs_root = jobs_root

    root = await ce.create_goal(
        "Build scaffold",
        workspace=str(tmp_path / "ws"),
        priority=80,
        rail_id="greenfield-system",
    )
    root.role = "root"
    ex = svc._rail_interpreter.builtins
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            require_plan=True,
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
        )
    )
    spawned = await ex.invoke("plan_milestones", job_id=root.id)
    arch_id = spawned.created_goal_ids[0]
    ce.claim_goal(arch_id, loop_id="w1")

    called: list[str] = []

    async def _boom(*_a: object, **_k: object) -> tuple[str, str]:
        called.append("evaluate")
        return "accept", "should not run"

    monkeypatch.setattr(
        "soothe.autopilot.verify.consensus.evaluate_goal_completion",
        _boom,
    )

    await svc._apply_consensus_and_finalize(
        arch_id,
        evidence_summary="Wrote docs/wave-plan.json in the project tree.",
        contribution=GoalDispatchContextContribution(
            findings=[
                Finding(
                    summary="Step EKK-01: write_file docs/wave-plan.json",
                    relevance_score=0.5,
                )
            ],
        ),
    )

    assert called == []
    consensus.with_structured_output.assert_not_called()
    arch = await ce.get_goal(arch_id)
    assert arch is not None
    assert arch.status == "pending"
    assert arch.send_back_count == 1


@pytest.mark.asyncio
async def test_workspace_wave_plan_file_not_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project-tree wave-plan.json must not satisfy is_wave_plan_ready."""
    monkeypatch.setenv("SOOTHE_DATA_DIR", str(tmp_path))
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(parents=True)
    ws = tmp_path / "ws"
    (ws / "docs").mkdir(parents=True)
    (ws / "docs" / "wave-plan.json").write_text(
        '{"wave_modules":["from-workspace"],"rationale":"legacy"}',
        encoding="utf-8",
    )
    (ws / "wave-plan.json").write_text(
        '{"wave_modules":["also-workspace"],"rationale":"legacy"}',
        encoding="utf-8",
    )
    (ws / ".soothe").mkdir(parents=True)
    (ws / ".soothe" / "wave-plan.json").write_text(
        '{"wave_modules":["dot-soothe"],"rationale":"legacy"}',
        encoding="utf-8",
    )

    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=4),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(decision="accept", reasoning="n/a"),
        runner_factory=IdleFakeFactory(),
    )
    assert svc._rail_interpreter is not None
    svc._jobs_root = jobs_root
    svc._rail_interpreter.builtins._jobs_root = jobs_root

    root = await ce.create_goal(
        "Build scaffold",
        workspace=str(ws),
        priority=80,
        rail_id="greenfield-system",
    )
    root.role = "root"
    ex = svc._rail_interpreter.builtins
    await ex.bind_job(
        catalog_rail_job_state(
            root.id,
            require_plan=True,
            wave_plan_artifact=DEFAULT_WAVE_PLAN_ARTIFACT,
        )
    )
    await ex.ingest_wave_plan(root.id)
    assert not ex.is_wave_plan_ready(root.id)
    assert not resolve_wave_plan_path(jobs_root=jobs_root, job_id=root.id).is_file()


@pytest.mark.asyncio
async def test_architecture_gate_fail_closed_without_rail_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing rail interpreter must send_back, not LLM-accept."""
    monkeypatch.setenv("SOOTHE_DATA_DIR", str(tmp_path))
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=4),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(
            decision="accept",
            reasoning="would accept without WavePlan",
        ),
        runner_factory=IdleFakeFactory(),
    )
    svc._rail_interpreter = None

    root = await ce.create_goal(
        "Build scaffold",
        workspace=str(tmp_path / "ws"),
        priority=80,
        rail_id="greenfield-system",
    )
    root.role = "root"
    arch = await ce.create_goal(
        "Architecture map",
        parent_id=root.id,
        source="decomposition",
        priority=80,
        workspace=str(tmp_path / "ws"),
        rail_id="greenfield-system",
    )
    arch.role = "planner"
    arch.rail_tags = ["architecture", "planning", "milestones"]
    ce.claim_goal(arch.id, loop_id="w1")

    called: list[str] = []

    async def _boom(*_a: object, **_k: object) -> tuple[str, str]:
        called.append("evaluate")
        return "accept", "should not run"

    monkeypatch.setattr(
        "soothe.autopilot.verify.consensus.evaluate_goal_completion",
        _boom,
    )

    await svc._apply_consensus_and_finalize(
        arch.id,
        evidence_summary="prose only",
        contribution=None,
    )

    assert called == []
    updated = await ce.get_goal(arch.id)
    assert updated is not None
    assert updated.status == "pending"
    assert updated.send_back_count == 1
