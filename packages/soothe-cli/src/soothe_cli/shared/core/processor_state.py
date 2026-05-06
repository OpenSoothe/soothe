"""Processor state for unified event handling.

This module defines the internal state managed by EventProcessor.
Renderers should not modify this state directly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_sdk.client.schemas import Plan

from soothe_cli.shared.events.stream_accumulator import StreamingTextAccumulator


@dataclass
class ProcessorState:
    """Internal state for EventProcessor.

    This state is owned by the processor and should not be
    modified directly by renderers. Renderers can read state
    via processor properties.
    """

    # Message deduplication - tracks seen message IDs
    seen_message_ids: set[str] = field(default_factory=set)

    # Streaming tool call arg accumulation (IG-053)
    # Maps tool_call_id -> {'name': str, 'args_str': str, 'emitted': bool, 'is_main': bool}
    pending_tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Namespace -> display name mapping for subagents
    name_map: dict[str, str] = field(default_factory=dict)

    # Current plan state (updated on plan events)
    current_plan: Plan | None = None

    # Thread identifier from daemon
    thread_id: str = ""

    # Internal context tracking (suppress internal LLM responses)
    internal_context_active: bool = False

    # Tool call timing for duration display (RFC-0020)
    # Maps tool_call_id -> start_timestamp
    tool_call_start_times: dict[str, float] = field(default_factory=dict)

    # Deduplication for tool calls (prevents duplicate display)
    emitted_tool_call_ids: set[str] = field(default_factory=set)

    # Deduplication for tool results (prevents duplicate display)
    emitted_tool_result_ids: set[str] = field(default_factory=set)

    # Unified streaming text accumulator (RFC-614)
    streaming_accumulator: StreamingTextAccumulator = field(
        default_factory=StreamingTextAccumulator
    )
    """Unified streaming text accumulator with namespace isolation."""

    # Exactly-once final-output guard per loop phase + namespace (RFC-614)
    final_loop_output_emitted: set[tuple[str, tuple[str, ...]]] = field(default_factory=set)
    """(phase, namespace) pairs that already emitted final loop-tagged output this turn."""

    # Task tool spawn queue → bind first subgraph namespace (FIFO; IG-334)
    task_spawn_queue: deque[tuple[str, str]] = field(default_factory=deque)
    namespace_task_bindings: dict[tuple[str, ...], tuple[str, str]] = field(default_factory=dict)

    def reset_turn(self) -> None:
        """Reset per-turn state.

        Called when a turn ends (status becomes idle/stopped).
        Clears streaming buffers but preserves session state.
        """
        self.pending_tool_calls.clear()
        self.tool_call_start_times.clear()
        self.emitted_tool_call_ids.clear()
        self.emitted_tool_result_ids.clear()
        self.streaming_accumulator.finalize_all()
        self.streaming_accumulator.clear()
        self.final_loop_output_emitted.clear()
        self.task_spawn_queue.clear()
        self.namespace_task_bindings.clear()

    def clear_session(self) -> None:
        """Clear all session state.

        Called when thread changes. Resets everything for fresh session.
        """
        self.seen_message_ids.clear()
        self.pending_tool_calls.clear()
        self.current_plan = None
        self.internal_context_active = False
        self.tool_call_start_times.clear()
        self.emitted_tool_call_ids.clear()
        self.emitted_tool_result_ids.clear()
        self.streaming_accumulator.clear()
        self.final_loop_output_emitted.clear()
        self.task_spawn_queue.clear()
        self.namespace_task_bindings.clear()
