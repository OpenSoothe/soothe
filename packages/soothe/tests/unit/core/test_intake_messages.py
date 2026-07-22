"""Unit tests for intake ledger recording and prior projection (IG-540, IG-554)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.sloop.intention import IntentClassifier
from soothe.sloop.intention.models import (
    IntakePass1Confidence,
    IntakePass1LLMResult,
    IntakePass2LLMResult,
    IntakeScope,
)
from soothe.sloop.intention.two_pass_coordinator import TwoPassIntakeResult
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


@pytest.mark.asyncio
class TestIntakeClassifierLedger:
    """Intent-classify ledger recording."""

    async def test_records_ledger_pair_when_context_engine_provided(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        pass2 = IntakePass2LLMResult(
            scope=IntakeScope.SIMPLE,
            reasoning="I'll read the readme.",
        )
        mock_result = TwoPassIntakeResult(
            IntakePass1LLMResult(
                is_task=True,
                confidence=IntakePass1Confidence.HIGH,
                social_response=None,
                reasoning="task",
            ),
            pass2,
        )
        ce = MagicMock()
        ce.save = AsyncMock()
        with patch.object(
            classifier._two_pass, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            await classifier.classify_intake(
                "summarize readme",
                thread_id="thread-1",
                context_engine=ce,
            )
        assert ce.ledger.record_message.call_count == 2
        ce.save.assert_awaited_once()
        human_call = ce.ledger.record_message.call_args_list[0]
        human_msg = human_call[0][0]
        assert human_msg.phase == "intent_classify"
        assert "summarize readme" in human_msg.content
        ai_call = ce.ledger.record_message.call_args_list[1]
        ai_msg = ai_call[0][0]
        parsed = json.loads(ai_msg.content)
        assert parsed["scope"] == "simple"

    async def test_skips_ledger_when_no_context_engine(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = TwoPassIntakeResult(
            IntakePass1LLMResult(
                is_task=True,
                confidence=IntakePass1Confidence.HIGH,
                social_response=None,
                reasoning="task",
            ),
            IntakePass2LLMResult(
                scope=IntakeScope.COMPLEX,
                reasoning="complex",
            ),
        )
        with patch.object(
            classifier._two_pass, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            await classifier.classify_intake("refactor", context_engine=None)


class TestIntakePriorGoalProjection:
    """Prior goal completion projection for intake classify."""

    def test_projects_last_goal_completion_pair(self) -> None:
        from soothe.prompts.plan_ledger_projection import (
            _GOAL_COMPLETION_CONTEXT_BOUNDARY,
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="step", phase="execute_step"),
            LoopAIMessage(content="step output", phase="execute_step"),
            LoopHumanMessage(content="finalize", phase="goal_completion"),
            LoopAIMessage(content="synthesized report", phase="goal_completion"),
        ]
        # IG-555: Default includes boundary marker for planning projections
        projected = project_last_goal_completion_for_intake(ledger, None)
        assert len(projected) == 2
        assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() in projected[0].content
        assert "Prior goal completed" in projected[0].content
        assert projected[-1].content == "synthesized report"

    def test_intake_pass2_omits_boundary_marker(self) -> None:
        """IG-555: Intake Pass 2 projection omits boundary (classifier needs prior scope)."""
        from soothe.prompts.plan_ledger_projection import (
            _GOAL_COMPLETION_CONTEXT_BOUNDARY,
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="step", phase="execute_step"),
            LoopAIMessage(content="step output", phase="execute_step"),
            LoopHumanMessage(content="finalize", phase="goal_completion"),
            LoopAIMessage(content="synthesized report", phase="goal_completion"),
        ]
        # Intake Pass 2 uses include_boundary=False for classifier scope signal
        projected = project_last_goal_completion_for_intake(ledger, None, include_boundary=False)
        assert len(projected) == 2
        assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() not in projected[0].content
        assert projected[0].content == "Prior goal completed. Terminal report follows."
        assert projected[-1].content == "synthesized report"

    def test_prefers_latest_goal_completion_before_trailing_plan_rows(self) -> None:
        from soothe.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="old", phase="goal_completion"),
            LoopAIMessage(content="older report", phase="goal_completion"),
            LoopHumanMessage(content="new", phase="goal_completion"),
            LoopAIMessage(content="latest report", phase="goal_completion"),
            LoopHumanMessage(content="plan", phase="plan_assess", iteration=0),
            LoopAIMessage(content='{"status":"continue"}', phase="plan_assess", iteration=0),
        ]
        projected = project_last_goal_completion_for_intake(ledger, None)
        assert len(projected) == 2
        assert projected[-1].content == "latest report"

    def test_returns_empty_when_no_goal_completion_unit(self) -> None:
        from soothe.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="step-1", phase="execute_step"),
            LoopAIMessage(content="first", phase="execute_step"),
            LoopHumanMessage(content="step-2", phase="execute_step"),
            LoopAIMessage(content="final answer", phase="execute_step"),
        ]
        projected = project_last_goal_completion_for_intake(ledger, None)
        assert projected == []

    def test_goal_completion_unit_projects_for_intake(self) -> None:
        from soothe.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="what time is it?", phase="goal_completion"),
            LoopAIMessage(content="It is 3 PM.", phase="goal_completion"),
        ]
        projected = project_last_goal_completion_for_intake(ledger, None)
        assert len(projected) == 2
        assert projected[-1].content == "It is 3 PM."

    def test_no_legacy_phase_fallback_when_no_goal_completion(self) -> None:
        from soothe.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="what time is it?", phase="execute_step"),
            LoopAIMessage(content="It is 3 PM.", phase="execute_step"),
        ]
        projected = project_last_goal_completion_for_intake(ledger, None)
        assert projected == []

    def test_empty_ledger_projects_nothing(self) -> None:
        from soothe.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        assert project_last_goal_completion_for_intake([], None) == []


class TestIntentClassifyLedgerProjection:
    """Intent-classify humans use GOAL RECAP in plan ledger projection (D1)."""

    def test_project_loop_messages_rewrites_intent_classify_goal(self) -> None:
        from soothe.prompts.plan_ledger_projection import (
            project_loop_messages_for_plan,
        )

        ledger = [
            LoopHumanMessage(
                content="GOAL:\nsummarize readme\n\nTASK:\nClassify intake.",
                phase="intent_classify",
                thread_id="t",
            ),
            LoopAIMessage(
                content='{"scope":"simple"}',
                phase="intent_classify",
                thread_id="t",
            ),
        ]
        projected = project_loop_messages_for_plan(ledger, None)
        assert projected[0].content.startswith("GOAL RECAP:\n")
        assert "GOAL:\n" not in projected[0].content.split("TASK:")[0]
        assert projected[1] is ledger[1]

    def test_project_planner_ledger_new_goal_includes_compacted_intent_classify(self) -> None:
        from soothe.prompts.plan_ledger_projection import (
            project_planner_ledger,
        )

        ledger = [
            LoopHumanMessage(
                content="GOAL:\nchild goal\n\nTASK:\nClassify intake.",
                phase="intent_classify",
                thread_id="t",
            ),
            LoopAIMessage(content='{"scope":"complex"}', phase="intent_classify", thread_id="t"),
            LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
            LoopAIMessage(content="exec a", phase="execute_step", thread_id="t"),
        ]
        projected = project_planner_ledger(ledger, "new_goal", None)
        assert len(projected) == 2
        assert projected[0].content.startswith("GOAL RECAP:\n")
