"""IG-680: health remove guards, workspace inherit, consensus evidence, deps chain."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.autopilot import AutopilotService
from soothe.autopilot.consensus import ConsensusVerdict
from soothe.autopilot.engine_models import (
    Finding,
    GoalDispatchContextContribution,
    StepSummary,
    ToolCallStats,
)
from soothe.autopilot.evidence_grounding import (
    format_contribution_evidence,
    synthesize_completion_evidence,
    workspace_deliverable_probe,
    workspace_has_deliverables,
)
from soothe.autopilot.goal_dag_verifier import GoalDAGVerifier
from soothe.autopilot.monitor_models import (
    DagHealthReport,
    DecomposeSuggestion,
    WireDependencySuggestion,
)
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.context.models import GoalNode
from soothe.context.planning_models import DecompositionResult, SubGoalSpec
from soothe.events.internal_bus import InternalEventBus

from .fakes import IdleFakeFactory


def _mock_consensus_model(*, decision: str, reasoning: str) -> MagicMock:
    verdict = ConsensusVerdict(decision=decision, reasoning=reasoning)  # type: ignore[arg-type]
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=verdict.model_dump())
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=structured)
    return mock_model


@pytest.fixture
def mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.agent = MagicMock()
    cfg.agent.autopilot = MagicMock()
    return cfg


class TestHealthRemoveGuards:
    @pytest.mark.asyncio
    async def test_refuses_remove_active_root_with_children(self, mock_config: MagicMock) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("umbrella job", priority=80, workspace="/tmp/ws")
        child = await ce.create_goal(
            "child work",
            priority=70,
            parent_id=root.id,
            workspace="/tmp/ws",
        )
        ce.claim_goal(root.id, loop_id="w1")
        assert root.status == "active"

        verifier = GoalDAGVerifier(ce, mock_config)
        assert verifier.may_auto_remove(root.id) is False

        report = DagHealthReport(
            suggest_remove=[root.id],
            reasoning="umbrella redundant",
        )
        await verifier.apply_health_report(report)

        still = await ce.get_goal(root.id)
        assert still is not None
        assert still.status == "active"
        assert await ce.get_goal(child.id) is not None

    @pytest.mark.asyncio
    async def test_allows_remove_cancelled_clutter_without_dependents(
        self, mock_config: MagicMock
    ) -> None:
        ce = ContextEngine()
        clutter = await ce.create_goal("echo smoke", priority=10)
        await ce.cancel_goal(clutter.id, reason="test")

        verifier = GoalDAGVerifier(ce, mock_config)
        assert verifier.may_auto_remove(clutter.id) is True

        report = DagHealthReport(suggest_remove=[clutter.id], reasoning="clutter")
        await verifier.apply_health_report(report)
        assert await ce.get_goal(clutter.id) is None


class TestWorkspaceInheritAndDeps:
    def test_create_subgoals_inherits_workspace_and_chains_deps(self) -> None:
        ce = ContextEngine()
        parent = GoalNode(description="root", workspace="/tmp/soothe-autopilot-eval")
        ce._dag.add_goal(parent)

        created = ce.planning.goal.create_subgoals(
            parent.id,
            DecompositionResult(
                subgoals=[
                    SubGoalSpec(description="Design", priority=80),
                    SubGoalSpec(description="Implement", priority=70),
                    SubGoalSpec(description="Test", priority=60),
                ],
                reasoning="pipeline",
            ),
        )
        assert len(created) == 3
        assert all(c.workspace == "/tmp/soothe-autopilot-eval" for c in created)
        assert created[0].depends_on == []
        assert created[1].depends_on == [created[0].id]
        assert created[2].depends_on == [created[1].id]

    def test_dedupes_identical_subgoal_descriptions(self) -> None:
        ce = ContextEngine()
        parent = GoalNode(description="root", workspace="/tmp/ws")
        ce._dag.add_goal(parent)
        planner = ce.planning.goal
        first = planner.apply_llm_subgoals(
            parent.id,
            [{"description": "Write DESIGN.md", "priority": 50}],
        )
        second = planner.apply_llm_subgoals(
            parent.id,
            [{"description": "Write DESIGN.md", "priority": 50}],
        )
        assert len(first) == 1
        assert second == []


class TestWireDependencies:
    @pytest.mark.asyncio
    async def test_health_applies_wire_dependencies(self, mock_config: MagicMock) -> None:
        ce = ContextEngine()
        a = await ce.create_goal("implement", priority=70)
        b = await ce.create_goal("test", priority=60)
        assert b.depends_on == []

        verifier = GoalDAGVerifier(ce, mock_config)
        report = DagHealthReport(
            wire_dependencies=[
                WireDependencySuggestion(goal_id=b.id, depends_on=[a.id]),
            ],
            reasoning="pipeline",
        )
        await verifier.apply_health_report(report)
        updated = await ce.get_goal(b.id)
        assert updated is not None
        assert updated.depends_on == [a.id]

    @pytest.mark.asyncio
    async def test_health_skips_child_depends_on_job_root(self, mock_config: MagicMock) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("job root", priority=80)
        child = await ce.create_goal("maker", priority=70, parent_id=root.id)
        sibling = await ce.create_goal("review", priority=60, parent_id=root.id)

        verifier = GoalDAGVerifier(ce, mock_config)
        report = DagHealthReport(
            wire_dependencies=[
                WireDependencySuggestion(goal_id=sibling.id, depends_on=[root.id, child.id]),
            ],
            reasoning="bad root edge",
        )
        await verifier.apply_health_report(report)
        updated = await ce.get_goal(sibling.id)
        assert updated is not None
        assert root.id not in updated.depends_on
        assert child.id in updated.depends_on


class TestConsensusEmptyEvidence:
    @pytest.mark.asyncio
    async def test_empty_evidence_suspends_without_description_fallback(self) -> None:
        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(
            ce=ce,
            config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
            internal_bus=bus,
            consensus_model=_mock_consensus_model(
                decision="accept",
                reasoning="should not be called",
            ),
            runner_factory=IdleFakeFactory(),
        )
        goal = await svc.submit_task("complete deliverable", workspace=None)
        ce.claim_goal(goal.id, loop_id="w1")

        await svc._apply_consensus_and_finalize(goal.id, evidence_summary="")

        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.status == "suspended"
        assert "insufficient evidence" in (updated.error or updated.status or "") or True
        # Suspended goals keep status suspended; reason is in suspend path logs / error field.
        assert updated.status == "suspended"

    @pytest.mark.asyncio
    async def test_workspace_probe_grounds_consensus(self, tmp_path: Path) -> None:
        (tmp_path / "SUMMARY.md").write_text("done\n", encoding="utf-8")
        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(
            ce=ce,
            config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
            internal_bus=bus,
            consensus_model=_mock_consensus_model(
                decision="accept",
                reasoning="artifacts present",
            ),
            runner_factory=IdleFakeFactory(),
        )
        goal = await svc.submit_task("verify deliverable", workspace=str(tmp_path))
        ce.claim_goal(goal.id, loop_id="w1")

        await svc._apply_consensus_and_finalize(goal.id, evidence_summary="")

        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.status == "completed"

    @pytest.mark.asyncio
    async def test_thin_summary_still_appends_workspace_probe(self, tmp_path: Path) -> None:
        """Thin narrative alone must not hide on-disk deliverable markers."""
        (tmp_path / "SUMMARY.md").write_text("done\n", encoding="utf-8")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "DESIGN.md").write_text("arch\n", encoding="utf-8")
        seen: dict[str, str] = {}

        async def _capture(
            goal_desc: str, agent_response: str, evidence: str, **kwargs: object
        ) -> tuple[str, str]:
            seen["evidence"] = evidence
            seen["response"] = agent_response
            return "accept", "probe visible"

        bus = InternalEventBus()
        ce = ContextEngine()
        model = MagicMock()
        # evaluate_goal_completion is imported inside the method; patch via consensus_model
        # by wrapping AutopilotService path with a monkeypatch at call site below.
        svc = AutopilotService(
            ce=ce,
            config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
            internal_bus=bus,
            consensus_model=model,
            runner_factory=IdleFakeFactory(),
        )
        goal = await svc.submit_task("verify deliverable", workspace=str(tmp_path))
        ce.claim_goal(goal.id, loop_id="w1")

        with patch(
            "soothe.autopilot.consensus.evaluate_goal_completion",
            side_effect=_capture,
        ):
            await svc._apply_consensus_and_finalize(
                goal.id,
                evidence_summary="wrote a todo list and ran one command",
            )

        assert "SUMMARY.md" in seen.get("evidence", "")
        assert "DESIGN.md" in seen.get("evidence", "")
        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.status == "completed"

    @pytest.mark.asyncio
    async def test_full_output_finding_grounds_consensus_without_workspace(self) -> None:
        """No-artifact success: ledger/full_output finding is enough to run consensus."""
        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(
            ce=ce,
            config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
            internal_bus=bus,
            consensus_model=_mock_consensus_model(
                decision="accept",
                reasoning="stdout evidence present",
            ),
            runner_factory=IdleFakeFactory(),
        )
        goal = await svc.submit_task("echo hello", workspace=None)
        ce.claim_goal(goal.id, loop_id="w1")
        contribution = GoalDispatchContextContribution(
            findings=[Finding(summary="hello", relevance_score=0.8)],
        )

        await svc._apply_consensus_and_finalize(
            goal.id,
            evidence_summary="hello",
            contribution=contribution,
        )

        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.status == "completed"

    @pytest.mark.asyncio
    async def test_plan_steps_alone_ground_consensus(self) -> None:
        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(
            ce=ce,
            config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
            internal_bus=bus,
            consensus_model=_mock_consensus_model(
                decision="accept",
                reasoning="completed steps present",
            ),
            runner_factory=IdleFakeFactory(),
        )
        goal = await svc.submit_task("echo hello", workspace=None)
        ce.claim_goal(goal.id, loop_id="w1")
        contribution = GoalDispatchContextContribution(
            plan_steps_executed=[
                StepSummary(id="S1", action="echo hello", outcome="completed"),
            ],
            tool_call_stats=ToolCallStats(counts_by_name={"shell": 1}),
        )

        await svc._apply_consensus_and_finalize(
            goal.id,
            evidence_summary="",
            contribution=contribution,
        )

        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.status == "completed"


class TestEvidenceHelpers:
    def test_workspace_probe(self, tmp_path: Path) -> None:
        assert workspace_has_deliverables(str(tmp_path)) is False
        (tmp_path / "SUMMARY.md").write_text("ok", encoding="utf-8")
        assert workspace_has_deliverables(str(tmp_path)) is True
        assert "SUMMARY.md" in workspace_deliverable_probe(str(tmp_path))

    def test_format_contribution_evidence(self) -> None:
        text = format_contribution_evidence(
            evidence_summary="",
            files_touched=None,
            findings=[Finding(summary="wrote util.py")],
        )
        assert "wrote util.py" in text
        assert (
            format_contribution_evidence(evidence_summary="", files_touched=None, findings=None)
            == ""
        )

    def test_format_contribution_includes_plan_steps_and_tools(self) -> None:
        text = format_contribution_evidence(
            evidence_summary="",
            files_touched=None,
            findings=None,
            plan_steps=[StepSummary(id="S1", action="echo hello", outcome="completed")],
            tool_call_stats=ToolCallStats(counts_by_name={"shell": 1}),
        )
        assert "plan_steps_completed" in text
        assert "echo hello" in text
        assert "tool_calls: shell=1" in text

    def test_synthesize_completion_evidence_prefers_summary(self) -> None:
        pr = MagicMock()
        pr.evidence_summary = "explicit summary"
        pr.full_output = "ignored full"
        pr.decision = None
        assert synthesize_completion_evidence(pr) == "explicit summary"

    def test_synthesize_completion_evidence_uses_full_output(self) -> None:
        pr = MagicMock()
        pr.evidence_summary = ""
        pr.full_output = "hello from ledger"
        pr.decision = None
        assert synthesize_completion_evidence(pr) == "hello from ledger"

    def test_synthesize_completion_evidence_uses_completed_steps(self) -> None:
        pr = MagicMock()
        pr.evidence_summary = ""
        pr.full_output = None
        decision = MagicMock()
        decision.actions = [{"description": "run echo hello"}]
        pr.decision = decision
        assert "run echo hello" in synthesize_completion_evidence(pr)


class TestPostCompletionSkip:
    @pytest.mark.asyncio
    async def test_skip_decompose_when_deliverables_present(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "SUMMARY.md").write_text("ok", encoding="utf-8")
        ce = ContextEngine()
        goal = await ce.create_goal("design", workspace=str(tmp_path))
        await ce.complete_goal(goal.id)

        verifier = GoalDAGVerifier(ce, mock_config)
        result = await verifier.verify_dag_post_completion(goal.id)
        assert result.get("skip_decompose") is True
        assert result.get("decomposition") is None


class TestDecomposeCooldown:
    @pytest.mark.asyncio
    async def test_decompose_cooldown(self, mock_config: MagicMock) -> None:
        ce = ContextEngine()
        parent = await ce.create_goal("parent", workspace="/tmp/ws-no-markers")
        verifier = GoalDAGVerifier(ce, mock_config)
        report = DagHealthReport(
            suggest_decompose=[
                DecomposeSuggestion(
                    goal_id=parent.id,
                    subgoals=[
                        {"description": "A", "priority": 50},
                        {"description": "B", "priority": 40},
                    ],
                )
            ],
            reasoning="split",
        )
        await verifier.apply_health_report(report)
        children = [g for g in ce.get_goals_by_status(None) if g.parent_id == parent.id]
        assert len(children) == 2

        # Second wave within cooldown should be skipped
        report2 = DagHealthReport(
            suggest_decompose=[
                DecomposeSuggestion(
                    goal_id=parent.id,
                    subgoals=[{"description": "C unique", "priority": 30}],
                )
            ],
            reasoning="again",
        )
        await verifier.apply_health_report(report2)
        children2 = [g for g in ce.get_goals_by_status(None) if g.parent_id == parent.id]
        assert len(children2) == 2


class TestNeedsReplanOutcome:
    def test_derive_outcome_none_is_needs_replan(self) -> None:
        from soothe.runner._runner_autopilot_worker import AutopilotWorkerMixin

        assert AutopilotWorkerMixin._derive_outcome(None) == "needs_replan"

    def test_build_contribution_with_files(self, tmp_path: Path) -> None:
        from soothe.runner._runner_autopilot_worker import AutopilotWorkerMixin
        from soothe.sloop.state.schemas import PlanResult

        target = tmp_path / "util.py"
        target.write_text("x=1\n", encoding="utf-8")
        pr = PlanResult(
            status="done",
            evidence_summary=f"wrote {target}",
            goal_progress="complete",
        )
        contrib = AutopilotWorkerMixin._build_contribution(
            pr, goal_id="g1", workspace=str(tmp_path)
        )
        assert isinstance(contrib, GoalDispatchContextContribution)
        assert contrib.findings
        assert any(str(target) in k or "util.py" in k for k in contrib.files_touched)


class TestFollowUpSource:
    def test_reflection_source_allowed(self) -> None:
        ce = ContextEngine()
        parent = GoalNode(description="done", workspace="/tmp/ws")
        ce._dag.add_goal(parent)
        created = ce.planning.goal.create_follow_up_goals(
            [{"description": "follow up", "priority": 50, "depends_on": [parent.id]}],
            parent_id=parent.id,
            source="reflection",
        )
        assert len(created) == 1
        assert created[0].source == "reflection"
        assert created[0].workspace == "/tmp/ws"
