"""Daemon-side stream delivery shaping for loop event broadcast (RFC-614)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from soothe.foundation import extract_text_from_ai_message
from soothe_sdk.client.wire import prepare_stream_data_for_wire
from soothe_sdk.ux.loop_stream import assistant_output_phase

StreamDeliveryMode = Literal["batch", "merged", "full"]

AGENT_LOOP_COMPLETED = "soothe.cognition.agent_loop.completed"

# Coalesced goal-completion flushes for TUI (fewer WebSocket frames).
_MERGED_FLUSH_CHARS = 512

_MSG_PAIR_LEN = 2


@dataclass
class _GoalCompletionBuffer:
    namespace: tuple[str, ...]
    parts: list[str] = field(default_factory=list)
    template_msg: dict[str, Any] | None = None
    template_meta: dict[str, Any] | None = None


class StreamDeliveryCoalescer:
    """Shape runner stream tuples before daemon broadcast to clients."""

    def __init__(self, mode: StreamDeliveryMode) -> None:
        self._mode: StreamDeliveryMode = mode if mode in ("batch", "merged", "full") else "merged"
        self._gc: _GoalCompletionBuffer | None = None
        self._turn_complete_pending = False

    @property
    def turn_complete_pending(self) -> bool:
        """True after ``agent_loop.completed`` was ingested (caller should signal idle)."""
        return self._turn_complete_pending

    def consume_turn_complete_pending(self) -> bool:
        """Return and clear the turn-complete flag."""
        pending = self._turn_complete_pending
        self._turn_complete_pending = False
        return pending

    def ingest(
        self,
        namespace: tuple[str, ...] | list[str],
        mode: str,
        data: Any,
    ) -> list[tuple[tuple[str, ...], str, Any]]:
        """Return zero or more stream tuples to broadcast for this ingested chunk."""
        ns = tuple(namespace) if namespace else ()

        if mode == "custom" and isinstance(data, dict) and data.get("type") == AGENT_LOOP_COMPLETED:
            out = self._flush_goal_completion(final=True)
            out.append((ns, mode, data))
            self._turn_complete_pending = True
            return out

        if self._mode == "full" or mode != "messages":
            return [(ns, mode, data)]

        if not isinstance(data, (tuple, list)) or len(data) != _MSG_PAIR_LEN:
            return [(ns, mode, data)]

        msg = data[0]
        phase = assistant_output_phase(msg)
        if phase != "goal_completion":
            return [(ns, mode, data)]

        wire_data = prepare_stream_data_for_wire(data)
        msg_wire = wire_data[0] if isinstance(wire_data, (tuple, list)) and wire_data else msg
        if not isinstance(msg_wire, dict):
            return [(ns, mode, data)]

        self._accumulate_goal_completion(ns, msg_wire, wire_data[1] if len(wire_data) > 1 else {})

        if self._mode == "batch":
            return []

        if (
            self._mode == "merged"
            and self._joined_text()
            and len(self._joined_text()) >= _MERGED_FLUSH_CHARS
        ):
            return self._flush_goal_completion(final=False)

        return []

    def flush(self) -> list[tuple[tuple[str, ...], str, Any]]:
        """Flush any buffered goal-completion text at stream end."""
        return self._flush_goal_completion(final=True)

    def _accumulate_goal_completion(
        self,
        namespace: tuple[str, ...],
        msg_wire: dict[str, Any],
        metadata: Any,
    ) -> None:
        if self._gc is None:
            self._gc = _GoalCompletionBuffer(namespace=namespace)
        self._gc.template_msg = dict(msg_wire)
        if isinstance(metadata, dict):
            self._gc.template_meta = dict(metadata)
        for piece in extract_text_from_ai_message(msg_wire):
            if piece:
                self._gc.parts.append(piece)

    def _joined_text(self) -> str:
        if self._gc is None:
            return ""
        return "".join(self._gc.parts)

    def _flush_goal_completion(self, *, final: bool) -> list[tuple[tuple[str, ...], str, Any]]:
        if self._gc is None or not self._gc.parts:
            self._gc = None
            return []

        text = self._joined_text()
        msg = dict(self._gc.template_msg or {})
        msg.setdefault("type", "AIMessageChunk")
        msg["content"] = text
        msg["phase"] = "goal_completion"
        if final:
            msg["chunk_position"] = "last"
        elif "chunk_position" in msg:
            msg.pop("chunk_position", None)

        meta: dict[str, Any] = {}
        if isinstance(self._gc.template_meta, dict):
            meta = dict(self._gc.template_meta)

        namespace = self._gc.namespace
        self._gc = None
        wire = prepare_stream_data_for_wire((msg, meta))
        return [(namespace, "messages", wire)]


__all__ = [
    "AGENT_LOOP_COMPLETED",
    "StreamDeliveryCoalescer",
    "StreamDeliveryMode",
]
