"""AgentLoop-specific message types with thread/iteration context."""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import Field


class LoopHumanMessage(HumanMessage):
    """AgentLoop HumanMessage with thread/iteration context.

    Extends HumanMessage to capture LoopState context for:
    - Thread tracking (thread_id)
    - Iteration tracking (iteration)
    - Goal context (goal_summary)
    - Execution phase (phase: "execute_wave", "execute_step", "goal_completion")
    - Wave tracking (wave_id for execute_wave phase)

    All fields are Optional to support all message creation points uniformly,
    including planner/synthesis calls without thread context.

    Inherits all langchain HumanMessage fields and behavior:
    - content: Message text (required)
    - type: Literal["human"] (preserved)
    - Serialization via messages_to_dict() preserves extra fields

    Example:
        >>> msg = LoopHumanMessage(
        ...     content="Execute: Search for relevant files",
        ...     thread_id="thread_123",
        ...     iteration=2,
        ...     goal_summary="Find configuration files",
        ...     phase="execute_step",
        ... )
        >>> msg.thread_id  # Access agentloop metadata
        'thread_123'
    """

    # AgentLoop context fields (all optional)
    thread_id: str | None = None
    iteration: int | None = None
    goal_summary: str | None = Field(default=None, max_length=200)
    workspace: str | None = None
    phase: Literal["execute_wave", "execute_step", "goal_completion"] | None = None
    wave_id: str | None = None  # UUID[:8] for wave tracking

    # Preserve langchain type discrimination
    type: Literal["human"] = "human"


class LoopAIMessage(AIMessage):
    """AgentLoop AIMessage with iteration metadata.

    Extends AIMessage to preserve:
    - response_metadata for token extraction (executor._extract_token_usage)
    - usage_metadata for standardized token counts
    - tool_calls for tool tracking
    - AgentLoop-specific metadata (iteration, phase)

    NOTE: LoopAIMessage is rarely directly instantiated - CoreAgent returns
    AIMessage/AIMessageChunk from .astream(). This class enables future
    wrapping/injection of custom AI messages if needed.

    Inherits all langchain AIMessage fields:
    - content: Response text (required)
    - response_metadata: Dict with token_usage (critical for executor)
    - usage_metadata: Standardized token counts
    - tool_calls: List of tool invocations
    - type: Literal["ai"] (preserved)

    Example:
        >>> ai_msg = LoopAIMessage(
        ...     content="Found 5 files",
        ...     response_metadata={"token_usage": {"total_tokens": 150}},
        ...     iteration=2,
        ...     phase="execute_wave",
        ... )
        >>> ai_msg.response_metadata["token_usage"]["total_tokens"]
        150
    """

    # AgentLoop context fields (optional)
    thread_id: str | None = None
    iteration: int | None = None
    phase: str | None = None
    wave_id: str | None = None

    # Inherited: response_metadata, usage_metadata, tool_calls, content
    type: Literal["ai"] = "ai"


def loop_message_to_thread_metadata(msg: LoopHumanMessage) -> dict[str, str | int | None]:
    """Extract metadata from LoopHumanMessage for ThreadMessage persistence.

    Converts LoopHumanMessage fields to a flat dict suitable for
    ThreadMessage.metadata field.

    Args:
        msg: LoopHumanMessage with agentloop context (may have None fields)

    Returns:
        Dict with thread_id, iteration, goal_summary, phase, wave_id, workspace.
        Fields may be None if message was created without thread context.

    Example:
        >>> msg = LoopHumanMessage(content="Test", thread_id="abc", iteration=5)
        >>> metadata = loop_message_to_thread_metadata(msg)
        >>> metadata["thread_id"]
        'abc'
        >>> metadata["iteration"]
        5
    """
    return {
        "thread_id": msg.thread_id,
        "iteration": msg.iteration,
        "goal_summary": msg.goal_summary,
        "phase": msg.phase,
        "wave_id": msg.wave_id,
        "workspace": msg.workspace,
    }
