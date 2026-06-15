"""StrangeLoop-specific message types with thread/iteration context."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import Field
from soothe_sdk.ux.loop_stream import LOOP_ASSISTANT_OUTPUT_PHASES as ASSISTANT_OUTPUT_PHASES

if TYPE_CHECKING:
    from soothe.foundation.loop.state.schemas import LoopState


def _record_ledger_message(
    context_engine: Any | None,
    msg: Any,
    phase: str,
    loop_messages: list[Any],
) -> None:
    """Append a message to CE LedgerManager (or loop_messages when CE is absent).

    When ``context_engine`` is provided, writes only to the CE ledger.
    The ``loop_messages`` property on LoopState automatically reflects CE
    state when bound — no explicit sync call is needed.

    When CE is None, falls back to appending to ``loop_messages`` directly.

    Args:
        context_engine: ContextEngine instance for direct LedgerManager writes.
        msg: Message to record.
        phase: Phase tag (e.g., "execute_step", "plan_assess", "goal_completion").
        loop_messages: Legacy parameter — only used when CE is absent.
            When CE is present, this list is not modified.
    """
    if context_engine is not None:
        from langchain_core.messages import BaseMessage

        if isinstance(msg, BaseMessage):
            context_engine.ledger.record_message(msg, phase)
            return
    # Fallback: no CE available, write directly to loop_messages
    loop_messages.append(msg)


def last_ledger_ai_content(state: LoopState) -> str:
    """Return content of the last non-planning ``LoopAIMessage`` in ledger.

    Used by goal completion when ``require_goal_completion=False`` to provide
    the user with the most recent non-planning assistant response from the
    ledger, replacing the deprecated ``last_execute_assistant_text`` path.
    RFC-214 records plan-assess and plan-generate turns in the same ledger,
    but these planning messages must not be surfaced as final user output in
    ``ledger_direct`` completion mode.

    Args:
        state: LoopState with populated ``loop_messages``.

    Returns:
        Content of the last non-planning AI message, or empty string if none found.
    """
    planning_phases = {"plan_assess", "plan_generate"}
    for msg in reversed(state.loop_messages):
        if (
            isinstance(msg, LoopAIMessage)
            and msg.content
            and (getattr(msg, "phase", None) not in planning_phases)
        ):
            text = msg.content.strip()
            if text:
                return text
    return ""


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
    """StrangeLoop HumanMessage with thread/iteration context.

    Extends HumanMessage to capture LoopState context for:
    - Thread tracking (thread_id)
    - Iteration tracking (iteration)
    - Goal context (goal_summary)
    - Execution phase (phase: plan_assess, plan_generate, execute_step, etc.)
    - Wave tracking (wave_id for execute_wave phase)
    - CoreAgent dedup (core_agent_message_id for RFC-214 reference-based dedup)

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
        >>> msg.thread_id  # Access sloop metadata
        'thread_123'
    """

    # StrangeLoop context fields (all optional)
    thread_id: str | None = None
    iteration: int | None = None
    goal_summary: str | None = Field(default=None, max_length=200)
    workspace: str | None = None
    phase: (
        Literal[
            "plan_assess",  # RFC-214: Plan assess phase
            "plan_generate",  # RFC-214: Plan generate phase
            "execute_wave",  # Parallel execution wave
            "execute_step",  # Single step execution
            "goal_completion",  # Goal completion phase
            "quiz",  # Quiz / minimal direct reply
        ]
        | None
    ) = None
    wave_id: str | None = None  # UUID[:8] for wave tracking
    # RFC-214: Reference to original CoreAgent message for dedup during ledger projection
    core_agent_message_id: str | None = None

    # Preserve langchain type discrimination
    type: Literal["human"] = "human"


class LoopAIMessage(AIMessage):
    """StrangeLoop AIMessage with iteration metadata.

    Extends AIMessage to preserve:
    - response_metadata for token extraction (executor._extract_token_usage)
    - usage_metadata for standardized token counts
    - tool_calls for tool tracking
    - StrangeLoop-specific metadata (iteration, phase)
    - CoreAgent dedup (core_agent_message_id for RFC-214 reference-based dedup)

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

    # StrangeLoop context fields (optional)
    thread_id: str | None = None
    iteration: int | None = None
    phase: str | None = None
    wave_id: str | None = None
    # RFC-214: Reference to original CoreAgent message for dedup during ledger projection
    core_agent_message_id: str | None = None

    # Inherited: response_metadata, usage_metadata, tool_calls, content
    type: Literal["ai"] = "ai"


class LoopAIMessageChunk(AIMessageChunk):
    """Streaming AI chunk with StrangeLoop ``phase`` metadata (IG-317 / RFC-614)."""

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

    from soothe.foundation.loop.utils.stream_normalize import parse_tuple_stream_chunk

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
        msg: LoopHumanMessage with sloop context (may have None fields)

    Returns:
        Dict with thread_id, iteration, goal_summary, phase, wave_id, workspace,
        and core_agent_message_id.
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
        "core_agent_message_id": msg.core_agent_message_id,
    }
