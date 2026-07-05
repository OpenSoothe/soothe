"""Unit tests for intake message builders and ledger context (IG-540)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.intention import IntentClassification, IntentClassifier, TaskComplexity
from soothe.foundation.sloop.intention.intake_messages import (
    build_intake_human_message,
    build_intake_system_message,
)
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.intention.prompts import (
    INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT,
    INTAKE_CLASSIFICATION_SYSTEM_PROMPT,
)
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


class TestIntakeMessageBuilders:
    """System/human split for intake classification."""

    def test_system_message_has_static_rules_and_timestamp(self) -> None:
        system = build_intake_system_message("TestBot", retry=False)
        assert "trivial" in system
        assert "quiz" not in system
        assert "{query}" not in system
        assert "match GOAL language" in system
        assert "RESPONSE_LANGUAGE_HINT" not in system
        assert "<TIMESTAMP>" in system
        assert "TestBot" in system

    def test_human_message_uses_goal_and_task_sections(self) -> None:
        human = build_intake_human_message(
            query="count all folder in project root and show me 2 recommended actions",
        )
        assert human.startswith("GOAL:\n")
        assert "\n\nTASK:\n" in human
        assert "count all folder in project root" in human
        assert human.endswith("Classify GOAL above. JSON only.")
        assert "I'll or Let me" not in human
        assert "match GOAL language" not in human
        assert "<current_query>" not in human
        assert "<intent_inputs>" not in human
        assert "intake_label" not in human.split("TASK:")[0]
        assert "RESPONSE_LANGUAGE_HINT" not in human

    def test_retry_human_message_uses_retry_task(self) -> None:
        human = build_intake_human_message(query="summarize readme", retry=True)
        assert human.endswith("Re-classify GOAL above. JSON only.")

    def test_retry_system_is_shorter_than_primary(self) -> None:
        assert len(INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT) < len(
            INTAKE_CLASSIFICATION_SYSTEM_PROMPT
        )


@pytest.mark.asyncio
class TestIntakeClassifierLedger:
    """Intent-classify ledger recording."""

    async def test_records_ledger_pair_when_context_engine_provided(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = IntentClassification(
            intake_label=IntakeLabel.SIMPLE,
            goal_description="summarize readme",
            task_complexity=TaskComplexity.SIMPLE,
            reasoning="I'll read the readme.",
        )
        llm_dict = {
            "intake_label": "simple",
            "reasoning": "I'll read the readme.",
            "goal_description": "summarize readme",
        }
        ce = MagicMock()
        ce.save = AsyncMock()
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            recorded_human = build_intake_human_message(query="summarize readme")
            mock_llm.return_value = (mock_result, recorded_human, llm_dict)
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
        assert human_msg.content.startswith("GOAL RECAP:\n")
        assert "summarize readme" in human_msg.content
        ai_call = ce.ledger.record_message.call_args_list[1]
        ai_msg = ai_call[0][0]
        parsed = json.loads(ai_msg.content)
        assert parsed["intake_label"] == "simple"

    async def test_skips_ledger_when_no_context_engine(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            goal_description="refactor",
            task_complexity=TaskComplexity.COMPLEX,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_result, "human", {"intake_label": "complex"})
            await classifier.classify_intake("refactor", context_engine=None)


class TestIntakeLangfuseInvokeConfig:
    """Intent-classify nests under goal loop trace when goal_trace is provided (IG-540)."""

    def test_build_invoke_config_uses_goal_trace(self) -> None:
        from soothe.config import SootheConfig

        cfg = SootheConfig()
        cfg.observability.langfuse.enabled = True
        classifier = IntentClassifier(model=MagicMock(), soothe_config=cfg)
        goal_trace = MagicMock()
        goal_trace.intake_invoke_config.return_value = {"metadata": {"purpose": "classify_intake"}}

        out = classifier._build_invoke_config(
            "classify_intake",
            "intake.primary",
            goal_trace=goal_trace,
        )

        goal_trace.intake_invoke_config.assert_called_once()
        assert out["metadata"]["purpose"] == "classify_intake"


class TestIntakePriorGoalProjection:
    """Prior goal completion projection for intake classify."""

    def test_projects_last_goal_completion_pair(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="step", phase="execute_step"),
            LoopAIMessage(content="step output", phase="execute_step"),
            LoopHumanMessage(content="finalize", phase="goal_completion"),
            LoopAIMessage(content="synthesized report", phase="goal_completion"),
        ]
        projected = project_last_goal_completion_for_intake(ledger, None)
        assert len(projected) == 2
        assert projected[0].content == "Prior goal completed. Terminal report follows."
        assert projected[-1].content == "synthesized report"

    def test_prefers_latest_goal_completion_before_trailing_plan_rows(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
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
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
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

    def test_falls_back_to_trivial_pair_when_no_goal_completion(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="what time is it?", phase="trivial"),
            LoopAIMessage(content="It is 3 PM.", phase="trivial"),
        ]
        projected = project_last_goal_completion_for_intake(ledger, None)
        assert len(projected) == 2
        assert projected[-1].content == "It is 3 PM."

    def test_falls_back_to_legacy_quiz_pair_when_no_goal_completion(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="what is python?", phase="quiz"),
            LoopAIMessage(content="A programming language.", phase="quiz"),
        ]
        projected = project_last_goal_completion_for_intake(ledger, None)
        assert len(projected) == 2
        assert projected[-1].content == "A programming language."

    def test_empty_ledger_projects_nothing(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_last_goal_completion_for_intake,
        )

        assert project_last_goal_completion_for_intake([], None) == []


class TestIntentClassifyLedgerProjection:
    """Intent-classify humans use GOAL RECAP in plan ledger projection (D1)."""

    def test_project_loop_messages_rewrites_intent_classify_goal(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_loop_messages_for_plan,
        )

        ledger = [
            LoopHumanMessage(
                content="GOAL:\nsummarize readme\n\nTASK:\nClassify intake.",
                phase="intent_classify",
                thread_id="t",
            ),
            LoopAIMessage(
                content='{"intake_label":"simple"}',
                phase="intent_classify",
                thread_id="t",
            ),
        ]
        projected = project_loop_messages_for_plan(ledger, None)
        assert projected[0].content.startswith("GOAL RECAP:\n")
        assert "GOAL:\n" not in projected[0].content.split("TASK:")[0]
        assert projected[1] is ledger[1]

    def test_project_planner_ledger_new_goal_includes_compacted_intent_classify(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_planner_ledger,
        )

        ledger = [
            LoopHumanMessage(
                content="GOAL:\nchild goal\n\nTASK:\nClassify intake.",
                phase="intent_classify",
                thread_id="t",
            ),
            LoopAIMessage(
                content='{"intake_label":"complex"}', phase="intent_classify", thread_id="t"
            ),
            LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
            LoopAIMessage(content="exec a", phase="execute_step", thread_id="t"),
        ]
        projected = project_planner_ledger(ledger, "new_goal", None)
        assert len(projected) == 2
        assert projected[0].content.startswith("GOAL RECAP:\n")
