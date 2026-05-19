"""Per-turn coalescing, wire deduplication, and event-loop yield for TUI stream handling."""

from __future__ import annotations

import asyncio
import json
from time import monotonic
from typing import Any

from soothe_cli.tui.widgets.messages import (
    flush_deferred_tools_refreshes,
    reset_turn_tool_refresh_state,
)

# Match AssistantMessage streaming batch cadence.
_TOOL_UI_COALESCE_SEC = 0.05
_CHUNK_YIELD_INTERVAL = 24
_CHUNK_YIELD_BUDGET_SEC = 0.016


class TurnToolUiCoalescer:
    """Batch tool-card repaints, dedupe wire kwargs, and yield during dense streams."""

    def __init__(self) -> None:
        reset_turn_tool_refresh_state()
        self._chunk_count = 0
        self._burst_start = monotonic()
        self._last_flush_at = 0.0
        self._wire_args_fingerprint: dict[str, str] = {}
        self.execute_wave_active = False

    def reset_turn(self) -> None:
        """Clear per-turn state (new user turn)."""
        reset_turn_tool_refresh_state()
        self._chunk_count = 0
        self._burst_start = monotonic()
        self._last_flush_at = 0.0
        self._wire_args_fingerprint.clear()
        self.execute_wave_active = False

    def note_wire_apply(self, tool_call_id: str, args: dict[str, Any]) -> bool:
        """Record a wire kwargs payload.

        Returns:
            True when the same ``(tool_call_id, args)`` was already applied.
        """
        key = str(tool_call_id).strip()
        if not key:
            return False
        try:
            fp = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            fp = repr(args)
        if self._wire_args_fingerprint.get(key) == fp:
            return True
        self._wire_args_fingerprint[key] = fp
        return False

    def wire_applied(self, tool_call_id: str) -> bool:
        """True when wire has already delivered displayable kwargs for this id."""
        return str(tool_call_id).strip() in self._wire_args_fingerprint

    def should_skip_messages_arg_refresh(self, tool_call_id: str) -> bool:
        """Skip messages-path arg refresh when execute wave uses wire authority."""
        if not self.execute_wave_active:
            return False
        return self.wire_applied(tool_call_id)

    async def after_chunk(self, *, force_flush: bool = False) -> None:
        """Yield to Textual when needed and flush deferred tool-list repaints."""
        self._chunk_count += 1
        now = monotonic()
        if self._chunk_count % _CHUNK_YIELD_INTERVAL == 0:
            await asyncio.sleep(0)
            self._burst_start = now
        elif now - self._burst_start >= _CHUNK_YIELD_BUDGET_SEC:
            await asyncio.sleep(0)
            self._burst_start = now

        if force_flush or (now - self._last_flush_at) >= _TOOL_UI_COALESCE_SEC:
            flush_deferred_tools_refreshes(force=force_flush)
            self._last_flush_at = now

    async def flush_final(self) -> None:
        """Force pending tool UI updates at end of turn or interrupt."""
        flush_deferred_tools_refreshes(force=True)


__all__ = [
    "TurnToolUiCoalescer",
]
