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
        assert "quiz" in system
        assert "trivial" in system
        assert "{query}" not in system
        assert "<TIMESTAMP>" in system
        assert "TestBot" in system

    def test_human_message_uses_goal_and_task_sections(self) -> None:
        human = build_intake_human_message(
            query="count all folder in project root and show me 2 recommended actions",
        )
        assert human.startswith("GOAL:\n")
        assert "\n\nTASK:\n" in human
        assert "count all folder in project root" in human
        assert "I'll or Let me" in human
        assert "<current_query>" not in human
        assert "<intent_inputs>" not in human
        assert "intake_label" not in human.split("TASK:")[0]

    def test_retry_human_message_uses_retry_task(self) -> None:
        human = build_intake_human_message(query="summarize readme", retry=True)
        assert "Re-classify GOAL above" in human

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
            intent_type="agentic",
            intake_label=IntakeLabel.SIMPLE,
            goal_description="summarize readme",
            task_complexity=TaskComplexity.SIMPLE,
            reasoning="I'll read the readme.",
        )
        llm_dict = {
            "intake_label": "simple",
            "reasoning": "I'll read the readme.",
            "goal_description": "summarize readme",
            "quiz_response": None,
        }
        ce = MagicMock()
        ce.save = AsyncMock()
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_result, "human body", llm_dict)
            await classifier.classify_intake(
                "summarize readme",
                thread_id="thread-1",
                context_engine=ce,
            )
        assert ce.ledger.record_message.call_count == 2
        ce.save.assert_awaited_once()
        ai_call = ce.ledger.record_message.call_args_list[1]
        ai_msg = ai_call[0][0]
        parsed = json.loads(ai_msg.content)
        assert parsed["intake_label"] == "simple"

    async def test_skips_ledger_when_no_context_engine(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = IntentClassification(
            intent_type="agentic",
            intake_label=IntakeLabel.COMPLEX,
            goal_description="refactor",
            task_complexity=TaskComplexity.COMPLEX,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_result, "human", {"intake_label": "complex"})
            await classifier.classify_intake("refactor", context_engine=None)


class TestIntakeLangfuseInvokeConfig:
    """Intent-classify nests under goal loop trace when bootstrap is provided (IG-540)."""

    def test_build_invoke_config_uses_bootstrap_not_independent_trace(self) -> None:
        from soothe.config import SootheConfig

        cfg = SootheConfig()
        cfg.observability.langfuse.enabled = True
        classifier = IntentClassifier(model=MagicMock(), soothe_config=cfg)
        bootstrap = {"metadata": {"loop_id": "loop-1"}, "callbacks": [MagicMock()]}

        with patch(
            "soothe.utils.observability.langfuse.build_intake_langfuse_invoke_config",
            return_value={"metadata": {"purpose": "classify_intake"}},
        ) as mock_build:
            out = classifier._build_invoke_config(
                "classify_intake",
                "intake.primary",
                langfuse_bootstrap=bootstrap,
            )

        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs["langfuse_bootstrap"] is bootstrap
        assert out["metadata"]["purpose"] == "classify_intake"


@pytest.mark.asyncio
class TestLoadIntakeContext:
    """Ledger loading for pre-stream classification."""

    async def test_returns_empty_on_failure(self) -> None:
        from soothe.foundation.sloop.intention.intake_context import load_intake_context

        config = MagicMock()
        with patch(
            "soothe.foundation.context.engine.ContextEngine",
            side_effect=RuntimeError("boom"),
        ):
            ctx = await load_intake_context(config, "loop-1")
        assert ctx.loop_messages == []
        assert ctx.context_engine is None


class TestIntakePriorGoalProjection:
    """Prior goal completion projection for intake classify."""

    def test_prefers_goal_completion_pair(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_prior_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="step", phase="execute_step"),
            LoopAIMessage(content="step output", phase="execute_step"),
            LoopHumanMessage(content="finalize", phase="goal_completion"),
            LoopAIMessage(content="synthesized report", phase="goal_completion"),
        ]
        projected = project_prior_goal_completion_for_intake(ledger, None)
        assert len(projected) == 2
        assert projected[-1].content == "synthesized report"

    def test_falls_back_to_last_execute_step_for_ledger_direct(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_prior_goal_completion_for_intake,
        )

        ledger = [
            LoopHumanMessage(content="step-1", phase="execute_step"),
            LoopAIMessage(content="first", phase="execute_step"),
            LoopHumanMessage(content="step-2", phase="execute_step"),
            LoopAIMessage(content="final answer", phase="execute_step"),
        ]
        projected = project_prior_goal_completion_for_intake(ledger, None)
        assert len(projected) == 2
        assert projected[0].content == "step-2"
        assert projected[1].content == "final answer"

    def test_empty_ledger_projects_nothing(self) -> None:
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_prior_goal_completion_for_intake,
        )

        assert project_prior_goal_completion_for_intake([], None) == []
