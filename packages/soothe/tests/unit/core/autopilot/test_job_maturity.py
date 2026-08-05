"""IG-692 / RFC-230: job maturity assessor + rail exclusivity."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.autopilot.goal_dag_verifier import GoalDAGVerifier
from soothe.autopilot.maturity import (
    JobMaturityAssessor,
    MaturityCriterion,
    is_verify_class_goal,
    latch_acceptance_met,
)
from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.interpreter import RailEvent
from soothe.context import ContextEngine


class TestIsVerifyClassGoal:
    def test_qa_tag(self) -> None:
        assert is_verify_class_goal(rail_tags=["qa"], role=None)

    def test_qa_role(self) -> None:
        assert is_verify_class_goal(rail_tags=[], role="qa")

    def test_feedback_verify(self) -> None:
        assert is_verify_class_goal(rail_tags=["feedback", "verify"], role=None)

    def test_review_not_verify(self) -> None:
        assert not is_verify_class_goal(rail_tags=["review"], role="checker")


class TestLatchAcceptanceMet:
    def test_rail_or_ce(self) -> None:
        assert latch_acceptance_met(rail_acceptance_met=True, maturity=None)
        assert latch_acceptance_met(
            rail_acceptance_met=False,
            maturity={"acceptance_met": True},
        )
        assert not latch_acceptance_met(rail_acceptance_met=False, maturity=None)
        assert not latch_acceptance_met(
            rail_acceptance_met=False,
            maturity={"acceptance_met": False},
        )


class TestJobMaturityAssessor:
    def test_empty_workspace_no_accept(self, tmp_path: Path) -> None:
        snap = JobMaturityAssessor().assess_workspace(tmp_path)
        assert snap.acceptance_met is False
        assert snap.suggested_rail_signal == "needs_feedback"

    def test_stub_elf_fails_goal_probe(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[workspace]\nmembers=[]\n", encoding="utf-8")
        fix = tmp_path / "tests" / "fixtures"
        fix.mkdir(parents=True)
        (fix / "simple_return.c").write_text("int main(){return 42;}\n", encoding="utf-8")
        ccc = tmp_path / "target" / "debug"
        ccc.mkdir(parents=True)
        bin_path = ccc / "ccc"
        bin_path.write_bytes(
            b'#!/bin/sh\ncp /dev/null "$3" 2>/dev/null; printf \'\\x7fELF\' > "$3"; dd if=/dev/zero bs=1 count=60 >> "$3" 2>/dev/null\n'
        )
        bin_path.chmod(0o755)

        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            if argv and argv[0] == "cargo":
                return MagicMock(returncode=0, stdout="ok\n", stderr="")
            if argv and str(argv[0]).endswith("ccc"):
                out = Path(argv[3])
                out.write_bytes(b"\x7fELF" + b"\x00" * 60)
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=126, stdout="", stderr="exec format error")

        with patch("soothe.autopilot.maturity.subprocess.run", side_effect=fake_run):
            snap = JobMaturityAssessor().assess_workspace(tmp_path)
        assert snap.acceptance_met is False
        ids = {c.id: c.status for c in snap.criteria}
        assert ids.get("cargo_build") == "pass"
        assert ids.get("goal_simple_return") == "fail"

    def test_all_probes_pass_latches(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[workspace]\nmembers=[]\n", encoding="utf-8")

        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            return MagicMock(returncode=0, stdout="ok\n", stderr="")

        with patch("soothe.autopilot.maturity.subprocess.run", side_effect=fake_run):
            snap = JobMaturityAssessor(cargo_timeout_s=5.0).assess_workspace(tmp_path)
        assert snap.acceptance_met is True
        assert snap.level == "accepted"
        assert snap.suggested_rail_signal == "job_complete"

    def test_snapshot_roundtrip(self) -> None:
        from datetime import UTC, datetime

        from soothe.autopilot.maturity import JobMaturitySnapshot

        snap = JobMaturitySnapshot(
            assessed_at=datetime.now(UTC),
            level="accepted",
            acceptance_met=True,
            criteria=[MaturityCriterion("cargo_build", "build", "pass", "ok")],
            blockers=[],
            suggested_rail_signal="job_complete",
            probe_summary="cargo_build=pass",
        )
        restored = JobMaturitySnapshot.from_dict(snap.to_dict())
        assert restored is not None
        assert restored.acceptance_met is True
        assert restored.criteria[0].id == "cargo_build"


class TestRailExclusivity:
    @pytest.mark.asyncio
    async def test_post_completion_skips_rail_job(self) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("job", priority=80, workspace="/tmp/ws")
        root.rail_id = "greenfield-system"
        child = await ce.create_goal(
            "QA verify",
            parent_id=root.id,
            priority=85,
            workspace="/tmp/ws",
        )
        child.rail_tags = ["qa"]
        verifier = GoalDAGVerifier(ce, MagicMock())
        result = await verifier.verify_dag_post_completion(child.id)
        assert result.get("skip_decompose") is True
        assert result.get("new_goals") == []
        assert result.get("decomposition") is None

    @pytest.mark.asyncio
    async def test_health_decompose_skipped_for_rail(self) -> None:
        from soothe.autopilot.monitor_models import DagHealthReport, DecomposeSuggestion

        ce = ContextEngine()
        root = await ce.create_goal("job", priority=80)
        root.rail_id = "greenfield-system"
        verifier = GoalDAGVerifier(ce, MagicMock())
        report = DagHealthReport(
            reasoning="x",
            suggest_decompose=[
                DecomposeSuggestion(goal_id=root.id, subgoals=[{"description": "review"}])
            ],
        )
        with patch.object(ce.planning.goal, "apply_llm_subgoals") as apply:
            apply.return_value = ["x"]
            await verifier.apply_health_report(report)
            apply.assert_not_called()


class TestAcceptanceMetPersist:
    @pytest.mark.asyncio
    async def test_set_acceptance_met(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("job", priority=80)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(
            RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.1")
        )
        await ex.set_acceptance_met(root.id, met=True)
        state = await ex.job_state(root.id)
        assert state is not None
        assert state.acceptance_met is True
        path = tmp_path / root.id / "rail_state.json"
        assert path.is_file()
        assert '"acceptance_met": true' in path.read_text(encoding="utf-8")


class TestAcceptanceContractBrief:
    def test_includes_goal_md(self, tmp_path: Path) -> None:
        from soothe.autopilot.maturity import acceptance_contract_brief

        (tmp_path / "GOAL.md").write_text("Task: pass return N\n", encoding="utf-8")
        brief = acceptance_contract_brief(workspace=tmp_path)
        assert "GOAL.md" in brief
        assert "return N" in brief

    def test_includes_verification_rules(self) -> None:
        from soothe.autopilot.maturity import acceptance_contract_brief

        brief = acceptance_contract_brief(verification_rules="cargo test must pass")
        assert "cargo test must pass" in brief


class TestEnsureTriggerTags:
    @pytest.mark.asyncio
    async def test_repairs_empty_annotation_from_ce(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("job", priority=80)
        integ = await ce.create_goal("integrate", parent_id=root.id, priority=70)
        integ.rail_tags = ["integrate", "wave-1"]
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(
            RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.1")
        )
        # Clear in-memory tags to simulate loss
        state = await ex.job_state(root.id)
        assert state is not None
        state.annotations.pop(integ.id, None)
        repaired = await ex.ensure_trigger_tags(root.id, integ.id)
        assert "integrate" in repaired
        tags = await ex.tags_by_goal(root.id)
        assert "integrate" in tags.get(integ.id, [])


class TestTopMaturityField:
    def test_build_top_includes_maturity(self) -> None:
        from soothe.autopilot.top_snapshot import build_top_job_entry

        entry = build_top_job_entry(
            job_id="j1",
            status="pending",
            priority=80,
            description="job",
            workspace="/tmp/ws",
            dag={
                "root_id": "j1",
                "nodes": [{"id": "j1", "status": "pending"}],
                "edges": [],
            },
            loops=[],
            include_terminal=True,
            maturity={"level": "scaffold", "acceptance_met": False, "blockers": ["x"]},
        )
        assert entry is not None
        assert entry["maturity"]["acceptance_met"] is False
        assert entry["maturity"]["level"] == "scaffold"


class TestDagIdleEmission:
    @pytest.mark.asyncio
    async def test_dag_idle_when_children_terminal(self) -> None:
        from soothe.autopilot import AutopilotService
        from soothe.config.models import AutopilotConfig
        from soothe.events.internal_bus import InternalEventBus

        from .fakes import IdleFakeFactory

        ce = ContextEngine()
        bus = InternalEventBus()
        cfg = AutopilotConfig(max_loops=1, max_parallel_goals=1)
        svc = AutopilotService(
            ce=ce,
            config=cfg,
            internal_bus=bus,
            runner_factory=IdleFakeFactory(),
            subscribe_to_bus=False,
        )
        handled: list[str] = []

        class _FakeInterp:
            _rails: dict = {}

            async def handle(self, event: RailEvent) -> list:
                handled.append(event.name)
                return []

            async def bind_job(self, *a, **k):  # type: ignore[no-untyped-def]
                return None

        svc._rail_interpreter = _FakeInterp()  # type: ignore[assignment]
        root = await ce.create_goal("job", priority=80, workspace="/tmp/ws")
        root.rail_id = "greenfield-system"
        root.status = "pending"
        child = await ce.create_goal("done child", parent_id=root.id, priority=50)
        await ce.complete_goal(child.id)

        await svc._maybe_emit_dag_idle(child.id)
        assert "dag_idle" in handled
