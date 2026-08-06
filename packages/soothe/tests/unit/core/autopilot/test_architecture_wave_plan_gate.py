"""Tests for Autopilot host-owned architecture WavePlan ingest (IG-704)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.autopilot import AutopilotService
from soothe.autopilot.dispatch.models import Finding, GoalDispatchContextContribution
from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
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
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.4",
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
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.4",
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
