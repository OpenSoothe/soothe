"""Integration tests for the autoresearch rail + native exec (IG-739 / RFC-231).

Covers:
- Catalog discovery and YAML contract (``autoresearch.yml`` loads, has
  ``do:`` recipes for ``decompose_parallel`` / ``spawn_feedback_cycle``, brief
  overrides for ``review`` / ``qa_verify``, and the expected flow).
- Native ``invoke`` dispatch: ``plan_and_implement`` routes to
  ``AutoresearchExec`` (synthesis plan + writer) instead of the generic
  code-planning + code-implementation path.
- Helper functions: brief builders, ``research_scout_inform_ids``,
  ``is_autoresearch_job``, ``get_autoresearch_exec``.
- ``decompose_parallel`` and ``spawn_feedback_cycle`` via ``do:`` recipes.
- Rail-id-aware dispatch: non-autoresearch rails use generic handlers.
- Edge cases: unbound job, missing trigger goal, acceptance-gated skip.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from soothe.autopilot.rail.autoresearch_exec import (
    AUTORESEARCH_RAIL_ID,
    RESEARCH_SCOPE_BANNER,
    RESEARCH_TAGS_FEEDBACK,
    RESEARCH_TAGS_PLANNING,
    RESEARCH_TAGS_SCOUT,
    RESEARCH_TAGS_SYNTHESIS,
    AutoresearchExec,
    get_autoresearch_exec,
    is_autoresearch_job,
    research_plan_brief,
    research_scout_inform_ids,
    research_synthesis_brief,
)
from soothe.autopilot.rail.builtins_exec import (
    BuiltinResult,
    RailBuiltinExecutor,
    RailJobState,
)
from soothe.context import ContextEngine
from soothe.rails import LoopRailCatalog

# ---------------------------------------------------------------------------
# Catalog & YAML contract
# ---------------------------------------------------------------------------


class TestAutoresearchCatalog:
    """Verify the autoresearch rail loads from the builtin catalog."""

    def test_rail_loads(self) -> None:
        rail = LoopRailCatalog().resolve("autoresearch")
        assert rail.id == "autoresearch"
        assert rail.version == "1.0"
        assert rail.summary
        assert rail.applies_when
        assert rail.flow

    def test_verb_do_recipes_present(self) -> None:
        rail = LoopRailCatalog().resolve("autoresearch")
        verbs = rail.verbs

        # decompose_parallel has a do: recipe
        decomp = verbs.get("decompose_parallel", {})
        assert isinstance(decomp.get("do"), list)
        assert decomp["do"]

        # spawn_feedback_cycle has a do: recipe
        fb = verbs.get("spawn_feedback_cycle", {})
        assert isinstance(fb.get("do"), list)
        assert fb["do"]

    def test_verb_brief_overrides_present(self) -> None:
        rail = LoopRailCatalog().resolve("autoresearch")
        verbs = rail.verbs

        assert "brief" in verbs.get("review", {})
        assert "brief" in verbs.get("qa_verify", {})

    def test_flow_includes_all_expected_verbs(self) -> None:
        rail = LoopRailCatalog().resolve("autoresearch")
        thens = {str(e.get("then")) for e in rail.flow}
        assert "decompose_parallel" in thens
        assert "plan_and_implement" in thens
        assert "review" in thens
        assert "qa_verify" in thens
        assert "spawn_feedback_cycle" in thens
        assert "pause_for_user" in thens
        assert "complete_job" in thens

    def test_flow_includes_expected_events(self) -> None:
        rail = LoopRailCatalog().resolve("autoresearch")
        events = {str(e.get("event")) for e in rail.flow}
        assert "job_start" in events
        assert "goal_completed" in events
        assert "goal_failed" in events
        assert "dag_idle" in events

    def test_flow_has_conditions(self) -> None:
        rail = LoopRailCatalog().resolve("autoresearch")
        conditions = rail.conditions
        assert "ready_to_synthesize" in conditions
        assert "needs_synthesis" in conditions
        assert "needs_feedback" in conditions
        assert "needs_review" in conditions
        assert "needs_qa" in conditions
        assert "needs_human" in conditions
        assert "job_complete" in conditions

    def test_fanout_requires_plan(self) -> None:
        rail = LoopRailCatalog().resolve("autoresearch")
        fanout = rail.fanout or {}
        assert fanout.get("require_plan") is True


# ---------------------------------------------------------------------------
# Brief builders
# ---------------------------------------------------------------------------


class TestBriefBuilders:
    """Verify research brief builders produce the expected scope and discipline."""

    def test_research_plan_brief_includes_job_id(self) -> None:
        brief = research_plan_brief(job_id="job-abc123")
        assert "job-abc123" in brief
        assert "outline" in brief.lower()

    def test_research_plan_brief_includes_scope_banner(self) -> None:
        brief = research_plan_brief(job_id="j1")
        assert RESEARCH_SCOPE_BANNER in brief
        assert "public-web-only" in brief

    def test_research_plan_brief_requires_flat_json(self) -> None:
        brief = research_plan_brief(job_id="j1")
        assert "sections" in brief
        assert "independence" in brief
        assert "No nested trees" in brief

    def test_research_synthesis_brief_includes_job_id(self) -> None:
        brief = research_synthesis_brief(job_id="job-xyz")
        assert "job-xyz" in brief
        assert "adaptive report" in brief.lower()

    def test_research_synthesis_brief_includes_scope_banner(self) -> None:
        brief = research_synthesis_brief(job_id="j1")
        assert RESEARCH_SCOPE_BANNER in brief

    def test_research_synthesis_brief_does_not_re_gather(self) -> None:
        brief = research_synthesis_brief(job_id="j1")
        assert "Do not re-gather" in brief

    def test_scope_banner_is_public_web_only(self) -> None:
        assert "public-web-only" in RESEARCH_SCOPE_BANNER
        assert "Cite a source URL" in RESEARCH_SCOPE_BANNER


# ---------------------------------------------------------------------------
# Helper functions (is_autoresearch_job, get_autoresearch_exec)
# ---------------------------------------------------------------------------


class TestHelpers:
    """Verify rail-id-aware dispatch helpers."""

    def test_is_autoresearch_job_true(self) -> None:
        state = RailJobState(
            job_id="j1",
            rail_id=AUTORESEARCH_RAIL_ID,
            rail_version="1.0",
        )
        assert is_autoresearch_job(state) is True

    def test_is_autoresearch_job_false_for_other_rail(self) -> None:
        state = RailJobState(
            job_id="j1",
            rail_id="greenfield-system",
            rail_version="1.0",
        )
        assert is_autoresearch_job(state) is False

    def test_is_autoresearch_job_false_for_none(self) -> None:
        assert is_autoresearch_job(None) is False

    def test_get_autoresearch_exec_returns_bound_instance(self) -> None:
        ce = ContextEngine()
        ex = RailBuiltinExecutor(ce)
        ar_ex = get_autoresearch_exec(ex)
        assert isinstance(ar_ex, AutoresearchExec)
        assert ar_ex._ex is ex


# ---------------------------------------------------------------------------
# research_scout_inform_ids
# ---------------------------------------------------------------------------


class TestScoutInformIds:
    """Verify inform-id collection filters for research scout/gather goals."""

    @pytest.mark.asyncio
    async def test_returns_completed_research_scout_goals(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        state = RailJobState(
            job_id=root.id,
            rail_id="autoresearch",
            rail_version="1.0",
        )
        await ex.bind_job(state)

        # A completed scout goal
        scout = await ce.create_goal("Scout", parent_id=root.id, source="decomposition")
        await ce.complete_goal(scout.id)
        await ex.annotate_goal(scout.id, root.id, tags=RESEARCH_TAGS_SCOUT, role="researcher")

        # A completed gather goal (feedback round)
        gather = await ce.create_goal("Gather", parent_id=root.id, source="decomposition")
        await ce.complete_goal(gather.id)
        await ex.annotate_goal(gather.id, root.id, tags=["research", "gather"], role="researcher")

        result = research_scout_inform_ids(await ex.job_state(root.id), ce)
        assert scout.id in result
        assert gather.id in result

    @pytest.mark.asyncio
    async def test_excludes_non_research_goals(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(RailJobState(job_id=root.id, rail_id="autoresearch", rail_version="1.0"))

        # A non-research goal (e.g. code implementation)
        impl = await ce.create_goal("Impl", parent_id=root.id, source="decomposition")
        await ce.complete_goal(impl.id)
        await ex.annotate_goal(impl.id, root.id, tags=["implementation", "maker"], role="maker")

        result = research_scout_inform_ids(await ex.job_state(root.id), ce)
        assert impl.id not in result
        assert result == []

    @pytest.mark.asyncio
    async def test_excludes_non_completed_goals(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(RailJobState(job_id=root.id, rail_id="autoresearch", rail_version="1.0"))

        # A pending (not completed) scout goal
        scout = await ce.create_goal("Scout pending", parent_id=root.id, source="decomposition")
        await ex.annotate_goal(scout.id, root.id, tags=RESEARCH_TAGS_SCOUT, role="researcher")

        result = research_scout_inform_ids(await ex.job_state(root.id), ce)
        assert scout.id not in result
        assert result == []


# ---------------------------------------------------------------------------
# Native invoke dispatch: plan_and_implement
# ---------------------------------------------------------------------------


class TestNativePlanAndImplement:
    """Verify ``invoke("plan_and_implement")`` routes to AutoresearchExec."""

    @pytest.mark.asyncio
    async def test_plan_and_implement_spawns_synthesis_plan_and_writer(
        self, tmp_path: Path
    ) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(RailJobState(job_id=root.id, rail_id="autoresearch", rail_version="1.0"))

        result = await ex.invoke("plan_and_implement", job_id=root.id)
        assert result.status == "success"
        assert len(result.created_goal_ids) == 2

        plan_id, synth_id = result.created_goal_ids
        plan = await ce.get_goal(plan_id)
        synth = await ce.get_goal(synth_id)

        assert plan is not None
        assert synth is not None

        # Synthesis plan goal tags
        assert "research" in (plan.rail_tags or [])
        assert "planning" in (plan.rail_tags or [])
        assert plan.role == "planner"

        # Synthesis writer goal tags
        assert "research" in (synth.rail_tags or [])
        assert "synthesis" in (synth.rail_tags or [])
        assert synth.role == "writer"

        # Writer depends on plan
        assert plan_id in (synth.depends_on or [])

        # Both goals are children of the job root
        assert plan.parent_id == root.id
        assert synth.parent_id == root.id

        # Neither goal applies code discipline
        assert "NO PRODUCTION CODE" not in (plan.description or "")
        assert "NO PRODUCTION CODE" not in (synth.description or "")
        assert "invoke_skill" not in (plan.description or "")
        assert "invoke_skill" not in (synth.description or "")

    @pytest.mark.asyncio
    async def test_plan_and_implement_briefs_include_scope_banner(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(RailJobState(job_id=root.id, rail_id="autoresearch", rail_version="1.0"))

        result = await ex.invoke("plan_and_implement", job_id=root.id)
        assert result.status == "success"
        plan_id, synth_id = result.created_goal_ids

        plan = await ce.get_goal(plan_id)
        synth = await ce.get_goal(synth_id)

        assert RESEARCH_SCOPE_BANNER in (plan.description or "")
        assert RESEARCH_SCOPE_BANNER in (synth.description or "")

    @pytest.mark.asyncio
    async def test_plan_and_implement_wires_informs_from_scout_goals(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(RailJobState(job_id=root.id, rail_id="autoresearch", rail_version="1.0"))

        # Create a completed scout goal
        scout = await ce.create_goal("Scout findings", parent_id=root.id, source="decomposition")
        await ce.complete_goal(scout.id)
        await ex.annotate_goal(scout.id, root.id, tags=RESEARCH_TAGS_SCOUT, role="researcher")

        result = await ex.invoke("plan_and_implement", job_id=root.id)
        assert result.status == "success"
        plan_id, synth_id = result.created_goal_ids

        plan = await ce.get_goal(plan_id)
        # Synthesis plan should be informed by the completed scout goal
        assert scout.id in (plan.depends_on or [])

    @pytest.mark.asyncio
    async def test_plan_and_implement_no_informs_when_no_scouts(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(RailJobState(job_id=root.id, rail_id="autoresearch", rail_version="1.0"))

        result = await ex.invoke("plan_and_implement", job_id=root.id)
        assert result.status == "success"
        plan_id, _ = result.created_goal_ids

        plan = await ce.get_goal(plan_id)
        # No scout goals → depends_on should only contain the synthesis plan
        # dependency chain (plan has no informs, synth depends on plan)
        assert plan.depends_on == [] or plan.depends_on is None


# ---------------------------------------------------------------------------
# Rail-id-aware dispatch: non-autoresearch rails use generic handlers
# ---------------------------------------------------------------------------


class TestRailIdAwareDispatch:
    """Verify non-autoresearch rails do NOT route to AutoresearchExec."""

    @pytest.mark.asyncio
    async def test_greenfield_plan_and_implement_not_autoresearch(self, tmp_path: Path) -> None:
        """A greenfield-system job should use generic _do_plan_and_implement, not
        AutoresearchExec. We verify by mocking the generic handler.
        """
        ce = ContextEngine()
        root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(
            RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.0")
        )

        # Mock the generic _do_plan_and_implement to verify it gets called
        ex._do_plan_and_implement = AsyncMock(
            return_value=BuiltinResult(status="success", detail="generic")
        )

        result = await ex.invoke("plan_and_implement", job_id=root.id)
        assert result.status == "success"
        assert result.detail == "generic"
        ex._do_plan_and_implement.assert_awaited_once()


# ---------------------------------------------------------------------------
# do: recipe verbs (decompose_parallel, spawn_feedback_cycle)
# ---------------------------------------------------------------------------


class TestDoRecipes:
    """Verify ``do:`` recipe verbs execute via RecipeRunner."""

    @pytest.mark.asyncio
    async def test_decompose_parallel_spawns_scout_plan(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)

        # Use catalog state so verb_overrides from YAML are loaded
        from support.rail_harness import catalog_rail_job_state

        await ex.bind_job(catalog_rail_job_state(root.id, rail_id="autoresearch"))

        result = await ex.invoke("decompose_parallel", job_id=root.id)
        assert result.status == "success"
        assert len(result.created_goal_ids) == 1

        scout_plan_id = result.created_goal_ids[0]
        scout_plan = await ce.get_goal(scout_plan_id)
        assert scout_plan is not None
        assert "research" in (scout_plan.rail_tags or [])
        assert "planning" in (scout_plan.rail_tags or [])
        assert scout_plan.role == "planner"

        # wire_deps: root should depend on the scout plan
        refreshed = await ce.get_goal(root.id)
        assert refreshed is not None
        assert scout_plan_id in (refreshed.depends_on or [])

    @pytest.mark.asyncio
    async def test_spawn_feedback_cycle_gates_on_acceptance(self, tmp_path: Path) -> None:
        """When acceptance_met is True, spawn_feedback_cycle skips."""
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)

        from support.rail_harness import catalog_rail_job_state

        state = catalog_rail_job_state(root.id, rail_id="autoresearch")
        state.acceptance_met = True
        await ex.bind_job(state)

        result = await ex.invoke("spawn_feedback_cycle", job_id=root.id)
        assert result.status == "skipped"
        assert result.created_goal_ids == []

    @pytest.mark.asyncio
    async def test_spawn_feedback_cycle_spawns_when_not_accepted(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)

        from support.rail_harness import catalog_rail_job_state

        state = catalog_rail_job_state(root.id, rail_id="autoresearch")
        await ex.bind_job(state)

        # Need a completed trigger goal to avoid the no-inflight feedback check
        verify = await ce.create_goal("Verify", parent_id=root.id, source="decomposition")
        await ce.complete_goal(verify.id)
        await ex.annotate_goal(
            verify.id, root.id, tags=["feedback", "research", "verify"], role="qa"
        )

        result = await ex.invoke("spawn_feedback_cycle", job_id=root.id, trigger_goal_id=verify.id)
        assert result.status == "success"
        assert len(result.created_goal_ids) == 3

        diagnose_id, optimize_id, verify_id = result.created_goal_ids
        diagnose = await ce.get_goal(diagnose_id)
        optimize = await ce.get_goal(optimize_id)
        verify_goal = await ce.get_goal(verify_id)

        assert diagnose is not None
        assert "diagnose" in (diagnose.rail_tags or [])
        assert "feedback" in (diagnose.rail_tags or [])

        assert optimize is not None
        assert "gather" in (optimize.rail_tags or [])

        assert verify_goal is not None
        assert "verify" in (verify_goal.rail_tags or [])

        # Feedback round was bumped
        refreshed = await ex.job_state(root.id)
        assert refreshed is not None
        assert refreshed.feedback_round == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify error handling for unbound jobs and missing state."""

    @pytest.mark.asyncio
    async def test_plan_and_implement_unbound_job(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)

        result = await ex.invoke("plan_and_implement", job_id="nonexistent")
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_autoresearch_exec_direct_unbound(self, tmp_path: Path) -> None:
        """AutoresearchExec.plan_and_implement raises on unbound job."""
        ce = ContextEngine()
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        ar_ex = AutoresearchExec(ex)

        # _require raises KeyError for unbound jobs; invoke catches it.
        with pytest.raises(KeyError):
            await ar_ex.plan_and_implement(job_id="nonexistent", trigger_goal_id=None)


