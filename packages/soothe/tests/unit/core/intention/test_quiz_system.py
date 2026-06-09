"""Tests for quiz-path system message builder."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.foundation.core.quiz_messages import build_quiz_system_message


def test_build_quiz_system_message_includes_assistant_name() -> None:
    text = build_quiz_system_message("Soothe")
    assert "You are Soothe" in text
    assert "Do not claim to be Claude" in text


def test_build_quiz_system_message_includes_quiz_guide() -> None:
    text = build_quiz_system_message("TestBot")
    assert "Quiz/factual questions" in text


@pytest.mark.asyncio
class TestIntentClassifierQuizMessages:
    """Intent classifier passes identity system message to the LLM."""

    @staticmethod
    def _messages_from_invoke_call(call_args: object) -> list:
        args, kwargs = call_args  # type: ignore[misc]
        if args:
            payload = args[1] if len(args) > 1 else args[0]
        else:
            payload = kwargs.get("messages")
        if isinstance(payload, list):
            return payload
        return [payload]

    async def test_classify_intent_llm_uses_system_message(self) -> None:
        from soothe.foundation.loop.intention import IntentClassifier
        from soothe.foundation.loop.intention.models import (
            IntentClassificationLLMResult,
            TaskComplexity,
        )

        classifier = IntentClassifier(model=MagicMock(), assistant_name="Soothe")
        mock_result = IntentClassificationLLMResult(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="I'm Soothe, your assistant.",
        )

        invoke_mock = AsyncMock(return_value=mock_result.model_dump())
        with patch(
            "soothe.foundation.loop.intention.classifier.invoke_structured_chat",
            invoke_mock,
        ):
            await classifier._classify_intent_llm("who are u")

        messages = self._messages_from_invoke_call(invoke_mock.call_args)
        assert isinstance(messages[0], SystemMessage)
        assert "You are Soothe" in str(messages[0].content)
        assert isinstance(messages[1], HumanMessage)
        assert "who are u" in str(messages[1].content)
