"""AgentLoop-specific message types with thread/iteration context."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import Field
from soothe_sdk.ux.loop_stream import LOOP_ASSISTANT_OUTPUT_PHASES as ASSISTANT_OUTPUT_PHASES


def loop_message_assistant_output_phase(msg: Any) -> str | None:
    """Return ``phase`` when ``msg`` is a loop-tagged assistant-output message."""
    if msg is None:
        return None
    phase = getattr(msg, "phase", None)
    if isinstance(phase, str) and phase in ASSISTANT_OUTPUT_PHASES:
        return phase
    if isinstance(msg, dict):
        p = msg.get("phase")
        if isinstance(p, str) and p in ASSISTANT_OUTPUT_PHASES:
            return p
    return None


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
    phase: Literal["execute_wave", "execute_step", "goal_completion", "chitchat", "quiz"] | None = (
        None
    )
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


class LoopAIMessageChunk(AIMessageChunk):
    """Streaming AI chunk with AgentLoop ``phase`` metadata (IG-317 / RFC-614)."""

    thread_id: str | None = None
    iteration: int | None = None
    phase: str | None = None
    wave_id: str | None = None

    type: Literal["AIMessageChunk"] = "AIMessageChunk"


def loop_assistant_messages_chunk(
    *,
    content: str,
    phase: str,
    thread_id: str,
    iteration: int | None = None,
) -> tuple[tuple[str, ...], str, tuple[LoopAIMessage, dict[str, Any]]]:
    """Build a root ``messages``-mode stream chunk for piggybacked assistant text (IG-317)."""
    if phase not in ASSISTANT_OUTPUT_PHASES:
        raise ValueError(f"Invalid assistant output phase: {phase}")
    msg = LoopAIMessage(content=content, thread_id=thread_id, iteration=iteration, phase=phase)
    return ((), "messages", (msg, {}))


def tag_messages_stream_chunk_for_goal_completion(
    chunk: Any,
    *,
    thread_id: str,
    iteration: int,
) -> Any:
    """Tag AI payloads in a LangGraph ``messages`` chunk with ``phase=goal_completion`` (IG-317)."""
    from langchain_core.messages import AIMessage as LCAIMessage
    from langchain_core.messages import AIMessageChunk as LCAIMessageChunk
    from langchain_core.messages import ToolMessage

    from soothe.cognition.agent_loop.utils.stream_normalize import parse_tuple_stream_chunk

    parsed = parse_tuple_stream_chunk(chunk)
    if parsed is None:
        return chunk
    namespace, mode, data = parsed
    if mode != "messages" or not isinstance(data, (tuple, list)) or len(data) < 2:
        return chunk
    msg, meta = data[0], data[1]
    if isinstance(msg, ToolMessage):
        return chunk
    if loop_message_assistant_output_phase(msg) == "goal_completion":
        return chunk
    if isinstance(msg, LCAIMessageChunk):
        tagged = LoopAIMessageChunk.model_validate(
            {
                **msg.model_dump(),
                "thread_id": thread_id,
                "iteration": iteration,
                "phase": "goal_completion",
            }
        )
        return (namespace, mode, (tagged, meta))
    if isinstance(msg, LCAIMessage):
        tagged = LoopAIMessage.model_validate(
            {
                **msg.model_dump(),
                "thread_id": thread_id,
                "iteration": iteration,
                "phase": "goal_completion",
            }
        )
        return (namespace, mode, (tagged, meta))
    return chunk


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
