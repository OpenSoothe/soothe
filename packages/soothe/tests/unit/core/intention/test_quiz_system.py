"""Tests for quiz-path system message builder."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.core.quiz_messages import build_quiz_system_message


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
        args, _kwargs = call_args  # type: ignore[misc]
        if isinstance(args[0], list):
            return args[0]
        return [args[0]]

    async def test_classify_intent_llm_uses_system_message(self) -> None:
        from soothe.core.intention import IntentClassifier
        from soothe.core.intention.models import IntentClassificationLLMResult, TaskComplexity

        classifier = IntentClassifier(model=MagicMock(), assistant_name="Soothe")
        mock_result = IntentClassificationLLMResult(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="I'm Soothe, your assistant.",
        )
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_result)
        classifier._intent_model = mock_structured

        await classifier._classify_intent_llm("who are u")

        call_args = mock_structured.ainvoke.call_args
        messages = self._messages_from_invoke_call(call_args)
        assert isinstance(messages[0], SystemMessage)
        assert "You are Soothe" in str(messages[0].content)
        assert isinstance(messages[1], HumanMessage)
        assert "who are u" in str(messages[1].content)
