"""IG-726: CE report commit + projection for Autopilot judgment."""

from __future__ import annotations

import pytest

from soothe.autopilot.verify.report_projection import (
    build_goal_report,
    project_goal_report_for_judge,
)
from soothe.context.engine import ContextEngine


class TestReportProjection:
    def test_build_minimal_summary_when_empty(self) -> None:
        report = build_goal_report(outcome="completed", summary="")
        assert report["outcome"] == "completed"
        assert "Loop ended" in report["summary"]

    def test_project_includes_findings_and_effects(self) -> None:
        report = build_goal_report(
            outcome="completed",
            summary="Merged chat branch",
            findings=["tests green"],
            effects=[{"kind": "git", "statement": "merged w1/chat"}],
        )
        text = project_goal_report_for_judge(report)
        assert "Merged chat branch" in text
        assert "tests green" in text
        assert "merged w1/chat" in text

    def test_project_empty_report(self) -> None:
        assert project_goal_report_for_judge(None) == ""
        assert project_goal_report_for_judge({}) == ""


@pytest.mark.asyncio
class TestCommitGoalReport:
    async def test_commit_bumps_revision_and_stores_report(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("do thing")
        await ce.activate_goal(goal.id, loop_id="w1")

        rev1 = await ce.commit_goal_report(
            goal.id,
            build_goal_report(outcome="completed", summary="first"),
        )
        assert rev1 == 1
        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.report is not None
        assert updated.report["summary"] == "first"
        assert updated.report_revision == 1

        rev2 = await ce.commit_goal_report(
            goal.id,
            build_goal_report(outcome="completed", summary="second"),
        )
        assert rev2 == 2
        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.report["summary"] == "second"
        assert updated.report_revision == 2

    async def test_commit_missing_goal_raises(self) -> None:
        ce = ContextEngine()
        with pytest.raises(KeyError):
            await ce.commit_goal_report("missing", {"outcome": "failed", "summary": "x"})

    async def test_finalize_commits_report_before_judge(self) -> None:
        from unittest.mock import AsyncMock, patch

        from soothe.autopilot import AutopilotService
        from soothe.autopilot.verify.consensus import ConsensusResult
        from soothe.config.models import AutopilotConfig
        from soothe.events.internal_bus import InternalEventBus

        from .fakes import IdleFakeFactory

        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(
            ce=ce,
            config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
            internal_bus=bus,
            consensus_model=object(),
            runner_factory=IdleFakeFactory(),
        )
        goal = await svc.submit_task("maker chat", max_send_backs=3)
        ce.claim_goal(goal.id, loop_id="w1")

        with patch(
            "soothe.autopilot.verify.consensus.evaluate_goal_completion",
            new_callable=AsyncMock,
            return_value=ConsensusResult("accept", "ok"),
        ) as mock_judge:
            await svc._apply_consensus_and_finalize(
                goal.id,
                evidence_summary="Implemented chat slice",
                loop_id="w1",
            )

        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.report is not None
        assert updated.report_revision >= 1
        assert "Implemented chat slice" in (updated.report.get("summary") or "")
        assert updated.status == "completed"
        assert mock_judge.await_count == 1
        # Judge receives CE projection (summary), not a separate workspace scrape.
        assert "Implemented chat slice" in mock_judge.await_args.args[1]
