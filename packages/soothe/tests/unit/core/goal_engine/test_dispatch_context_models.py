"""Tests for GoalDispatchContext* models (RFC-222 revised)."""

from __future__ import annotations

import pytest

from soothe.core.goal_engine.models import (
    FileTouchSummary,
    Finding,
    GoalDispatchContextBundle,
    GoalDispatchContextContribution,
    ParentFinding,
    PriorStepSummary,
    StepSummary,
    ToolCallStats,
)


class TestPrimitiveSummaries:
    def test_prior_step_summary_minimal(self) -> None:
        s = PriorStepSummary(
            id="S1",
            description="run tests",
            status="completed",
            goal_id_origin="g1",
        )
        assert s.id == "S1"
        assert s.status == "completed"
        assert s.duration_ms is None

    def test_file_touch_summary_records_op(self) -> None:
        f = FileTouchSummary(
            content_hash="abc123",
            last_op="write",
            goal_id_origin="g1",
        )
        assert f.last_op == "write"

    def test_parent_finding_clamps_relevance(self) -> None:
        with pytest.raises(ValueError, match="less than or equal to"):
            ParentFinding(goal_id_origin="g1", summary="x", relevance_score=1.5)

    def test_finding_truncation_via_field_max_length(self) -> None:
        # summary max_length is 2000 chars by design
        with pytest.raises(ValueError):
            Finding(summary="x" * 2001)

    def test_tool_call_stats_aggregates(self) -> None:
        s = ToolCallStats(
            counts_by_name={"read_file": 5, "edit_file": 2},
            failures_by_name={"edit_file": 1},
        )
        assert s.total_calls() == 7
        assert s.total_failures() == 1


class TestBundleBounds:
    def test_bundle_default_is_empty(self) -> None:
        b = GoalDispatchContextBundle()
        assert b.prior_plan_steps == []
        assert b.files_touched == {}
        assert b.findings == []
        assert b.cached_system_prompt_hash is None

    def test_bundle_accepts_under_caps(self) -> None:
        b = GoalDispatchContextBundle(
            findings=[ParentFinding(goal_id_origin=f"g{i}", summary=f"f{i}") for i in range(20)],
        )
        assert len(b.findings) == 20

    def test_bundle_rejects_too_many_findings(self) -> None:
        with pytest.raises(ValueError, match="findings.*exceeds max"):
            GoalDispatchContextBundle(
                findings=[
                    ParentFinding(goal_id_origin=f"g{i}", summary=f"f{i}") for i in range(21)
                ],
            )

    def test_bundle_rejects_too_many_files(self) -> None:
        with pytest.raises(ValueError, match="files_touched.*exceeds max"):
            GoalDispatchContextBundle(
                files_touched={
                    f"/p{i}": FileTouchSummary(
                        content_hash=f"h{i}", last_op="read", goal_id_origin="g"
                    )
                    for i in range(51)
                }
            )

    def test_bundle_rejects_too_many_plan_steps(self) -> None:
        with pytest.raises(ValueError, match="prior_plan_steps.*exceeds max"):
            GoalDispatchContextBundle(
                prior_plan_steps=[
                    PriorStepSummary(
                        id=f"S{i}", description="x", status="completed", goal_id_origin="g"
                    )
                    for i in range(31)
                ]
            )


class TestContributionBounds:
    def test_contribution_default_is_empty(self) -> None:
        c = GoalDispatchContextContribution()
        assert c.plan_steps_executed == []
        assert c.findings == []
        assert c.tool_call_stats.total_calls() == 0

    def test_contribution_rejects_too_many_findings(self) -> None:
        with pytest.raises(ValueError, match="findings.*exceeds max"):
            GoalDispatchContextContribution(
                findings=[Finding(summary=f"f{i}") for i in range(21)],
            )

    def test_contribution_rejects_too_many_files(self) -> None:
        with pytest.raises(ValueError, match="files_touched.*exceeds max"):
            GoalDispatchContextContribution(
                files_touched={
                    f"/p{i}": FileTouchSummary(
                        content_hash=f"h{i}", last_op="edit", goal_id_origin="g"
                    )
                    for i in range(51)
                }
            )

    def test_contribution_rejects_too_many_plan_steps(self) -> None:
        with pytest.raises(ValueError, match="plan_steps_executed.*exceeds max"):
            GoalDispatchContextContribution(
                plan_steps_executed=[
                    StepSummary(id=f"S{i}", action="x", outcome="completed") for i in range(31)
                ]
            )


class TestSerialization:
    """Bundle/contribution must round-trip through JSON for IPC."""

    def test_bundle_round_trip_json(self) -> None:
        original = GoalDispatchContextBundle(
            prior_plan_steps=[
                PriorStepSummary(id="S1", description="d", status="completed", goal_id_origin="g1"),
            ],
            files_touched={
                "/a": FileTouchSummary(content_hash="h", last_op="write", goal_id_origin="g1"),
            },
            findings=[ParentFinding(goal_id_origin="g1", summary="ok")],
            cached_system_prompt_hash="prefix-h",
        )
        encoded = original.model_dump_json()
        decoded = GoalDispatchContextBundle.model_validate_json(encoded)
        assert decoded == original

    def test_contribution_round_trip_json(self) -> None:
        original = GoalDispatchContextContribution(
            plan_steps_executed=[StepSummary(id="S1", action="run", outcome="completed")],
            files_touched={
                "/a": FileTouchSummary(content_hash="h", last_op="edit", goal_id_origin="g1"),
            },
            findings=[Finding(summary="done")],
            tool_call_stats=ToolCallStats(counts_by_name={"read_file": 1}),
        )
        encoded = original.model_dump_json()
        decoded = GoalDispatchContextContribution.model_validate_json(encoded)
        assert decoded == original
