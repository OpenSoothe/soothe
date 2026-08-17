"""IG-726: CE report commit + projection for Autopilot judgment."""

from __future__ import annotations

import pytest
from soothe.context.engine import ContextEngine

from soothe_autopilot.verify.report_projection import (
    build_goal_report,
    project_goal_report_for_judge,
)


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

        from soothe.config.models import AutopilotConfig
        from soothe.events.internal_bus import InternalEventBus

        from soothe_autopilot import AutopilotService
        from soothe_autopilot.verify.consensus import ConsensusResult

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
            "soothe_autopilot.verify.consensus.evaluate_goal_completion",
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
        assert updated.judged_report_revision == updated.report_revision
        assert "Implemented chat slice" in (updated.report.get("summary") or "")
        assert updated.status == "completed"
        assert mock_judge.await_count == 1
        # Judge receives CE projection (summary), not a separate workspace scrape.
        assert "Implemented chat slice" in mock_judge.await_args.args[1]

    async def test_finalize_emits_report_committed_and_is_idempotent(self) -> None:
        from unittest.mock import AsyncMock, patch

        from soothe.config.models import AutopilotConfig
        from soothe.events.internal_bus import InternalEventBus
        from soothe.events.internal_events import (
            INTERNAL_GOAL_REPORT_COMMITTED,
            InternalGoalReportCommittedEvent,
        )

        from soothe_autopilot import AutopilotService
        from soothe_autopilot.verify.consensus import ConsensusResult

        from .fakes import IdleFakeFactory

        bus = InternalEventBus()
        seen: list[InternalGoalReportCommittedEvent] = []

        async def _capture(event: object) -> None:
            if isinstance(event, InternalGoalReportCommittedEvent):
                seen.append(event)

        bus.subscribe(INTERNAL_GOAL_REPORT_COMMITTED, _capture)

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
            "soothe_autopilot.verify.consensus.evaluate_goal_completion",
            new_callable=AsyncMock,
            return_value=ConsensusResult("accept", "ok"),
        ) as mock_judge:
            await svc._apply_consensus_and_finalize(
                goal.id,
                evidence_summary="first pass",
                loop_id="w1",
            )
            # Second call: new report commit for observability, but skip judge
            # because goal is already terminal.
            await svc._apply_consensus_and_finalize(
                goal.id,
                evidence_summary="duplicate finalize",
                loop_id="w1",
            )

        assert mock_judge.await_count == 1
        assert len(seen) >= 1
        assert seen[0].goal_id == goal.id
        assert seen[0].report_revision >= 1
        updated = await ce.get_goal(goal.id)
        assert updated is not None
        assert updated.status == "completed"

    async def test_idempotent_skip_same_revision_without_recommit(self) -> None:
        from unittest.mock import AsyncMock, patch

        from soothe.config.models import AutopilotConfig
        from soothe.events.internal_bus import InternalEventBus

        from soothe_autopilot import AutopilotService
        from soothe_autopilot.verify.consensus import ConsensusResult

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
        goal = await svc.submit_task("reworkable", max_send_backs=3)
        ce.claim_goal(goal.id, loop_id="w1")

        with patch(
            "soothe_autopilot.verify.consensus.evaluate_goal_completion",
            new_callable=AsyncMock,
            return_value=ConsensusResult("send_back", "needs polish"),
        ) as mock_judge:
            await svc._apply_consensus_and_finalize(
                goal.id,
                evidence_summary="almost",
                loop_id="w1",
            )
            updated = await ce.get_goal(goal.id)
            assert updated is not None
            assert updated.judged_report_revision >= 1
            # Simulate bus redelivery: same revision, no new commit.
            # Force judged == revision and call judge gate via fake re-entry
            # by committing then resetting revision+judged to equal.
            rev = updated.report_revision
            updated.judged_report_revision = rev
            # Patch commit to no-op bump (keep same revision) — call finalize
            # after manually setting report so skip path hits judged >= rev.
            with patch.object(
                svc,
                "_commit_loop_end_report",
                new_callable=AsyncMock,
                return_value=rev,
            ):
                await svc._apply_consensus_and_finalize(
                    goal.id,
                    evidence_summary="redelivered",
                    loop_id="w1",
                )

        assert mock_judge.await_count == 1
