"""Background-thread preparation for daemon stream chunks (TUI turn loop).

Runs CPU-heavy parsing off the main asyncio loop. The applier on the main loop
consumes ``PreparedTurnChunk`` values and performs widget updates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import ToolMessage
from soothe_client.appkit.turn import (
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
)
from soothe_sdk.core.events import (
    STRANGE_LOOP_COMPLETED,
    STRANGE_LOOP_PLAN_DECISION,
    STRANGE_LOOP_STARTED,
    STRANGE_LOOP_STEP_COMPLETED,
    STRANGE_LOOP_STEP_QUEUED,
    STRANGE_LOOP_STEP_STARTED,
)
from soothe_sdk.ux.classification import classify_event_to_tier
from soothe_sdk.ux.loop_stream import assistant_output_phase
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, TOOL_CALL_UPDATES_BATCH

from soothe_cli.runtime.presentation.engine import PresentationEngine
from soothe_cli.runtime.state.session_stats import TurnEventStats
from soothe_cli.runtime.wire.chunk_filter import (
    message_has_tool_invocation_metadata,
    updates_chunk_is_noop,
)
from soothe_cli.runtime.wire.messages import is_summarization_chunk, normalize_lc_stream_message

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2

_MAIN_LOOP_CUSTOM_TYPES = frozenset(
    {
        STREAM_TOOL_CALL_UPDATE,
        TOOL_CALL_UPDATES_BATCH,
        STRANGE_LOOP_STARTED,
        STRANGE_LOOP_COMPLETED,
        STRANGE_LOOP_PLAN_DECISION,
        STRANGE_LOOP_STEP_STARTED,
        STRANGE_LOOP_STEP_QUEUED,
        STRANGE_LOOP_STEP_COMPLETED,
    }
)


@dataclass
class PreparedTurnChunk:
    """Chunk plan produced on the processor thread and applied on the main loop."""

    namespace: tuple[Any, ...]
    mode: str
    data: Any
    priority: int = PRIORITY_LOW
    skip: bool = False
    normalized_message: Any | None = None
    message_metadata: Any | None = None
    is_summarization: bool = False
    tool_stream_touched: bool = False


@dataclass
class TurnPrepareState:
    """Mutable per-turn state accessed only from the processor thread.

    Tool-call pending buffers and ``StepTaskRouter`` are updated on the main loop
    only (see ``execute_task_textual`` applier) to avoid races during parallel steps.
    """

    ev_stats: TurnEventStats
    presentation: PresentationEngine


def _message_priority(message: Any, *, is_summarization: bool) -> int:
    if isinstance(message, ToolMessage):
        return PRIORITY_NORMAL
    if message_has_tool_invocation_metadata(message):
        return PRIORITY_NORMAL
    if is_summarization:
        return PRIORITY_NORMAL
    # Loop-tagged assistant output (plan_direct, goal_completion, etc.) is interleaved
    # with high-priority loop progress events (plan_decision, step_started). Default LOW
    # priority bumps them behind progress events even when emitted first, so e.g. the
    # plan_direct prose lands after the step card. Match progress priority so FIFO
    # sequence wins within the priority class.
    if assistant_output_phase(message) is not None:
        return PRIORITY_HIGH
    return PRIORITY_LOW


def prepare_turn_chunk(state: TurnPrepareState, chunk: Any) -> PreparedTurnChunk | None:
    """Prepare one daemon chunk on the processor thread."""
    if not isinstance(chunk, (list, tuple)) or len(chunk) != _STREAM_CHUNK_LEN:
        state.ev_stats.skipped += 1
        return None

    namespace, mode, data = chunk
    ns_key = tuple(namespace) if namespace else ()

    if mode == "updates" and updates_chunk_is_noop(data):
        state.ev_stats.filtered_early += 1
        return None

    state.ev_stats.record(str(mode))

    prepared = PreparedTurnChunk(namespace=ns_key, mode=str(mode), data=data)

    if mode == "messages":
        return _prepare_messages_chunk(state, prepared, ns_key, data)
    if mode == "custom" and isinstance(data, dict):
        return _prepare_custom_chunk(state, prepared, ns_key, data)
    if mode == "updates":
        prepared.priority = PRIORITY_NORMAL
        return prepared
    return prepared


def _prepare_messages_chunk(
    state: TurnPrepareState,
    prepared: PreparedTurnChunk,
    ns_key: tuple[Any, ...],
    data: Any,
) -> PreparedTurnChunk | None:
    if not isinstance(data, (list, tuple)) or len(data) != _MSG_PAIR_LEN:
        return None

    message, metadata = data[0], data[1] if len(data) > 1 else {}
    message = normalize_lc_stream_message(message)
    prepared.normalized_message = message
    prepared.message_metadata = metadata
    prepared.is_summarization = is_summarization_chunk(metadata)
    prepared.priority = _message_priority(message, is_summarization=prepared.is_summarization)

    if not prepared.is_summarization and message_has_tool_invocation_metadata(message):
        prepared.tool_stream_touched = True

    return prepared


def _prepare_custom_chunk(
    state: TurnPrepareState,
    prepared: PreparedTurnChunk,
    ns_key: tuple[Any, ...],
    data: dict[str, Any],
) -> PreparedTurnChunk:
    event_type = str(data.get("type", ""))

    if event_type.startswith("soothe.error"):
        prepared.priority = PRIORITY_HIGH
        return prepared

    if event_type in (
        STRANGE_LOOP_STEP_STARTED,
        STRANGE_LOOP_STEP_QUEUED,
        STRANGE_LOOP_STEP_COMPLETED,
        STRANGE_LOOP_PLAN_DECISION,
    ):
        prepared.priority = PRIORITY_CRITICAL
        return prepared

    if event_type in _MAIN_LOOP_CUSTOM_TYPES or event_type == TOOL_CALL_UPDATES_BATCH:
        prepared.priority = PRIORITY_HIGH
        return prepared

    category = classify_event_to_tier(event_type, ns_key)
    if not state.presentation.tier_visible(category):
        prepared.skip = True
        return prepared

    # Output events have a dedicated renderer path; drop the generic copy.
    if event_type.startswith("soothe.output."):
        prepared.skip = True
        return prepared

    return prepared


__all__ = ["PreparedTurnChunk", "TurnPrepareState", "prepare_turn_chunk"]
