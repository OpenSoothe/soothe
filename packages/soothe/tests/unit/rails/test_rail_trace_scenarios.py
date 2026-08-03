"""Multi-turn LoopRail integration scenarios with pseudo CE execution.

Runs real ContextEngine + LoopRailInterpreter; exports evaluation JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support.rail_harness import RailHarness, write_evaluation_report

from soothe.autopilot.rail.trace_store import export_trace_evaluation
from soothe.context.models import GoalNode

EVAL_REPORT_PATH = Path(__file__).resolve().parent / "evaluation_results.json"


@pytest.fixture
def harness() -> RailHarness:
    return RailHarness()


@pytest.mark.asyncio
async def test_feature_dev_happy_path_trace(harness: RailHarness) -> None:
    expected = [
        "decompose_parallel",
        "plan_and_implement",
        "review",
        "qa_verify",
        "complete_job",
    ]
    scripts = {
        ("goal_completed", "ready_to_plan"): [False, True],
        ("goal_completed", "needs_review"): [False, False, True],
        ("goal_completed", "needs_qa"): [False, False, True],
        ("dag_idle", "job_complete"): [True],
    }
    job_id = await harness.submit(
        "Add OAuth login",
        rail_id="feature-dev",
        scout_count=2,
        guard_scripts=scripts,
    )

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    report = await harness.run_turns(on_ready)
    report["scenario"] = "feature-dev-happy"
    report["expected_builtins"] = expected
    report["fired_builtins"] = harness.successful_builtins()
    report["builtins_match_expected"] = harness.successful_builtins() == expected
    assert await harness.job_completed()
    assert harness.successful_builtins() == expected, report
    assert report["job_id"] == job_id


@pytest.mark.asyncio
async def test_spike_stops_for_human(harness: RailHarness) -> None:
    expected = [
        "decompose_parallel",
        "pause_for_user",
        "complete_job",
    ]
    scripts = {
        ("goal_completed", "scouts_done"): [False, True],
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "Spike: compare SQLite vs Postgres for rails",
        rail_id="spike",
        scout_count=2,
        guard_scripts=scripts,
    )

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready)
    assert await harness.job_suspended()
    assert "plan_and_implement" not in harness.successful_builtins()
    assert harness.successful_builtins()[:2] == [
        "decompose_parallel",
        "pause_for_user",
    ]
    await harness.user_intervention()
    assert await harness.job_completed()
    assert harness.successful_builtins() == expected


@pytest.mark.asyncio
async def test_maker_checker_independent_review(harness: RailHarness) -> None:
    expected = [
        "plan_and_implement",
        "review",
        "qa_verify",
        "complete_job",
    ]
    scripts = {
        ("goal_completed", "needs_check"): [False, True],
        ("goal_completed", "needs_qa"): [False, True],
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "Harden auth token validation",
        rail_id="maker-checker",
        guard_scripts=scripts,
    )

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready)
    assert harness.successful_builtins() == expected
    reviews = [g for g in await harness.ce.list_goals() if "review" in await harness.tags(g.id)]
    assert len(reviews) >= 1


@pytest.mark.asyncio
async def test_maker_checker_send_back_replants(harness: RailHarness) -> None:
    expected_prefix = [
        "plan_and_implement",
        "review",
        "retry_branch",
    ]
    scripts = {
        ("goal_completed", "needs_check"): [False, True, True],
        ("goal_send_back", "checker_failed_recoverable"): [True],
        ("goal_completed", "needs_qa"): [False, True],
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "Critical payment fix",
        rail_id="maker-checker",
        guard_scripts=scripts,
    )

    saw_review = False

    async def on_ready(goal: GoalNode, turn: int) -> None:
        nonlocal saw_review
        tags = await harness.tags(goal.id)
        if "review" in tags and not saw_review:
            saw_review = True
            await harness.activate(goal.id)
            await harness.pseudo_send_back(goal.id)
            return
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready, max_turns=40)
    fired = harness.successful_builtins()
    assert fired[:3] == expected_prefix, fired
    assert "retry_branch" in fired
    assert await harness.job_completed()
    assert "qa_verify" in fired
    assert "complete_job" in fired


@pytest.mark.asyncio
async def test_pr_review_no_implement(harness: RailHarness) -> None:
    expected = ["review", "qa_verify", "complete_job"]
    scripts = {
        ("goal_completed", "needs_qa"): [True],
        ("goal_completed", "needs_human"): [False, False],
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "Review PR #42",
        rail_id="pr-review",
        guard_scripts=scripts,
    )

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready)
    assert harness.successful_builtins() == expected
    assert "plan_and_implement" not in harness.successful_builtins()
    assert "decompose_parallel" not in harness.successful_builtins()


@pytest.mark.asyncio
async def test_export_evaluation_bundle(harness: RailHarness, tmp_path: Path) -> None:
    """Run a minimal spike and write evaluation JSON (smoke for export)."""
    scripts = {
        ("goal_completed", "scouts_done"): [True],
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "Tiny spike",
        rail_id="spike",
        scout_count=1,
        guard_scripts=scripts,
    )

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready)
    await harness.user_intervention()
    expected = ["decompose_parallel", "pause_for_user", "complete_job"]
    report = harness.evaluation(expected_builtins=expected)
    report["scenario"] = "spike-export-smoke"
    out = write_evaluation_report(tmp_path / "eval.json", [report])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert data["scenarios"][0]["fired_builtins"] == expected


@pytest.mark.asyncio
async def test_suite_writes_evaluation_results_json() -> None:
    """End-to-end: run core scenarios and export ``evaluation_results.json``."""
    reports: list[dict] = []

    h1 = RailHarness()
    await h1.submit(
        "Add OAuth login",
        rail_id="feature-dev",
        scout_count=2,
        guard_scripts={
            ("goal_completed", "ready_to_plan"): [False, True],
            ("goal_completed", "needs_review"): [False, False, True],
            ("goal_completed", "needs_qa"): [False, False, True],
            ("dag_idle", "job_complete"): [True],
        },
    )

    async def complete_all(goal: GoalNode, turn: int) -> None:
        await h1.pseudo_complete(goal.id)

    await h1.run_turns(complete_all)
    exp1 = [
        "decompose_parallel",
        "plan_and_implement",
        "review",
        "qa_verify",
        "complete_job",
    ]
    r1 = export_trace_evaluation(h1.job_id or "", h1.trace, expected_builtins=exp1)
    r1["scenario"] = "feature-dev-happy"
    reports.append(r1)

    h2 = RailHarness()
    await h2.submit(
        "Spike",
        rail_id="spike",
        scout_count=2,
        guard_scripts={
            ("goal_completed", "scouts_done"): [False, True],
            ("dag_idle", "job_complete"): [True],
        },
    )

    async def complete2(goal: GoalNode, turn: int) -> None:
        await h2.pseudo_complete(goal.id)

    await h2.run_turns(complete2)
    await h2.user_intervention()
    exp2 = ["decompose_parallel", "pause_for_user", "complete_job"]
    r2 = export_trace_evaluation(h2.job_id or "", h2.trace, expected_builtins=exp2)
    r2["scenario"] = "spike-human-gate"
    reports.append(r2)

    h3 = RailHarness()
    await h3.submit(
        "Harden auth",
        rail_id="maker-checker",
        guard_scripts={
            ("goal_completed", "needs_check"): [False, True],
            ("goal_completed", "needs_qa"): [False, True],
            ("dag_idle", "job_complete"): [True],
        },
    )

    async def complete3(goal: GoalNode, turn: int) -> None:
        await h3.pseudo_complete(goal.id)

    await h3.run_turns(complete3)
    exp3 = ["plan_and_implement", "review", "qa_verify", "complete_job"]
    r3 = export_trace_evaluation(h3.job_id or "", h3.trace, expected_builtins=exp3)
    r3["scenario"] = "maker-checker-happy"
    reports.append(r3)

    path = write_evaluation_report(EVAL_REPORT_PATH, reports)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["passed"] is True, data
    assert data["scenario_count"] == 3
    print(f"\nLoopRail evaluation report written to: {path}")
    for s in data["scenarios"]:
        print(
            f"  - {s['scenario']}: match={s['builtins_match_expected']} fired={s['fired_builtins']}"
        )
