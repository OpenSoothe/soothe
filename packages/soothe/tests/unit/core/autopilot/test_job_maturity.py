"""RFC-230: job maturity assessor (LLM) + rail exclusivity."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.interpreter import RailEvent
from soothe.autopilot.verify.goal_dag_verifier import GoalDAGVerifier
from soothe.autopilot.verify.job_maturity import (
    JobMaturityAssessor,
    JobMaturitySnapshot,
    MaturityAssessmentVerdict,
    MaturityCriterion,
    MaturityCriterionOut,
    is_verify_class_goal,
    latch_acceptance_met,
    shallow_workspace_inventory,
)
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


class TestShallowInventory:
    def test_lists_non_coding_files(self, tmp_path: Path) -> None:
        (tmp_path / "itinerary.md").write_text("day 1\n", encoding="utf-8")
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "draft.tex").write_text("% tex\n", encoding="utf-8")
        text = shallow_workspace_inventory(tmp_path)
        assert "itinerary.md" in text
        assert "notes/" in text
        assert "draft.tex" in text


class TestJobMaturityAssessor:
    @pytest.mark.asyncio
    async def test_missing_model_fail_closed(self, tmp_path: Path) -> None:
        snap = await JobMaturityAssessor(model=None).assess(tmp_path)
        assert snap.acceptance_met is False
        assert snap.suggested_rail_signal == "needs_feedback"
        assert any("model unavailable" in b for b in snap.blockers)

    @pytest.mark.asyncio
    async def test_llm_accept_latches(self, tmp_path: Path) -> None:
        (tmp_path / "GOAL.md").write_text("Deliver a travel itinerary.\n", encoding="utf-8")
        (tmp_path / "itinerary.md").write_text("Day 1: museum\n", encoding="utf-8")
        verdict = MaturityAssessmentVerdict(
            acceptance_met=True,
            level="accepted",
            criteria=[
                MaturityCriterionOut(
                    id="itinerary",
                    description="Travel itinerary present",
                    status="pass",
                    evidence="itinerary.md",
                )
            ],
            blockers=[],
            suggested_rail_signal="job_complete",
            reasoning="Contract satisfied",
        )
        model = MagicMock()
        with patch(
            "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=verdict,
        ):
            snap = await JobMaturityAssessor(model=model).assess(
                tmp_path,
                goal_md="Deliver a travel itinerary.",
            )
        assert snap.acceptance_met is True
        assert snap.level == "accepted"
        assert snap.suggested_rail_signal == "job_complete"

    @pytest.mark.asyncio
    async def test_llm_reject_with_blockers(self, tmp_path: Path) -> None:
        verdict = MaturityAssessmentVerdict(
            acceptance_met=False,
            level="acceptance_candidate",
            criteria=[
                MaturityCriterionOut(
                    id="paper",
                    description="Draft paper",
                    status="fail",
                    evidence="missing sections",
                )
            ],
            blockers=["missing abstract"],
            suggested_rail_signal="needs_feedback",
            reasoning="Incomplete draft",
        )
        model = MagicMock()
        with patch(
            "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=verdict,
        ):
            snap = await JobMaturityAssessor(model=model).assess(
                tmp_path,
                verification_rules="Paper must include abstract and conclusion",
            )
        assert snap.acceptance_met is False
        assert "missing abstract" in snap.blockers
        assert snap.suggested_rail_signal == "needs_feedback"

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self, tmp_path: Path) -> None:
        from soothe.autopilot.verify.job_maturity import MaturityAssessmentError

        model = MagicMock()
        with (
            patch(
                "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(MaturityAssessmentError, match="failed"),
        ):
            await JobMaturityAssessor(model=model).assess(tmp_path)

    def test_snapshot_roundtrip(self) -> None:
        snap = JobMaturitySnapshot(
            assessed_at=datetime.now(UTC),
            level="accepted",
            acceptance_met=True,
            criteria=[MaturityCriterion("contract", "met", "pass", "ok")],
            blockers=[],
            suggested_rail_signal="job_complete",
            probe_summary="contract=pass",
        )
        restored = JobMaturitySnapshot.from_dict(snap.to_dict())
        assert restored is not None
        assert restored.acceptance_met is True
        assert restored.criteria[0].id == "contract"


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
        from soothe.autopilot.monitor.models import DagHealthReport, DecomposeSuggestion

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
        from soothe.autopilot.verify.job_maturity import acceptance_contract_brief

        (tmp_path / "GOAL.md").write_text("Task: pass return N\n", encoding="utf-8")
        brief = acceptance_contract_brief(workspace=tmp_path)
        assert "GOAL.md" in brief
        assert "return N" in brief

    def test_includes_verification_rules(self) -> None:
        from soothe.autopilot.verify.job_maturity import acceptance_contract_brief

        brief = acceptance_contract_brief(verification_rules="cargo test must pass")
        assert "cargo test must pass" in brief

    def test_default_is_domain_agnostic(self) -> None:
        from soothe.autopilot.verify.job_maturity import acceptance_contract_brief

        brief = acceptance_contract_brief()
        assert "acceptance contract" in brief.lower()
        assert "printf" not in brief.lower()


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
        from soothe.autopilot.jobs.top_snapshot import build_top_job_entry

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


class TestPathTokens:
    def test_extracts_non_coding_extensions(self) -> None:
        from soothe.autopilot.verify.plan_contribution import extract_path_tokens

        tokens = extract_path_tokens("wrote docs/paper.tex and plan/itinerary.pdf")
        assert any(t.endswith("paper.tex") for t in tokens)
        assert any(t.endswith("itinerary.pdf") for t in tokens)


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
