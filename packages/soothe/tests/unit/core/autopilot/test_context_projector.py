"""Tests for ContextProjector (RFC-222 revised).

Covers linear chain, diamond join, fan-out, soft (informs) parents,
recency-ordering, bound enforcement, and graceful handling of missing
parents.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from soothe.config.models import ContextProjectionConfig
from soothe.core.autopilot.context_projector import ContextProjector
from soothe.core.autopilot.context_store import InMemoryGoalDispatchContextStore
from soothe.core.goal_engine.models import (
    FileTouchSummary,
    Finding,
    Goal,
    GoalDispatchContextContribution,
    StepSummary,
    ToolCallStats,
)

# ---- Fixtures -----------------------------------------------------------


def _goal(
    gid: str,
    *,
    depends_on: list[str] | None = None,
    informs: list[str] | None = None,
    updated_offset_sec: float = 0.0,
) -> Goal:
    g = Goal(
        id=gid,
        description=f"goal {gid}",
        depends_on=depends_on or [],
        informs=informs or [],
    )
    g.updated_at = datetime.now(UTC) - timedelta(seconds=updated_offset_sec)
    return g


def _contribution(
    *,
    files: dict[str, str] | None = None,  # path → hash
    findings: list[tuple[str, float]] | None = None,  # (summary, relevance)
    steps: list[tuple[str, str]] | None = None,  # (id, action)
    tool_counts: dict[str, int] | None = None,
    origin: str = "?",
) -> GoalDispatchContextContribution:
    return GoalDispatchContextContribution(
        plan_steps_executed=[
            StepSummary(id=sid, action=action, outcome="completed") for sid, action in (steps or [])
        ],
        files_touched={
            path: FileTouchSummary(content_hash=h, last_op="edit", goal_id_origin=origin)
            for path, h in (files or {}).items()
        },
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
        assert out.files_touched == {}
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
        assert out.files_touched == {}


# ---- DAG shapes --------------------------------------------------------


class TestLinearChain:
    @pytest.mark.asyncio
    async def test_a_to_b_merges_a_into_bundle(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "A",
            _contribution(
                findings=[("a-finding", 0.9)],
                files={"/x": "h1"},
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
        assert out.files_touched["/x"].content_hash == "h1"
        assert out.prior_plan_steps[0].id == "S1"
        assert out.prior_plan_steps[0].goal_id_origin == "A"


class TestDiamondJoin:
    @pytest.mark.asyncio
    async def test_diamond_unions_both_parents(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "A",
            _contribution(findings=[("from-A", 0.5)], files={"/a": "h-a"}, origin="A"),
        )
        await store.put(
            "B",
            _contribution(findings=[("from-B", 0.5)], files={"/b": "h-b"}, origin="B"),
        )
        a = _goal("A", updated_offset_sec=10)
        b = _goal("B", updated_offset_sec=0)  # more recent
        g = _goal("G", depends_on=["A", "B"])

        proj = _default_projector(store)
        out = await proj.project(g, {"A": a, "B": b, "G": g})

        # Both parents contribute findings.
        summaries = {f.summary for f in out.findings}
        assert summaries == {"from-A", "from-B"}

        # Both files appear (different paths, no conflict).
        assert "/a" in out.files_touched
        assert "/b" in out.files_touched

    @pytest.mark.asyncio
    async def test_diamond_with_same_file_recency_wins(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("OLD", _contribution(files={"/x": "old-h"}, origin="OLD"))
        await store.put("NEW", _contribution(files={"/x": "new-h"}, origin="NEW"))
        old = _goal("OLD", updated_offset_sec=100)
        new = _goal("NEW", updated_offset_sec=0)
        g = _goal("G", depends_on=["OLD", "NEW"])

        proj = _default_projector(store)
        out = await proj.project(g, {"OLD": old, "NEW": new, "G": g})

        # Most-recent parent wins.
        assert out.files_touched["/x"].content_hash == "new-h"


class TestFanOut:
    """Three children of the same parent each get an independent bundle."""

    @pytest.mark.asyncio
    async def test_each_child_sees_full_parent_context(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "P",
            _contribution(
                findings=[("p-finding", 1.0)],
                files={"/shared": "p-h"},
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
            assert b.files_touched["/shared"].content_hash == "p-h"


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
    async def test_max_files_caps_dict(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "P",
            _contribution(files={f"/p{i}": f"h{i}" for i in range(20)}, origin="P"),
        )
        p = _goal("P")
        g = _goal("G", depends_on=["P"])
        proj = ContextProjector(store, ContextProjectionConfig(max_files=5))
        out = await proj.project(g, {"P": p, "G": g})

        assert len(out.files_touched) == 5

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
