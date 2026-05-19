"""Background-thread preparation for daemon stream chunks (TUI turn loop).

Runs CPU-heavy parsing and ``StreamDisplayPipeline`` formatting off the main
asyncio loop so Textual can keep rendering. The applier on the main loop consumes
``PreparedTurnChunk`` values and performs widget updates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soothe_sdk.core.subagent_wire import is_allowlisted_subagent_event_type
from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux.classification import classify_event_to_tier
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe_cli.events.stream import StreamDisplayPipeline
from soothe_cli.events.core.presentation_engine import PresentationEngine
from soothe_cli.events.tools.message_processing import (
    ingest_tool_call_stream_state,
)
from soothe_cli.tui._session_stats import TurnEventStats
from soothe_cli.tui.step_task_routing import StepTaskRouter
from soothe_cli.tui.textual_adapter._adapter import (
    AGENT_LOOP_GOAL_COMPLETED,
    AGENT_LOOP_GOAL_STARTED,
    AGENT_LOOP_PLAN_DECISION,
    AGENT_LOOP_STEP_COMPLETED,
    AGENT_LOOP_STEP_STARTED,
)
from soothe_cli.events.stream.tui_format import format_display_line_for_tui
from soothe_cli.events.turn.messages import is_summarization_chunk, normalize_lc_stream_message

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2

# Custom events handled on the main loop (widgets / router side effects).
_MAIN_LOOP_CUSTOM_TYPES = frozenset(
    {
        STREAM_TOOL_CALL_UPDATE,
        AGENT_LOOP_GOAL_STARTED,
        AGENT_LOOP_GOAL_COMPLETED,
        AGENT_LOOP_PLAN_DECISION,
        AGENT_LOOP_STEP_STARTED,
        AGENT_LOOP_STEP_COMPLETED,
    }
)


@dataclass
class PreparedTurnChunk:
    """Chunk plan produced on the processor thread and applied on the main loop."""

    namespace: tuple[Any, ...]
    mode: str
    data: Any
    skip: bool = False
    normalized_message: Any | None = None
    message_metadata: Any | None = None
    precomputed_progress_lines: list[str] = field(default_factory=list)
    skip_custom_progress: bool = False
    is_summarization: bool = False
    tool_stream_touched: bool = False


@dataclass
class TurnPrepareState:
    """Mutable per-turn state accessed only from the processor thread."""

    ev_stats: TurnEventStats
    router: StepTaskRouter
    progress_pipeline: StreamDisplayPipeline
    presentation: PresentationEngine
    pending_tool_calls_lc: dict[str, dict[str, Any]]
    streaming_overlay: dict[str, dict[str, Any]]
    show_tool_ui: bool
    last_active_tool_call_id: str = ""

    def ingest_message_tool_stream(
        self,
        message: Any,
        *,
        is_main: bool,
    ) -> None:
        """Accumulate streaming tool-call args (IG-053) on the processor thread."""
        self.last_active_tool_call_id = ingest_tool_call_stream_state(
            self.pending_tool_calls_lc,
            message,
            is_main=is_main,
            last_active_id=self.last_active_tool_call_id,
        )


def prepare_turn_chunk(state: TurnPrepareState, chunk: Any) -> PreparedTurnChunk | None:
    """Prepare one daemon chunk on the processor thread.

    Args:
        state: Per-turn prepare state (processor thread only).
        chunk: ``(namespace, mode, data)`` tuple from the daemon.

    Returns:
        A plan for the applier, or ``None`` when the chunk is invalid and should be
        ignored.
    """
    if not isinstance(chunk, (list, tuple)) or len(chunk) != _STREAM_CHUNK_LEN:
        state.ev_stats.skipped += 1
        return None

    namespace, mode, data = chunk
    ns_key = tuple(namespace) if namespace else ()
    state.ev_stats.record(str(mode))

    prepared = PreparedTurnChunk(namespace=ns_key, mode=str(mode), data=data)

    if mode == "messages":
        return _prepare_messages_chunk(state, prepared, ns_key, data)
    if mode == "custom" and isinstance(data, dict):
        return _prepare_custom_chunk(state, prepared, ns_key, data)
    if mode == "updates":
        return prepared
    return prepared


def _prepare_messages_chunk(
    state: TurnPrepareState,
    prepared: PreparedTurnChunk,
    ns_key: tuple[Any, ...],
    data: Any,
) -> PreparedTurnChunk | None:
    if ns_key:
        state.router.on_subgraph_namespace(ns_key)

    if not isinstance(data, (list, tuple)) or len(data) != _MSG_PAIR_LEN:
        return None

    message, metadata = data
    message = normalize_lc_stream_message(message)
    prepared.normalized_message = message
    prepared.message_metadata = metadata
    prepared.is_summarization = is_summarization_chunk(metadata)

    is_main = ns_key == ()
    if not prepared.is_summarization:
        state.ingest_message_tool_stream(message, is_main=is_main)
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
        return prepared

    if event_type in _MAIN_LOOP_CUSTOM_TYPES:
        prepared.skip_custom_progress = True
        return prepared

    category = classify_event_to_tier(event_type, ns_key)
    if not state.presentation.tier_visible(category):
        prepared.skip = True
        return prepared

    task_scope = state.router.resolve_task_scope(ns_key) if ns_key else None
    if (
        task_scope
        and event_type.startswith("soothe.subagent.")
        and is_allowlisted_subagent_event_type(event_type)
    ):
        # Parent card append is resolved on the main loop; only precompute lines here.
        ev_wire = dict(data)
        ev_wire.setdefault("type", event_type)
        ev_wire["namespace"] = list(ns_key)
        ev_wire["task_scope"] = task_scope
        prepared.precomputed_progress_lines = _lines_from_pipeline(state, ev_wire)
        prepared.skip_custom_progress = True
        return prepared

    if category == VerbosityTier.QUIET and "error" not in event_type:
        prepared.skip = True
        return prepared

    event_for_pipeline = dict(data)
    event_for_pipeline["namespace"] = list(ns_key)
    if task_scope:
        event_for_pipeline["task_scope"] = task_scope
    prepared.precomputed_progress_lines = _lines_from_pipeline(state, event_for_pipeline)
    prepared.skip_custom_progress = bool(prepared.precomputed_progress_lines)
    return prepared


def _lines_from_pipeline(state: TurnPrepareState, event_for_pipeline: dict[str, Any]) -> list[str]:
    lines = state.progress_pipeline.process(event_for_pipeline)
    out: list[str] = []
    for line in lines:
        text = format_display_line_for_tui(line)
        if text:
            out.append(text)
    return out


__all__ = ["PreparedTurnChunk", "TurnPrepareState", "prepare_turn_chunk"]
