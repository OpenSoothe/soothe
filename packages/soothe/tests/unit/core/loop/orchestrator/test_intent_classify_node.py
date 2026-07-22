"""Tests for graph entry ``intent_classify`` node."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.intention.models import TaskComplexity

from soothe.sloop.intention import IntentClassification
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.nodes.intent_classify import node_intent_classify


@pytest.mark.asyncio
async def test_intent_classify_emits_interpreting_status_and_sets_state() -> None:
    """Two-pass classify_intake populates loop state when not pre-classified."""
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    classifier = MagicMock()
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="I'll plan a lightweight change.",
        task_complexity=TaskComplexity.SIMPLE,
    )
    classifier.classify_intake = AsyncMock(return_value=intent)

    loop_state = SimpleNamespace(
        goal="Fix the typo",
        goal_user_submission="Fix the typo",
        thread_id="t1",
        intent=None,
        routing_classification=None,
        total_tokens_used=0,
    )
    ce = MagicMock()
    ce.get_ledger_entries.return_value = []

    ctx = SimpleNamespace(
        loop_state=loop_state,
        intent_classifier=classifier,
        preferred_subagent=None,
        clarification_resume_text=None,
        clarification_resume_answers=None,
        ce=ce,
        goal_trace=None,
        state_manager=SimpleNamespace(loop_id="L1"),
        emit=_emit,
    )

    await node_intent_classify(ctx, {})

    classifier.classify_intake.assert_awaited_once()
    assert loop_state.intent is intent
    assert loop_state.routing_classification is not None
    assert any(
        t == "plan_phase_status"
        and isinstance(d, dict)
        and d.get("label") == "Interpreting goal"
        and d.get("total_tokens_used") == 0
        for t, d in emitted
    )
    assert any(t == "intent_classified_reasoning" for t, _ in emitted)


@pytest.mark.asyncio
async def test_intent_classify_skips_when_preclassified() -> None:
    """Pre-classified intent from pre-graph gather skips LLM."""
    classifier = MagicMock()
    classifier.classify_intake = AsyncMock()
    existing = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        task_complexity=TaskComplexity.COMPLEX,
    )
    loop_state = SimpleNamespace(
        goal="refactor",
        goal_user_submission="refactor",
        thread_id="t1",
        intent=existing,
        routing_classification=None,
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        intent_classifier=classifier,
        preferred_subagent=None,
        clarification_resume_text=None,
        clarification_resume_answers=None,
        ce=None,
        goal_trace=None,
        state_manager=SimpleNamespace(loop_id="L1"),
        emit=AsyncMock(),
    )

    await node_intent_classify(ctx, {})

    classifier.classify_intake.assert_not_called()
    assert loop_state.routing_classification is not None


@pytest.mark.asyncio
async def test_intent_classify_skips_on_clarification_resume() -> None:
    classifier = MagicMock()
    classifier.classify_intake = AsyncMock()

    loop_state = SimpleNamespace(
        goal="soothe",
        goal_user_submission="soothe",
        thread_id="t1",
        intent=None,
        routing_classification=None,
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        intent_classifier=classifier,
        preferred_subagent=None,
        clarification_resume_text="soothe",
        clarification_resume_answers=None,
        ce=None,
        goal_trace=None,
        state_manager=SimpleNamespace(loop_id="L1"),
        emit=AsyncMock(),
    )

    await node_intent_classify(ctx, {})

    classifier.classify_intake.assert_not_called()