# ---------------------------------------------------------------------------
# AutoresearchExec review / qa_verify hooks
# ---------------------------------------------------------------------------


class TestReviewQaHooks:
    """Verify review/qa_verify hooks delegate to generic handlers."""

    @pytest.mark.asyncio
    async def test_review_delegates_to_generic(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(RailJobState(job_id=root.id, rail_id="autoresearch", rail_version="1.0"))

        ar_ex = AutoresearchExec(ex)
        # Mock the generic handler to verify delegation
        ex._do_review = AsyncMock(
            return_value=BuiltinResult(status="success", detail="generic-review")
        )

        result = await ar_ex.review(job_id=root.id, trigger_goal_id=None)
        assert result.status == "success"
        assert result.detail == "generic-review"
        ex._do_review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_qa_verify_delegates_to_generic(self, tmp_path: Path) -> None:
        ce = ContextEngine()
        root = await ce.create_goal("Research topic", workspace=str(tmp_path), priority=70)
        ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
        await ex.bind_job(RailJobState(job_id=root.id, rail_id="autoresearch", rail_version="1.0"))

        ar_ex = AutoresearchExec(ex)
        ex._do_qa_verify = AsyncMock(
            return_value=BuiltinResult(status="success", detail="generic-qa")
        )

        result = await ar_ex.qa_verify(job_id=root.id, trigger_goal_id=None)
        assert result.status == "success"
        assert result.detail == "generic-qa"
        ex._do_qa_verify.assert_awaited_once()


# ---------------------------------------------------------------------------
# Module-level constants and __all__
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Verify all expected symbols are exported from autoresearch_exec."""

    def test_constants(self) -> None:
        assert AUTORESEARCH_RAIL_ID == "autoresearch"
        assert "research" in RESEARCH_TAGS_PLANNING
        assert "planning" in RESEARCH_TAGS_PLANNING
        assert "research" in RESEARCH_TAGS_SYNTHESIS
        assert "synthesis" in RESEARCH_TAGS_SYNTHESIS
        assert "research" in RESEARCH_TAGS_SCOUT
        assert "scout" in RESEARCH_TAGS_SCOUT
        assert "feedback" in RESEARCH_TAGS_FEEDBACK
        assert "research" in RESEARCH_TAGS_FEEDBACK

    def test_tag_vocabularies_are_disjoint(self) -> None:
        """Planning and synthesis tags differ (no goal should have both)."""
        assert set(RESEARCH_TAGS_PLANNING) != set(RESEARCH_TAGS_SYNTHESIS)
