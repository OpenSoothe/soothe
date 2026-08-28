"""StrangeLoop-specific message types with thread/iteration context."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import Field
from soothe_sdk.ux.loop_stream import LOOP_ASSISTANT_OUTPUT_PHASES as ASSISTANT_OUTPUT_PHASES

from soothe.sloop.orchestrator.stations import PLANNING_LEDGER_PHASES

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import LoopState


def _char_split_for_trim(text: str, chunk_size: int = 400) -> list[str]:
    """Split long single-line execute output for ``trim_messages`` partial strategy."""
    if not text:
        return [""]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def compact_execute_ai_message(msg: Any, max_tokens: int) -> Any:
    """Bound execute-step AI ledger text using langchain ``trim_messages``."""
    if max_tokens <= 0:
        return msg
    from langchain_core.messages import BaseMessage, trim_messages

    if not isinstance(msg, BaseMessage):
        return msg
    if not type(msg).__name__.endswith("AIMessage"):
        return msg

    trimmed = trim_messages(
        [msg],
        max_tokens=max_tokens,
        token_counter="approximate",
        strategy="last",
        allow_partial=True,
        text_splitter=_char_split_for_trim,
    )
    if not trimmed:
        return msg
    compact = trimmed[0]
    if compact is msg:
        return msg
    copier = getattr(msg, "model_copy", None)
    if callable(copier):
        return copier(update={"content": compact.content})
    return compact


def _record_ledger_message(
    context_engine: Any | None,
    msg: Any,
    phase: str,
) -> None:
    """Record a message to the CE LedgerManager.

    When ``context_engine`` is provided, writes to the CE ledger.
    The ``loop_messages`` property on LoopState automatically reflects CE
    state when bound — no explicit sync call is needed.

    Args:
        context_engine: ContextEngine instance for LedgerManager writes.
            Must be provided in production code. Tests without CE must
            use a sqlite :memory: ContextEngine instance.
        msg: Message to record (should be a BaseMessage subclass).
        phase: Phase tag (e.g., ``execute_step``, ``goal_completion``; legacy
            plan-spine tags such as ``plan_assess`` may appear in old ledgers).

    Raises:
        ValueError: If context_engine is None (production code must provide CE).
    """
    if context_engine is None:
        raise ValueError("_record_ledger_message requires a ContextEngine instance")
    from langchain_core.messages import BaseMessage

    if isinstance(msg, BaseMessage):
        if phase == "execute_step" and type(msg).__name__.endswith("AIMessage"):
            max_tokens = int(getattr(context_engine, "execute_ai_ledger_max_tokens", 0) or 0)
            msg = compact_execute_ai_message(msg, max_tokens)
        context_engine.ledger.record_message(msg, phase)
    else:
        import logging

        logging.getLogger(__name__).warning(
            "_record_ledger_message: non-BaseMessage dropped: %s", type(msg)
        )


def last_ledger_ai_content(state: LoopState) -> str:
    """Return content of the last non-planning ``LoopAIMessage`` in ledger.

    Used by goal completion when ``require_goal_completion=False`` to provide
    the user with the most recent non-planning assistant response from the
    ledger. Historical plan-spine ledger turns (and intake/preamble) must not
    be surfaced as final user output in ``ledger_direct`` completion mode.

    Args:
        state: LoopState with populated ``loop_messages``.

    Returns:
        Content of the last non-planning AI message, or empty string if none found.
    """
    # Dual-read: planning ledger phases + preamble (ancestor context, not output).
    planning_phases = PLANNING_LEDGER_PHASES | {"preamble"}
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
    - Execution phase (``execute_step``, ``goal_completion``, plus legacy
      plan-spine tags still present in old ledgers)
    - Wave tracking (wave_id for execute_wave phase)
    - CoreAgent dedup (core_agent_message_id for reference-based dedup)

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
            "intake",
            "intent_classify",  # persisted intake alias
            "evaluate",  # persisted plan-spine phase
            "assess",  # persisted plan-spine phase
            "plan_assess",  # persisted plan-spine phase
            "generate_plan",  # persisted plan-spine phase
            "plan_generate",  # persisted plan-spine phase
            "analyze_gaps",  # persisted plan-spine phase
            "plan_gap_analysis",  # persisted plan-spine phase
            "execute_wave",
            "execute_step",
            "goal_completion",  # wire-stable
            "goal_interrupted",
            "chitchat",
            "finalize",  # station id (prefer goal_completion for wire)
            "preamble",  # ancestor (user,ai) pairs
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
    - response_metadata for token extraction (``extract_token_usage_from_messages``)
    - usage_metadata for standardized token counts
    - tool_calls for tool tracking
    - StrangeLoop-specific metadata (iteration, phase)
    - CoreAgent dedup (core_agent_message_id for reference-based dedup)

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
    """Streaming AI chunk with StrangeLoop ``phase`` metadata."""

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
    """Build a root ``messages``-mode stream chunk for piggybacked assistant text."""
    if phase not in ASSISTANT_OUTPUT_PHASES:
        raise ValueError(f"Invalid assistant output phase: {phase}")
    msg = LoopAIMessage(content=content, thread_id=thread_id, iteration=iteration, phase=phase)
    return ((), "messages", (msg, {}))


def tag_messages_stream_chunk_for_assistant_phase(
    chunk: Any,
    *,
    phase: str,
    thread_id: str,
    iteration: int | None = None,
) -> Any:
    """Tag AI payloads in a LangGraph ``messages`` chunk with a loop assistant ``phase``."""
    if phase not in ASSISTANT_OUTPUT_PHASES:
        raise ValueError(f"Invalid assistant output phase: {phase}")
    from langchain_core.messages import AIMessage as LCAIMessage
    from langchain_core.messages import AIMessageChunk as LCAIMessageChunk
    from langchain_core.messages import ToolMessage

    from soothe.sloop.utils.stream_normalize import parse_tuple_stream_chunk

    parsed = parse_tuple_stream_chunk(chunk)
    if parsed is None:
        return chunk
    namespace, mode, data = parsed
    if mode != "messages" or not isinstance(data, (tuple, list)) or len(data) < 2:
        return chunk
    msg, meta = data[0], data[1]
    if isinstance(msg, ToolMessage):
        return chunk
    if loop_message_assistant_output_phase(msg) == phase:
        return chunk
    if isinstance(msg, LCAIMessageChunk):
        tagged = LoopAIMessageChunk.model_validate(
            {
                **msg.model_dump(),
                "thread_id": thread_id,
                "iteration": iteration,
                "phase": phase,
            }
        )
        return (namespace, mode, (tagged, meta))
    if isinstance(msg, LCAIMessage):
        tagged = LoopAIMessage.model_validate(
            {
                **msg.model_dump(),
                "thread_id": thread_id,
                "iteration": iteration,
                "phase": phase,
            }
        )
        return (namespace, mode, (tagged, meta))
    return chunk


def tag_messages_stream_chunk_for_goal_completion(
    chunk: Any,
    *,
    thread_id: str,
    iteration: int,
) -> Any:
    """Tag AI payloads in a LangGraph ``messages`` chunk with ``phase=goal_completion``."""
    return tag_messages_stream_chunk_for_assistant_phase(
        chunk,
        phase="goal_completion",
        thread_id=thread_id,
        iteration=iteration,
    )
