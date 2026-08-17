"""Tests for ContextProjector (RFC-222 revised, RFC-625, IG-712).

Covers linear chain, diamond join, fan-out, soft (informs) parents,
recency-ordering, bound enforcement, and graceful handling of missing
parents.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from soothe.config.models import ContextProjectionConfig
from soothe.context.models import GoalNode
from soothe.goal_contracts import (
    Finding,
    GoalDispatchContextContribution,
    GoalEffect,
    GoalEffectKind,
    StepSummary,
    ToolCallStats,
)

from soothe_autopilot.dispatch.projector import ContextProjector
from soothe_autopilot.dispatch.store import InMemoryGoalDispatchContextStore

# ---- Fixtures -----------------------------------------------------------


def _goal(
    gid: str,
    *,
    depends_on: list[str] | None = None,
    informs: list[str] | None = None,
    updated_offset_sec: float = 0.0,
    report: dict | None = None,
    created_offset_sec: float = 0.0,
) -> GoalNode:
    g = GoalNode(
        id=gid,
        description=f"goal {gid}",
        depends_on=depends_on or [],
        informs=informs or [],
    )
    g.updated_at = datetime.now(UTC) - timedelta(seconds=updated_offset_sec)
    g.created_at = datetime.now(UTC) - timedelta(seconds=created_offset_sec)
    if report is not None:
        g.report = report
    return g


def _contribution(
    *,
    effects: list[tuple[GoalEffectKind, str, str]] | None = None,  # (kind, ref, statement)
    findings: list[tuple[str, float]] | None = None,  # (summary, relevance)
    steps: list[tuple[str, str]] | None = None,  # (id, action)
    tool_counts: dict[str, int] | None = None,
    origin: str = "?",
) -> GoalDispatchContextContribution:
    return GoalDispatchContextContribution(
        plan_steps_executed=[
            StepSummary(id=sid, action=action, outcome="completed") for sid, action in (steps or [])
        ],
        effects=[
            GoalEffect(kind=kind, ref=ref, statement=statement, goal_id_origin=origin)
            for kind, ref, statement in (effects or [])
        ],
        findings=[Finding(summary=s, relevance_score=r) for s, r in (findings or [])],
        tool_call_stats=ToolCallStats(counts_by_name=tool_counts or {}),
    )


def _default_projector(store) -> ContextProjector:
    return ContextProjector(store, ContextProjectionConfig())


# ---- Empty / degenerate cases ------------------------------------------


class TestDegenerate:
    @pytest.mark.asyncio
    async def test_no_parents_returns_empty_bundle(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        proj = _default_projector(store)
        goal = _goal("g1")
        out = await proj.project(goal, {"g1": goal})
        assert out.findings == []
        assert out.prior_effects == []
        assert out.prior_plan_steps == []

    @pytest.mark.asyncio
    async def test_parent_with_no_stored_contribution(self) -> None:
        """Goal declares depends_on=['p1'] but the store has nothing for p1."""
        store = InMemoryGoalDispatchContextStore()
        proj = _default_projector(store)
        parent = _goal("p1")
        goal = _goal("g1", depends_on=["p1"])
        out = await proj.project(goal, {"p1": parent, "g1": goal})
        assert out.findings == []
        assert out.prior_effects == []


# ---- DAG shapes --------------------------------------------------------


class TestLinearChain:
    @pytest.mark.asyncio
    async def test_a_to_b_merges_a_into_bundle(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "A",
            _contribution(
                findings=[("a-finding", 0.9)],
                effects=[("mutate", "/x", "edited /x")],
                steps=[("S1", "do A")],
                origin="A",
            ),
        )
        a = _goal("A")
        b = _goal("B", depends_on=["A"])
        proj = _default_projector(store)
        out = await proj.project(b, {"A": a, "B": b})

        assert len(out.findings) == 1
        assert out.findings[0].summary == "a-finding"
        assert out.findings[0].goal_id_origin == "A"
        assert len(out.prior_effects) == 1
        assert out.prior_effects[0].ref == "/x"
        assert out.prior_effects[0].goal_id_origin == "A"
        assert out.prior_plan_steps[0].id == "S1"
        assert out.prior_plan_steps[0].goal_id_origin == "A"


class TestDiamondJoin:
    @pytest.mark.asyncio
    async def test_diamond_unions_both_parents(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "A",
            _contribution(
                findings=[("from-A", 0.5)],
                effects=[("mutate", "/a", "touched a")],
                origin="A",
            ),
        )
        await store.put(
            "B",
            _contribution(
                findings=[("from-B", 0.5)],
                effects=[("produce", "/b", "created b")],
                origin="B",
            ),
        )
        a = _goal("A", updated_offset_sec=10)
        b = _goal("B", updated_offset_sec=0)  # more recent
        g = _goal("G", depends_on=["A", "B"])

        proj = _default_projector(store)
        out = await proj.project(g, {"A": a, "B": b, "G": g})

        # Both parents contribute findings.
        summaries = {f.summary for f in out.findings}
        assert summaries == {"from-A", "from-B"}

        refs = {e.ref for e in out.prior_effects}
        assert refs == {"/a", "/b"}

    @pytest.mark.asyncio
    async def test_diamond_with_same_ref_recency_wins(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "OLD",
            _contribution(effects=[("mutate", "/x", "old digest")], origin="OLD"),
        )
        await store.put(
            "NEW",
            _contribution(effects=[("mutate", "/x", "new digest")], origin="NEW"),
        )
        old = _goal("OLD", updated_offset_sec=100)
        new = _goal("NEW", updated_offset_sec=0)
        g = _goal("G", depends_on=["OLD", "NEW"])

        proj = _default_projector(store)
        out = await proj.project(g, {"OLD": old, "NEW": new, "G": g})

        # Most-recent parent wins.
        assert len(out.prior_effects) == 1
        assert out.prior_effects[0].statement == "new digest"
        assert out.prior_effects[0].goal_id_origin == "NEW"


class TestFanOut:
    """Three children of the same parent each get an independent bundle."""

    @pytest.mark.asyncio
    async def test_each_child_sees_full_parent_context(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "P",
            _contribution(
                findings=[("p-finding", 1.0)],
                effects=[("mutate", "/shared", "shared edit")],
                origin="P",
            ),
        )
        p = _goal("P")
        children = [_goal(f"C{i}", depends_on=["P"]) for i in range(3)]
        all_goals = {"P": p, **{c.id: c for c in children}}
        proj = _default_projector(store)

        bundles = [await proj.project(c, all_goals) for c in children]

        # All three identical (snapshot of same parent context).
        for b in bundles:
            assert len(b.findings) == 1
            assert b.findings[0].summary == "p-finding"
            assert b.prior_effects[0].ref == "/shared"


class TestSoftDeps:
    @pytest.mark.asyncio
    async def test_informs_parent_contributes_just_like_depends_on(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("HARD", _contribution(findings=[("hard-info", 0.5)], origin="HARD"))
        await store.put("SOFT", _contribution(findings=[("soft-info", 0.5)], origin="SOFT"))
        hard = _goal("HARD")
        soft = _goal("SOFT")
        g = _goal("G", depends_on=["HARD"], informs=["SOFT"])

        proj = _default_projector(store)
        out = await proj.project(g, {"HARD": hard, "SOFT": soft, "G": g})

        summaries = {f.summary for f in out.findings}
        assert summaries == {"hard-info", "soft-info"}


# ---- Bound enforcement -------------------------------------------------


class TestBounds:
    @pytest.mark.asyncio
    async def test_max_findings_truncates_to_top_relevance(self) -> None:
        # Two parents, 10 findings each — projector should keep the top 5
        # by relevance × recency weighting under max_findings=5.
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "P1",
            _contribution(
                findings=[(f"p1-f{i}", i / 10) for i in range(10)],
                origin="P1",
            ),
        )
        await store.put(
            "P2",
            _contribution(
                findings=[(f"p2-f{i}", i / 10) for i in range(10)],
                origin="P2",
            ),
        )
        p1 = _goal("P1", updated_offset_sec=5)
        p2 = _goal("P2", updated_offset_sec=0)  # more recent
        g = _goal("G", depends_on=["P1", "P2"])
        proj = ContextProjector(store, ContextProjectionConfig(max_findings=5))
        out = await proj.project(g, {"P1": p1, "P2": p2, "G": g})

        assert len(out.findings) == 5
        # Top-5 are the highest-relevance findings.
        # Both parents had relevance 0.9, 0.8, 0.7, ... but P2 has the
        # recency multiplier, so its highest-relevance findings win.
        assert all(f.relevance_score >= 0.5 for f in out.findings)
        # The very highest relevance from the most-recent parent must be present.
        most_recent_top = "p2-f9"
        assert any(f.summary == most_recent_top for f in out.findings)

    @pytest.mark.asyncio
    async def test_max_effects_caps_list(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "P",
            _contribution(
                effects=[("decide", f"ref-{i}", f"claim {i}") for i in range(20)],
                origin="P",
            ),
        )
        p = _goal("P")
        g = _goal("G", depends_on=["P"])
        proj = ContextProjector(store, ContextProjectionConfig(max_effects=5))
        out = await proj.project(g, {"P": p, "G": g})

        assert len(out.prior_effects) == 5

    @pytest.mark.asyncio
    async def test_max_plan_steps_caps_list(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "P",
            _contribution(steps=[(f"S{i}", "x") for i in range(15)], origin="P"),
        )
        p = _goal("P")
        g = _goal("G", depends_on=["P"])
        proj = ContextProjector(store, ContextProjectionConfig(max_plan_steps=4))
        out = await proj.project(g, {"P": p, "G": g})

        assert len(out.prior_plan_steps) == 4


# ---- Aggregation -------------------------------------------------------


class TestToolStatsAggregation:
    @pytest.mark.asyncio
    async def test_tool_counts_sum_across_parents(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "A",
            _contribution(tool_counts={"read_file": 3, "edit_file": 1}, origin="A"),
        )
        await store.put(
            "B",
            _contribution(tool_counts={"read_file": 2, "write_file": 5}, origin="B"),
        )
        a = _goal("A")
        b = _goal("B")
        g = _goal("G", depends_on=["A", "B"])

        proj = _default_projector(store)
        out = await proj.project(g, {"A": a, "B": b, "G": g})

        assert out.tool_call_summary.counts_by_name == {
            "read_file": 5,
            "edit_file": 1,
            "write_file": 5,
        }


# ---- Preamble projection (RFC-222 §Goal-Report-Pair) -------------------


def _report(outcome: str = "completed", summary: str = "", findings=None, effects=None):
    r = {"outcome": outcome, "summary": summary or f"done ({outcome})"}
    if findings is not None:
        r["findings"] = findings
    if effects is not None:
        r["effects"] = effects
    return r


class TestPreambleProjection:
    """RFC-222 §Goal-Report-Pair Projection — ancestor (user, ai) pairs."""

    @pytest.mark.asyncio
    async def test_topo_order_three_deep_chain(self) -> None:
        """A → B → C dispatched: pairs appear [A, A-rpt, B, B-rpt], roots-first."""
        store = InMemoryGoalDispatchContextStore()
        await store.put("A", _contribution(findings=[("a-finding", 0.9)], origin="A"))
        await store.put("B", _contribution(findings=[("b-finding", 0.8)], origin="B"))
        a = _goal("A", report=_report(summary="root done"), created_offset_sec=200)
        b = _goal("B", depends_on=["A"], report=_report(summary="mid done"), created_offset_sec=100)
        c = _goal("C", depends_on=["B"])
        proj = _default_projector(store)
        out = await proj.project(c, {"A": a, "B": b, "C": c})
        ids = [m.goal_id_origin for m in out.preamble_messages]
        assert ids == ["A", "A", "B", "B"]

    @pytest.mark.asyncio
    async def test_transitive_grandparent_present(self) -> None:
        """Direct parent (B) has no contribution, but grandparent (A) does."""
        store = InMemoryGoalDispatchContextStore()
        await store.put("A", _contribution(findings=[("a", 0.9)], origin="A"))
        a = _goal("A", report=_report(summary="root done"), created_offset_sec=200)
        b = _goal("B", depends_on=["A"], created_offset_sec=100)
        c = _goal("C", depends_on=["B"])
        proj = _default_projector(store)
        out = await proj.project(c, {"A": a, "B": b, "C": c})
        ids = [m.goal_id_origin for m in out.preamble_messages]
        assert ids == ["A", "A"]
        # flat fields empty since direct parent B has no contribution
        assert out.prior_effects == []

    @pytest.mark.asyncio
    async def test_informs_cycle_guard(self) -> None:
        """informs soft-link cycle (X ↔ Y) does not loop infinitely."""
        store = InMemoryGoalDispatchContextStore()
        await store.put("X", _contribution(findings=[("x", 0.9)], origin="X"))
        await store.put("Y", _contribution(findings=[("y", 0.9)], origin="Y"))
        x = _goal("X", informs=["Y"], report=_report(summary="x done"), created_offset_sec=200)
        y = _goal("Y", informs=["X"], report=_report(summary="y done"), created_offset_sec=100)
        proj = _default_projector(store)
        # X informs Y informs X — cycle; must terminate
        out = await proj.project(x, {"X": x, "Y": y})
        # Both X and Y are ancestors of X via the cycle; both have contributions.
        assert len(out.preamble_messages) >= 2

    @pytest.mark.asyncio
    async def test_cap_enforcement_drops_oldest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cap bit: more ancestors than MAX_PREAMBLE_TURNS//2 → oldest dropped."""
        import soothe.goal_contracts as gc

        # Patch the cap down to 4 messages (2 pairs) to exercise the drop
        # path without needing 7+ ancestors under the real cap of 12.
        monkeypatch.setattr(gc, "MAX_PREAMBLE_TURNS", 4)
        monkeypatch.setattr("soothe_autopilot.dispatch.projector.MAX_PREAMBLE_TURNS", 4)
        store = InMemoryGoalDispatchContextStore()
        await store.put("A", _contribution(findings=[("a", 0.9)], origin="A"))
        await store.put("B", _contribution(findings=[("b", 0.8)], origin="B"))
        await store.put("C", _contribution(findings=[("c", 0.7)], origin="C"))
        a = _goal("A", report=_report(summary="a done"), created_offset_sec=300)
        b = _goal("B", depends_on=["A"], report=_report(summary="b done"), created_offset_sec=200)
        c = _goal("C", depends_on=["B"], report=_report(summary="c done"), created_offset_sec=100)
        d = _goal("D", depends_on=["C"])
        proj = _default_projector(store)
        out = await proj.project(d, {"A": a, "B": b, "C": c, "D": d})
        assert len(out.preamble_messages) == 4
        # Oldest (A) should be dropped; keep most-recent by updated_at.
        ids = {m.goal_id_origin for m in out.preamble_messages}
        assert "A" not in ids

    @pytest.mark.asyncio
    async def test_missing_contribution_skipped(self) -> None:
        """Ancestor with no stored contribution is omitted; descendants still appear."""
        store = InMemoryGoalDispatchContextStore()
        await store.put("A", _contribution(findings=[("a", 0.9)], origin="A"))
        # B has no contribution
        a = _goal("A", report=_report(summary="a done"), created_offset_sec=200)
        b = _goal("B", depends_on=["A"], created_offset_sec=100)
        c = _goal("C", depends_on=["B"])
        proj = _default_projector(store)
        out = await proj.project(c, {"A": a, "B": b, "C": c})
        ids = [m.goal_id_origin for m in out.preamble_messages]
        assert ids == ["A", "A"]

    @pytest.mark.asyncio
    async def test_ai_turn_reads_committed_report(self) -> None:
        """AI half mirrors GoalNode.report (outcome + summary), not the contribution."""
        store = InMemoryGoalDispatchContextStore()
        await store.put("A", _contribution(findings=[("contribution-finding", 0.9)], origin="A"))
        a = _goal(
            "A",
            report=_report(
                outcome="needs_replan",
                summary="report-level summary",
                findings=["report-finding"],
                effects=[{"kind": "produce", "ref": "f.py", "statement": "made f"}],
            ),
            created_offset_sec=100,
        )
        b = _goal("B", depends_on=["A"])
        proj = _default_projector(store)
        out = await proj.project(b, {"A": a, "B": b})
        ai_turn = out.preamble_messages[1]
        from soothe.goal_contracts import GoalReportAITurn

        assert isinstance(ai_turn, GoalReportAITurn)
        assert ai_turn.outcome == "needs_replan"
        assert ai_turn.summary == "report-level summary"
        assert ai_turn.findings == ["report-finding"]

    @pytest.mark.asyncio
    async def test_recency_tiebreak_within_topo_level(self) -> None:
        """Two root parents (A, B) of G: equal topo level, ordered by created_at asc."""
        store = InMemoryGoalDispatchContextStore()
        await store.put("A", _contribution(findings=[("a", 0.9)], origin="A"))
        await store.put("B", _contribution(findings=[("b", 0.8)], origin="B"))
        a = _goal("A", report=_report(summary="a done"), created_offset_sec=200)
        b = _goal("B", report=_report(summary="b done"), created_offset_sec=100)
        g = _goal("G", depends_on=["A", "B"])
        proj = _default_projector(store)
        out = await proj.project(g, {"A": a, "B": b, "G": g})
        ids = [m.goal_id_origin for m in out.preamble_messages]
        # A is older (200s ago) → appears before B (100s ago)
        assert ids == ["A", "A", "B", "B"]


# ---- Contract bounds (preamble_messages) --------------------------------


class TestPreambleContractBounds:
    def test_over_cap_raises(self) -> None:
        from soothe.goal_contracts import (
            GoalDispatchContextBundle,
            GoalReportUserTurn,
        )

        u = GoalReportUserTurn(goal_id_origin="g", content="x")
        with pytest.raises(ValueError, match="preamble_messages"):
            GoalDispatchContextBundle(preamble_messages=[u] * 100)

    def test_serialization_round_trip(self) -> None:
        from soothe.goal_contracts import (
            GoalDispatchContextBundle,
            GoalReportAITurn,
            GoalReportUserTurn,
        )

        u = GoalReportUserTurn(goal_id_origin="A", content="do A")
        a = GoalReportAITurn(goal_id_origin="A", outcome="completed", summary="A done")
        b = GoalDispatchContextBundle(preamble_messages=[u, a])
        d = b.model_dump(mode="json")
        b2 = GoalDispatchContextBundle.model_validate(d)
        assert len(b2.preamble_messages) == 2
        assert isinstance(b2.preamble_messages[0], GoalReportUserTurn)
        assert isinstance(b2.preamble_messages[1], GoalReportAITurn)
