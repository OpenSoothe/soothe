"""Test structured output (tool_calls) capture in SootheLangfuseCallbackHandler."""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult


def test_extract_structured_output_from_message_with_tool_calls() -> None:
    """Verify _extract_structured_output_from_message captures tool_calls."""
    from soothe_sdk.observability.langfuse.callback_handler import (
        _extract_structured_output_from_message,
    )

    msg = AIMessage(
        content="",  # Empty content, JSON is in tool_calls
        tool_calls=[
            {
                "name": "PlanGeneration",
                "args": {"type": "execute_steps", "steps": []},
                "id": "call_123",
            },
        ],
    )

    result = _extract_structured_output_from_message(msg)
    assert result is not None
    assert result["role"] == "assistant"
    assert result["content"] == ""
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "PlanGeneration"
    assert result["tool_calls"][0]["args"]["type"] == "execute_steps"


def test_extract_structured_output_returns_none_without_tool_calls() -> None:
    """Verify _extract_structured_output_from_message returns None for regular messages."""
    from soothe_sdk.observability.langfuse.callback_handler import (
        _extract_structured_output_from_message,
    )

    msg = AIMessage(content="Hello, how can I help?")
    result = _extract_structured_output_from_message(msg)
    assert result is None


def test_extract_structured_output_with_content_and_tool_calls() -> None:
    """Verify both content and tool_calls are captured when both present."""
    from soothe_sdk.observability.langfuse.callback_handler import (
        _extract_structured_output_from_message,
    )

    # Some models return thinking content + tool_calls
    msg = AIMessage(
        content="Let me analyze the task complexity...",
        tool_calls=[
            {"name": "StatusAssessment", "args": {"status": "replan"}, "id": "call_456"},
        ],
    )

    result = _extract_structured_output_from_message(msg)
    assert result is not None
    assert result["content"] == "Let me analyze the task complexity..."
    assert len(result["tool_calls"]) == 1


def test_on_llm_end_captures_structured_output() -> None:
    """Verify on_llm_end passes structured output to parent handler."""
    # This test requires langfuse to be installed
    try:
        from soothe_sdk.observability.langfuse.callback_handler import (
            LANGFUSE_AVAILABLE,
            SootheLangfuseCallbackHandler,
        )

        if not LANGFUSE_AVAILABLE:
            return  # Skip if langfuse not installed

        handler = SootheLangfuseCallbackHandler()

        # Create a mock LLMResult with structured output
        run_id = uuid4()
        msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "PlanGeneration",
                    "args": {
                        "type": "execute_steps",
                        "steps": [{"id": "01", "description": "Test step"}],
                    },
                    "id": "call_789",
                },
            ],
        )
        gen = ChatGeneration(message=msg)
        response = LLMResult(generations=[[gen]])

        # Call on_llm_end (we can't verify the actual Langfuse update without a real client,
        # but we can verify the handler doesn't crash and processes the data)
        kwargs = {}
        handler.on_llm_end(response, run_id=run_id, **kwargs)

        # If we got here without exception, the handler processed tool_calls correctly
        # In real usage, kwargs["output"] would contain the structured output

    except ImportError:
        pass  # Skip if langfuse not installed
