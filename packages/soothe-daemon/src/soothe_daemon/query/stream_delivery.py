"""Daemon-side stream delivery shaping for loop event broadcast (RFC-614)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from soothe.foundation import extract_text_from_ai_message
from soothe_sdk.client.wire import prepare_stream_data_for_wire
from soothe_sdk.core.events import AGENT_LOOP_COMPLETED
from soothe_sdk.ux.loop_stream import assistant_output_phase

StreamDeliveryMode = Literal["batch", "adaptive"]


_MSG_PAIR_LEN = 2


@dataclass
class _GoalCompletionBuffer:
    namespace: tuple[str, ...]
    parts: list[str] = field(default_factory=list)
    template_msg: dict[str, Any] | None = None
    template_meta: dict[str, Any] | None = None
    char_count: int = 0  # Track accumulated size


class StreamDeliveryCoalescer:
    """Shape runner stream tuples before daemon broadcast to clients.

    Supports two modes:
    - "batch": Always accumulate goal_completion chunks and emit single final message
    - "adaptive": Stream small outputs (< threshold), batch large outputs (>= threshold)

    Also supports file output for goal_completion exceeding file_output_threshold_chars.
    """

    def __init__(
        self,
        mode: StreamDeliveryMode,
        *,
        adaptive_threshold_chars: int = 500,
        file_output_threshold_chars: int = 5000,
        file_output_preview_chars: int = 500,
        file_output_dir: str | None = None,
        workspace: str | None = None,
    ) -> None:
        self._mode: StreamDeliveryMode = mode
        self._adaptive_threshold_chars = adaptive_threshold_chars
        self._file_output_threshold_chars = file_output_threshold_chars
        self._file_output_preview_chars = file_output_preview_chars
        self._file_output_dir = file_output_dir
        self._workspace = workspace
        self._gc: _GoalCompletionBuffer | None = None
        self._turn_complete_pending = False
        # Internal state for adaptive mode decision
        self._effective_mode: Literal["batch", "streaming"] = "streaming"
        self._adaptive_decision_made = False

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

        # Handle AGENT_LOOP_COMPLETED: flush goal_completion and pass through event
        if mode == "custom" and isinstance(data, dict) and data.get("type") == AGENT_LOOP_COMPLETED:
            out = self._flush_goal_completion(final=True)
            out.append((ns, mode, data))
            self._turn_complete_pending = True
            return out

        # Non-messages mode: always pass through
        if mode != "messages":
            return [(ns, mode, data)]

        # Validate message pair structure
        if not isinstance(data, (tuple, list)) or len(data) != _MSG_PAIR_LEN:
            return [(ns, mode, data)]

        msg = data[0]
        phase = assistant_output_phase(msg)

        # Non-goal_completion messages: always pass through
        if phase != "goal_completion":
            return [(ns, mode, data)]

        # Prepare wire data for goal_completion
        wire_data = prepare_stream_data_for_wire(data)
        msg_wire = wire_data[0] if isinstance(wire_data, (tuple, list)) and wire_data else msg
        if not isinstance(msg_wire, dict):
            return [(ns, mode, data)]

        # Batch mode: always accumulate (suppress until flush)
        if self._mode == "batch":
            self._accumulate_goal_completion(
                ns, msg_wire, wire_data[1] if len(wire_data) > 1 else {}
            )
            return []

        # Adaptive mode: decide based on accumulated size
        # Below threshold: stream (pass through); above threshold: batch
        if not self._adaptive_decision_made:
            self._accumulate_goal_completion(
                ns, msg_wire, wire_data[1] if len(wire_data) > 1 else {}
            )
            chars = len(self._joined_text())
            if chars >= self._adaptive_threshold_chars:
                # Switch to batching for large output
                self._effective_mode = "batch"
                self._adaptive_decision_made = True
                return []  # Suppress, will flush at end
            else:
                # Small output: continue streaming (pass through)
                return [(ns, mode, data)]

        # Adaptive already decided to batch: accumulate
        self._accumulate_goal_completion(ns, msg_wire, wire_data[1] if len(wire_data) > 1 else {})
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
                self._gc.char_count += len(piece)

    def _joined_text(self) -> str:
        if self._gc is None:
            return ""
        return "".join(self._gc.parts)

    def _flush_goal_completion(self, *, final: bool) -> list[tuple[tuple[str, ...], str, Any]]:
        if self._gc is None or not self._gc.parts:
            self._gc = None
            return []

        text = self._joined_text()

        # Check file output threshold for large synthesis
        if self._file_output_threshold_chars > 0 and len(text) >= self._file_output_threshold_chars:
            return self._emit_file_output_message(text)

        # Normal output (below threshold or threshold disabled)
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

    def _emit_file_output_message(self, text: str) -> list[tuple[tuple[str, ...], str, Any]]:
        """Write large goal_completion to file and emit summary message."""
        file_path = self._write_goal_completion_to_file(text)
        preview = (
            text[: self._file_output_preview_chars] if self._file_output_preview_chars > 0 else ""
        )

        msg = {
            "type": "AIMessageChunk",
            "content": preview + f"\n\n---\n**Full output saved to:** `{file_path}`",
            "phase": "goal_completion",
            "chunk_position": "last",
            "file_output_path": file_path,
            "file_output_size": len(text),
        }
        meta: dict[str, Any] = {}

        namespace = self._gc.namespace if self._gc else ()
        self._gc = None
        wire = prepare_stream_data_for_wire((msg, meta))
        return [(namespace, "messages", wire)]

    def _write_goal_completion_to_file(self, text: str) -> str:
        """Write goal_completion to file, return path.

        Uses workspace root/.soothe/output as default directory.
        """
        # Determine output directory
        if self._file_output_dir:
            output_dir = Path(self._file_output_dir)
        elif self._workspace:
            output_dir = Path(self._workspace) / ".soothe" / "output"
        else:
            output_dir = Path.home() / ".soothe" / "output"

        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp and UUID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"synthesis_{timestamp}_{uuid.uuid4().hex[:8]}.md"

        file_path = output_dir / filename
        file_path.write_text(text)

        return str(file_path)


__all__ = [
    "AGENT_LOOP_COMPLETED",
    "StreamDeliveryCoalescer",
    "StreamDeliveryMode",
]
