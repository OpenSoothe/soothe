"""Tests for backoff reasoner using ContextProjector (RFC-222 §Goal-Report-Pair).

The backoff LLM sees the ancestor (user, ai) transcript — with outcome, summary,
findings, and effects — via the same projection path the executing worker uses.
The projector is a required dependency; no legacy fallback path exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe.config.models import ContextProjectionConfig
from soothe.context.models import GoalNode
from soothe.goal_contracts import (
    EvidenceBundle,
    Finding,
    GoalDispatchContextContribution,
)

from soothe_autopilot.dispatch.projector import ContextProjector
from soothe_autopilot.dispatch.store import InMemoryGoalDispatchContextStore
from soothe_autopilot.verify.backoff_reasoner import GoalBackoffReasoner


def _goal(
    gid: str,
    *,
    depends_on: list[str] | None = None,
    report: dict | None = None,
    created_offset: float = 0.0,
) -> GoalNode:
    g = GoalNode(id=gid, description=f"goal {gid}", depends_on=depends_on or [])
    g.created_at = datetime.now(UTC) - timedelta(seconds=created_offset)
    if report is not None:
        g.report = report
    return g


def _evidence() -> EvidenceBundle:
    return EvidenceBundle(
        structured={"error": "timeout"},
        narrative="Goal timed out during execution",
        source="layer2_execute",
    )


def _make_reasoner(model: Any = None) -> GoalBackoffReasoner:
    """Build a reasoner with a mock config + model (no real LLM)."""
    cfg = MagicMock()
    cfg.create_chat_model.return_value = model or MagicMock()
    cfg.agent.autopilot.monitor_model_role = "think"
    return GoalBackoffReasoner(cfg)


class TestBuildPreambleText:
    @pytest.mark.asyncio
    async def test_renders_ancestor_transcript(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "A",
            GoalDispatchContextContribution(
                findings=[Finding(summary="A finding", relevance_score=0.9)]
            ),
        )
        await store.put(
            "B",
            GoalDispatchContextContribution(
                findings=[Finding(summary="B finding", relevance_score=0.8)]
            ),
        )
        a = _goal(
            "A",
            report={
                "outcome": "completed",
                "summary": "root done",
                "findings": ["rf"],
                "effects": [],
            },
            created_offset=200,
        )
        b = _goal(
            "B",
            depends_on=["A"],
            report={"outcome": "completed", "summary": "mid done"},
            created_offset=100,
        )
        c = _goal("C", depends_on=["B"])
        proj = ContextProjector(store, ContextProjectionConfig())
        text = await proj.build_preamble_text(c, {"A": a, "B": b, "C": c})
        assert "[user / goal A]:" in text
        assert "root done" in text
        assert "[ai / goal A]" in text
        assert "[user / goal B]:" in text
        assert "mid done" in text

    @pytest.mark.asyncio
    async def test_empty_when_no_ancestors(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        a = _goal("A", report={"outcome": "completed", "summary": "done"})
        proj = ContextProjector(store, ContextProjectionConfig())
        text = await proj.build_preamble_text(a, {"A": a})
        assert text == ""


class TestReasonBackoffProjection:
    @pytest.mark.asyncio
    async def test_prompt_contains_ancestor_transcript(self) -> None:
        """The prompt sent to the LLM must contain ancestor report summaries."""
        store = InMemoryGoalDispatchContextStore()
        await store.put(
            "A",
            GoalDispatchContextContribution(
                findings=[Finding(summary="A finding", relevance_score=0.9)]
            ),
        )
        await store.put(
            "B",
            GoalDispatchContextContribution(
                findings=[Finding(summary="B finding", relevance_score=0.8)]
            ),
        )
        a = _goal(
            "A",
            report={"outcome": "completed", "summary": "root done", "findings": ["root-finding"]},
            created_offset=200,
        )
        b = _goal(
            "B",
            depends_on=["A"],
            report={"outcome": "completed", "summary": "mid done"},
            created_offset=100,
        )
        c = _goal("C", depends_on=["B"])
        proj = ContextProjector(store, ContextProjectionConfig())

        mock_response = MagicMock()
        mock_response.content = (
            '```json\n{"backoff_to_goal_id": "C", "reason": "retry", '
            '"new_directives": [], "evidence_summary": "timeout"}\n```'
        )
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)

        reasoner = _make_reasoner(model=mock_model)
        await reasoner.reason_backoff(
            "C",
            {"A": a, "B": b, "C": c},
            _evidence(),
            projector=proj,
        )

        sent_prompt = mock_model.ainvoke.call_args[0][0][-1].content
        assert "root done" in sent_prompt
        assert "mid done" in sent_prompt
        assert "[ai / goal A]" in sent_prompt
        assert "[user / goal A]" in sent_prompt

    @pytest.mark.asyncio
    async def test_empty_chain_when_no_ancestors(self) -> None:
        """A goal with no ancestors → empty dependency chain, still runs."""
        store = InMemoryGoalDispatchContextStore()
        a = _goal("A", report={"outcome": "completed", "summary": "done"})

        mock_response = MagicMock()
        mock_response.content = (
            '```json\n{"backoff_to_goal_id": "A", "reason": "retry", '
            '"new_directives": [], "evidence_summary": "fail"}\n```'
        )
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)

        reasoner = _make_reasoner(model=mock_model)
        proj = ContextProjector(store, ContextProjectionConfig())
        await reasoner.reason_backoff("A", {"A": a}, _evidence(), projector=proj)

        # Prompt still built and sent; dependency chain section is empty.
        assert mock_model.ainvoke.call_count == 1


class TestMonitorBindsProjector:
    def test_bind_context_projector_stores_ref(self) -> None:
        from soothe_autopilot.monitor.monitor import AutopilotMonitor

        cfg = MagicMock()
        cfg.agent.autopilot.monitor_model_role = "think"
        cfg.create_chat_model.return_value = MagicMock()
        ce = MagicMock()
        bus = MagicMock()
        monitor = AutopilotMonitor(ce, bus, cfg)
        assert monitor._context_projector is None

        fake_proj = MagicMock()
        monitor.bind_context_projector(fake_proj)
        assert monitor._context_projector is fake_proj

    @pytest.mark.asyncio
    async def test_skips_backoff_when_no_projector_bound(self) -> None:
        """No projector bound → monitor logs and skips, does not call the reasoner."""
        from soothe_autopilot.monitor.monitor import AutopilotMonitor

        cfg = MagicMock()
        cfg.agent.autopilot.monitor_model_role = "think"
        cfg.create_chat_model.return_value = MagicMock()
        ce = MagicMock()
        ce.get_goals_by_status.return_value = []
        bus = MagicMock()
        monitor = AutopilotMonitor(ce, bus, cfg)
        # Replace the real reasoner with a mock so we can assert it's untouched.
        monitor._backoff_reasoner = MagicMock()

        event = MagicMock()
        event.goal_id = "g1"
        event.evidence = EvidenceBundle(
            structured={},
            narrative="failed",
            source="layer2_execute",
        )
        await monitor._on_goal_failed(event)

        # reason_backoff was never called (projector is None).
        monitor._backoff_reasoner.reason_backoff.assert_not_called()
