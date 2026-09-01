"""IG-737: TDD / debug / parallel / worktree skill brief SoT."""

from __future__ import annotations

from soothe.rails.verb_defaults import (
    apply_maker_discipline,
    apply_planner_waveplan_hints,
    implement_goal_brief,
    plan_implementation_brief,
    resolve_verb_brief,
    scout_explore_brief,
    slice_maker_brief,
)


def test_maker_discipline_includes_worktree_skill_tdd_and_debug() -> None:
    text = apply_maker_discipline("Implement slice foo.")
    assert 'invoke_skill("using-git-worktrees")' in text
    assert "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST" in text
    assert "Systematic debugging:" in text
    # Idempotent
    assert apply_maker_discipline(text) == text


def test_planner_waveplan_hints_efficiency_and_parallel() -> None:
    text = apply_planner_waveplan_hints("Architecture map for job x.")
    assert "Efficiency:" in text
    assert "Parallel dispatch:" in text
    assert apply_planner_waveplan_hints(text) == text


def test_resolve_plan_milestones_appends_hints() -> None:
    brief = resolve_verb_brief("plan_milestones", job_id="abc", overrides=None)
    assert brief is not None
    assert "abc" in brief
    assert "Efficiency:" in brief
    assert "Parallel dispatch:" in brief


def test_scout_and_plan_implement_briefs() -> None:
    scout = scout_explore_brief(job_id="j1", domain_index=1, domain_hint="auth tests")
    assert "Systematic debugging" in scout
    assert "auth tests" in scout
    assert "do not implement fixes" in scout.lower() or "Do not implement fixes" in scout

    plan = plan_implementation_brief(job_id="j1")
    assert "Parallel dispatch:" in plan
    assert "Do not implement product code" in plan

    impl = implement_goal_brief(job_id="j1")
    assert 'invoke_skill("using-git-worktrees")' in impl
    assert "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST" in impl

    maker = slice_maker_brief(
        job_id="j1",
        slug="api",
        ownership="Own packages/api only.",
        branch="job/j1/api",
        job_branch="job/j1/_base",
    )
    assert "Slice maker [api]" in maker
    assert "Work in workspace isolation" not in maker
    assert 'invoke_skill("using-git-worktrees")' in maker
    retry = slice_maker_brief(
        job_id="j1",
        slug="api",
        ownership="Own packages/api only.",
        branch="job/j1/api-retry",
        job_branch="job/j1/_base",
        retry=True,
    )
    assert "Slice maker [api] retry" in retry
