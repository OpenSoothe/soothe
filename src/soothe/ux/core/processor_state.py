"""Processor state for unified event handling.

This module defines the internal state managed by EventProcessor.
Renderers should not modify this state directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.protocols.planner import Plan


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

    # Multi-step plan suppression flag (suppress step text, show final report)
    multi_step_active: bool = False

    # Internal context tracking (suppress internal LLM responses)
    internal_context_active: bool = False

    # Tool call timing for duration display (RFC-0020)
    # Maps tool_call_id -> start_timestamp
    tool_call_start_times: dict[str, float] = field(default_factory=dict)

    def reset_turn(self) -> None:
        """Reset per-turn state.

        Called when a turn ends (status becomes idle/stopped).
        Clears streaming buffers but preserves session state.
        """
        self.pending_tool_calls.clear()
        self.tool_call_start_times.clear()

    def clear_session(self) -> None:
        """Clear all session state.

        Called when thread changes. Resets everything for fresh session.
        """
        self.seen_message_ids.clear()
        self.pending_tool_calls.clear()
        self.current_plan = None
        self.multi_step_active = False
        self.internal_context_active = False
        self.tool_call_start_times.clear()
