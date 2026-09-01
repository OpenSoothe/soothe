"""Autoresearch rail integration tests — multi-turn scenarios (IG-739 / RFC-231).

Runs the real ``ContextEngine`` + ``LoopRailInterpreter`` with scripted guards
to exercise the autoresearch rail end-to-end:

- Happy path: decompose → plan_and_implement → review → qa_verify → complete_job
- Feedback loop: needs_feedback triggers spawn_feedback_cycle (gate → bump →
  diagnose → optimize → verify), then re-synthesize and complete.
- Acceptance-gated skip: acceptance already met → spawn_feedback_cycle skipped.
- Human pause: needs_human → pause_for_user → resume → complete_job.
- Native dispatch: synthesis goals carry research tags (not code tags).
- Branch stuck: goal_failed → retry_branch.

Guard scripting: ``ScriptedGuardEvaluator`` evaluates conditions in flow order
(priority 100 for all flow rules; first match wins, ``allow_multiple=False``).
Each condition key maps to a FIFO deque; when exhausted, the condition returns
``matched=False``. Tests therefore script only the ``True`` responses needed to
advance the scenario — unscripted or exhausted conditions fall through to the
next rule.

Run::

    uv run pytest packages/soothe/tests/integration/rails -q --run-integration
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from soothe.context.models import GoalNode
from soothe.rails.trace_store import export_trace_evaluation
from support.rail_harness import RailHarness, write_evaluation_report

EVAL_REPORT_PATH = Path(__file__).resolve().parent / "autoresearch_evaluation_results.json"


@pytest.fixture
def harness() -> RailHarness:
    return RailHarness()


# ---------------------------------------------------------------------------
# Happy path: decompose → plan_and_implement → review → qa_verify → complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autoresearch_happy_path_trace(harness: RailHarness) -> None:
    """Full happy path: scout plan → synthesis → review → QA → complete.

    Event sequence:
      job_start → decompose_parallel (spawns scout plan)
      scout completes → ready_to_synthesize → plan_and_implement (plan+writer)
      synthesis writer completes → needs_review → review
      review completes → needs_qa → qa_verify
      qa completes → dag_idle → job_complete → complete_job
    """
    expected = [
        "decompose_parallel",
        "plan_and_implement",
        "review",
        "qa_verify",
        "complete_job",
    ]
    scripts = {
        ("goal_completed", "ready_to_synthesize"): [True],
        ("goal_completed", "needs_review"): [True],
        ("goal_completed", "needs_qa"): [True],
        ("dag_idle", "job_complete"): [True],
    }
    job_id = await harness.submit(
        "Compare top open-source vector databases for RAG workloads",
        rail_id="autoresearch",
        guard_scripts=scripts,
    )

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    report = await harness.run_turns(on_ready, max_turns=30)
    report["scenario"] = "autoresearch-happy"
    report["expected_builtins"] = expected
    report["fired_builtins"] = harness.successful_builtins()
    report["builtins_match_expected"] = harness.successful_builtins() == expected
    assert await harness.job_completed()
    assert harness.successful_builtins() == expected, report
    assert report["job_id"] == job_id


# ---------------------------------------------------------------------------
# Feedback cycle: needs_feedback → spawn_feedback_cycle → re-synthesize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autoresearch_feedback_cycle_then_synthesize(
    harness: RailHarness,
) -> None:
    """Sufficiency verify fails → feedback cycle (diagnose→optimize→verify) →
    synthesis retry → review → QA → complete.

    The feedback cycle fires via ``needs_feedback`` on ``dag_idle`` (all prior
    goals complete, acceptance not yet met). The gate in the YAML ``do:`` recipe
    checks acceptance_met (False) and no inflight feedback (none), then bumps
    feedback_round and spawns diagnose→optimize→verify.
    """
    scripts = {
        # Scout plan completes → not ready (feedback needed first)
        ("goal_completed", "ready_to_synthesize"): [False],
        # dag_idle after scout → needs_feedback → spawn_feedback_cycle
        ("dag_idle", "needs_feedback"): [True],
        # After feedback verify completes → ready to synthesize
        ("goal_completed", "needs_synthesis"): [True],
        # After synthesis writer completes → needs review
        ("goal_completed", "needs_review"): [True],
        # After review completes → needs QA
        ("goal_completed", "needs_qa"): [True],
        # After QA completes → job done
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "Survey state-of-the-art LLM inference optimizations",
        rail_id="autoresearch",
        guard_scripts=scripts,
    )

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready, max_turns=50)
    fired = harness.successful_builtins()
    assert "spawn_feedback_cycle" in fired, f"feedback cycle not fired: {fired}"
    assert "plan_and_implement" in fired, f"plan_and_implement not fired: {fired}"
    assert "review" in fired
    assert "qa_verify" in fired
    assert "complete_job" in fired
    assert await harness.job_completed()


# ---------------------------------------------------------------------------
# Acceptance-gated skip: feedback cycle does not fire when acceptance met
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autoresearch_feedback_skipped_when_acceptance_met(
    harness: RailHarness,
) -> None:
    """When acceptance is already met, spawn_feedback_cycle is skipped.

    The gate op (``unless: acceptance_met``) short-circuits the recipe before
    bumping feedback_round or spawning goals. The result status is ``skipped``.
    """
    scripts = {
        ("goal_completed", "ready_to_synthesize"): [True],
        ("goal_completed", "needs_review"): [True],
        ("goal_completed", "needs_qa"): [True],
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "Quick fact-check: is Python dynamically typed?",
        rail_id="autoresearch",
        guard_scripts=scripts,
    )

    # Mark acceptance as met before any feedback fires
    state = await harness.interpreter.builtins.job_state(harness.job_id or "")
    assert state is not None
    state.acceptance_met = True

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready, max_turns=30)
    assert "spawn_feedback_cycle" not in harness.successful_builtins()
    assert await harness.job_completed()


# ---------------------------------------------------------------------------
# Human pause: needs_human → pause_for_user → resume → complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autoresearch_pauses_for_human_then_completes(
    harness: RailHarness,
) -> None:
    """When research is blocked, the rail pauses for human input, then
    resumes to complete after user intervention.

    Unlike the spike rail (which has an explicit ``user_intervention`` flow
    rule), the autoresearch rail pauses via ``needs_human`` on
    ``goal_completed`` and completes via ``dag_idle → job_complete`` after
    the user intervenes and the DAG goes idle again.
    """
    expected = [
        "decompose_parallel",
        "pause_for_user",
        "complete_job",
    ]
    scripts = {
        # After scout plan completes → needs human (ambiguous topic)
        ("goal_completed", "needs_human"): [True],
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "Research ambiguous topic requiring scope clarification",
        rail_id="autoresearch",
        guard_scripts=scripts,
    )

    async def on_ready(goal: GoalNode, turn: int) -> None:
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready, max_turns=30)
    assert await harness.job_suspended()
    assert "plan_and_implement" not in harness.successful_builtins()
    assert harness.successful_builtins()[:2] == [
        "decompose_parallel",
        "pause_for_user",
    ]
    # User intervenes — autoresearch has no user_intervention rule, so we
    # tick dag_idle to trigger job_complete → complete_job.
    await harness.user_intervention()
    await harness.tick_dag_idle()
    assert await harness.job_completed()
    assert harness.successful_builtins() == expected


# ---------------------------------------------------------------------------
# Native dispatch: synthesis goals carry research tags, not code tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autoresearch_synthesis_goals_carry_research_tags(
    harness: RailHarness,
) -> None:
    """Verify plan_and_implement spawns research-tagged goals (not code tags).

    The native ``AutoresearchExec.plan_and_implement`` spawns:
      1. synthesis plan goal (research, planning, role=planner)
      2. synthesis writer goal (research, synthesis, role=writer)

    Neither goal should carry code-discipline tags (implementation, maker).
    """
    scripts = {
        ("goal_completed", "ready_to_synthesize"): [True],
        ("goal_completed", "needs_review"): [True],
        ("goal_completed", "needs_qa"): [True],
        ("dag_idle", "job_complete"): [True],
    }
    await harness.submit(
        "How do autonomous agents handle context window limits?",
        rail_id="autoresearch",
        guard_scripts=scripts,
    )

    synthesis_goal_ids: list[str] = []

    async def on_ready(goal: GoalNode, turn: int) -> None:
        tags = await harness.tags(goal.id)
        if "synthesis" in tags or "planning" in tags:
            synthesis_goal_ids.append(goal.id)
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready, max_turns=30)
    assert await harness.job_completed()
    # plan_and_implement fired → at least one synthesis goal created
    assert "plan_and_implement" in harness.successful_builtins()
    assert len(synthesis_goal_ids) >= 1
    for gid in synthesis_goal_ids:
        tags = await harness.tags(gid)
        assert "research" in tags, f"goal {gid} missing 'research' tag: {tags}"
        # Must NOT have code-discipline tags
        assert "implementation" not in tags, (
            f"goal {gid} has 'implementation' tag (code discipline): {tags}"
        )
        assert "maker" not in tags, f"goal {gid} has 'maker' tag (code discipline): {tags}"


# ---------------------------------------------------------------------------
# Decompose spawns a scout plan goal with research tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autoresearch_decompose_spawns_research_scout_plan(
    harness: RailHarness,
) -> None:
    """decompose_parallel (YAML do: recipe) spawns a scout plan goal with
    research+planning tags, and wires root dependencies.

    The ``wire_deps: root_waits_on: self`` op makes the job root depend on
    the scout plan goal id.
    """
    scripts = {
        ("goal_completed", "ready_to_synthesize"): [True],
        ("goal_completed", "needs_review"): [True],
        ("goal_completed", "needs_qa"): [True],
        ("dag_idle", "job_complete"): [True],
    }
    job_id = await harness.submit(
        "Compare SQLite vs Postgres for agent memory",
        rail_id="autoresearch",
        guard_scripts=scripts,
    )

    scout_goal_ids: list[str] = []

    async def on_ready(goal: GoalNode, turn: int) -> None:
        tags = await harness.tags(goal.id)
        if "research" in tags and "planning" in tags:
            scout_goal_ids.append(goal.id)
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready, max_turns=30)
    assert await harness.job_completed()
    assert "decompose_parallel" in harness.successful_builtins()
    assert len(scout_goal_ids) >= 1
    # Root should depend on the scout plan (wire_deps root_waits_on: self)
    root = await harness.ce.get_goal(job_id)
    assert root is not None
    assert scout_goal_ids[0] in (root.depends_on or []), (
        f"root {job_id} does not depend on scout plan {scout_goal_ids[0]}"
    )


# ---------------------------------------------------------------------------
# Branch stuck: goal_failed → retry_branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autoresearch_branch_stuck_retries(harness: RailHarness) -> None:
    """When a research goal fails and branch_is_stuck, retry_branch fires.

    The ``goal_failed`` event with ``branch_is_stuck`` condition triggers
    ``retry_branch``, which re-spawns the failed goal. After retry, the
    synthesis completes and the job finishes.
    """
    scripts = {
        ("goal_completed", "ready_to_synthesize"): [True],
        ("goal_completed", "needs_review"): [True],
        ("goal_completed", "needs_qa"): [True],
        ("dag_idle", "job_complete"): [True],
        # First failure → branch is stuck → retry
        ("goal_failed", "branch_is_stuck"): [True],
    }
    await harness.submit(
        "Research with a flaky gather step",
        rail_id="autoresearch",
        guard_scripts=scripts,
    )

    saw_failure = False

    async def on_ready(goal: GoalNode, turn: int) -> None:
        nonlocal saw_failure
        tags = await harness.tags(goal.id)
        # Fail the first synthesis-ish goal to trigger retry_branch
        if "synthesis" in tags and not saw_failure:
            saw_failure = True
            await harness.pseudo_fail(goal.id)
            return
        await harness.pseudo_complete(goal.id)

    await harness.run_turns(on_ready, max_turns=50)
    fired = harness.successful_builtins()
    assert "retry_branch" in fired, f"retry_branch not fired: {fired}"
    assert "complete_job" in fired
    assert await harness.job_completed()


# ---------------------------------------------------------------------------
# Suite-level: export evaluation JSON for CI review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suite_writes_evaluation_results_json() -> None:
    """End-to-end: run core autoresearch scenarios and export evaluation JSON."""
    reports: list[dict] = []

    # Scenario 1: happy path
    h1 = RailHarness()
    await h1.submit(
        "Compare top vector databases",
        rail_id="autoresearch",
        guard_scripts={
            ("goal_completed", "ready_to_synthesize"): [True],
            ("goal_completed", "needs_review"): [True],
            ("goal_completed", "needs_qa"): [True],
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
    r1["scenario"] = "autoresearch-happy"
    reports.append(r1)

    # Scenario 2: human pause
    h2 = RailHarness()
    await h2.submit(
        "Ambiguous research topic",
        rail_id="autoresearch",
        guard_scripts={
            ("goal_completed", "needs_human"): [True],
            ("dag_idle", "job_complete"): [True],
        },
    )

    async def complete2(goal: GoalNode, turn: int) -> None:
        await h2.pseudo_complete(goal.id)

    await h2.run_turns(complete2)
    await h2.user_intervention()
    await h2.tick_dag_idle()
    exp2 = ["decompose_parallel", "pause_for_user", "complete_job"]
    r2 = export_trace_evaluation(h2.job_id or "", h2.trace, expected_builtins=exp2)
    r2["scenario"] = "autoresearch-human-gate"
    reports.append(r2)

    path = write_evaluation_report(EVAL_REPORT_PATH, reports)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["passed"] is True, data
    assert data["scenario_count"] == 2
    print(f"\nAutoresearch rail evaluation report written to: {path}")
    for s in data["scenarios"]:
        print(
            f"  - {s['scenario']}: match={s['builtins_match_expected']} fired={s['fired_builtins']}"
        )
