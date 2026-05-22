"""Daemon-side stream delivery shaping for loop event broadcast (RFC-614)."""

from __future__ import annotations

import time
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
_AI_WIRE_TYPES = frozenset({"ai", "AIMessage", "AIMessageChunk"})
_TOOL_WIRE_TYPES = frozenset({"tool", "ToolMessage"})


@dataclass
class _GoalCompletionBuffer:
    namespace: tuple[str, ...]
    parts: list[str] = field(default_factory=list)
    template_msg: dict[str, Any] | None = None
    template_meta: dict[str, Any] | None = None
    char_count: int = 0


@dataclass
class _TextCoalesceBuffer:
    """Per-namespace accumulator for plain assistant text deltas."""

    namespace: tuple[str, ...]
    parts: list[str] = field(default_factory=list)
    template_msg: dict[str, Any] | None = None
    template_meta: dict[str, Any] | None = None
    last_activity_monotonic: float = 0.0


def _msg_to_wire_dict(msg: Any) -> dict[str, Any] | None:
    """Best-effort flat dict for coalescer logic."""
    if isinstance(msg, dict):
        body = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        return dict(body) if isinstance(body, dict) else None
    raw_type = getattr(msg, "type", None)
    if raw_type is not None:
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

        if isinstance(msg, ToolMessage):
            return {"type": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id}
        if isinstance(msg, (AIMessage, AIMessageChunk)):
            out: dict[str, Any] = {
                "type": "ai",
                "content": msg.content,
            }
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                out["tool_calls"] = msg.tool_calls
            if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
                out["tool_call_chunks"] = msg.tool_call_chunks
            phase = getattr(msg, "phase", None)
            if isinstance(phase, str):
                out["phase"] = phase
            pos = getattr(msg, "chunk_position", None)
            if pos is not None:
                out["chunk_position"] = pos
            return out
    return None


def _is_tool_wire_message(msg: Any) -> bool:
    body = _msg_to_wire_dict(msg)
    if body is None:
        return False
    raw = str(body.get("type") or "")
    if raw in _TOOL_WIRE_TYPES or raw.endswith("ToolMessage"):
        return True
    return bool(body.get("tool_call_id"))


def _wire_has_tool_invocation(body: dict[str, Any]) -> bool:
    if body.get("tool_calls") or body.get("tool_call_chunks"):
        return True
    for key in ("content", "content_blocks"):
        raw = body.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t in ("tool_call", "tool_call_chunk", "tool_use"):
                return True
            if t == "non_standard" and isinstance(item.get("value"), dict):
                inner = item["value"].get("type")
                if inner in ("tool_use", "tool_call", "tool_call_chunk"):
                    return True
    return False


def _is_ai_wire_message(msg: Any) -> bool:
    body = _msg_to_wire_dict(msg)
    if body is None:
        return False
    raw = str(body.get("type") or "")
    if raw in _AI_WIRE_TYPES or raw.endswith("AIMessageChunk"):
        return True
    return assistant_output_phase(body) is not None


def _plain_text_ai_message(msg: Any) -> bool:
    """True when message is assistant AI with no tool metadata (safe to coalesce text)."""
    if _is_tool_wire_message(msg):
        return False
    if not _is_ai_wire_message(msg):
        return False
    body = _msg_to_wire_dict(msg)
    if body is None:
        return False
    if assistant_output_phase(body) is not None:
        return False
    if _wire_has_tool_invocation(body):
        return False
    return bool(extract_text_from_ai_message(body))


def _chunk_position_last(msg: Any) -> bool:
    body = _msg_to_wire_dict(msg)
    if body is None:
        pos = getattr(msg, "chunk_position", None)
        return pos == "last"
    return body.get("chunk_position") == "last"


def _updates_has_interrupt(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    return "__interrupt__" in data


class StreamDeliveryCoalescer:
    """Shape runner stream tuples before daemon broadcast to clients.

    Supports:
    - goal_completion batching (batch / adaptive modes)
    - plain assistant text coalescing per namespace (RFC-614 / IG-426)
    - dropping noop ``updates`` tuples
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
        message_coalesce_enabled: bool = True,
        coalesce_interval_ms: int = 200,
    ) -> None:
        self._mode: StreamDeliveryMode = mode
        self._adaptive_threshold_chars = adaptive_threshold_chars
        self._file_output_threshold_chars = file_output_threshold_chars
        self._file_output_preview_chars = file_output_preview_chars
        self._file_output_dir = file_output_dir
        self._workspace = workspace
        self._message_coalesce_enabled = message_coalesce_enabled
        self._coalesce_interval_s = max(coalesce_interval_ms, 50) / 1000.0
        self._gc: _GoalCompletionBuffer | None = None
        self._text_buffers: dict[tuple[str, ...], _TextCoalesceBuffer] = {}
        self._turn_complete_pending = False
        self._effective_mode: Literal["batch", "streaming"] = "streaming"
        self._adaptive_decision_made = False
        self._coalesce_flush_count = 0

    @property
    def turn_complete_pending(self) -> bool:
        """True after ``agent_loop.completed`` was ingested (caller should signal idle)."""
        return self._turn_complete_pending

    @property
    def coalesce_flush_count(self) -> int:
        """Number of text-coalesce flushes this turn (metrics)."""
        return self._coalesce_flush_count

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
        now = time.monotonic()

        if mode == "updates":
            if _updates_has_interrupt(data):
                return [(ns, mode, data)]
            return []

        if mode == "custom" and isinstance(data, dict) and data.get("type") == AGENT_LOOP_COMPLETED:
            out = self._flush_all_text_buffers(final=True)
            out.extend(self._flush_goal_completion(final=True))
            out.append((ns, mode, data))
            self._turn_complete_pending = True
            return out

        if mode == "custom":
            out = self._flush_all_text_buffers(final=False)
            out.append((ns, mode, data))
            return out

        if mode != "messages":
            return [(ns, mode, data)]

        if not isinstance(data, (tuple, list)) or len(data) != _MSG_PAIR_LEN:
            return [(ns, mode, data)]

        msg, metadata = data[0], data[1] if len(data) > 1 else {}

        if _is_tool_wire_message(msg):
            out = self._flush_text_buffer(ns, final=False)
            out.append((ns, mode, data))
            return out

        phase = assistant_output_phase(msg)
        if phase == "goal_completion":
            out = self._flush_text_buffer(ns, final=False)
            out.extend(self._ingest_goal_completion(ns, msg, metadata))
            return out

        if not self._message_coalesce_enabled:
            return [(ns, mode, data)]

        if _wire_has_tool_invocation(_msg_to_wire_dict(msg) or {}):
            out = self._flush_text_buffer(ns, final=False)
            out.append((ns, mode, data))
            return out

        if _plain_text_ai_message(msg):
            out: list[tuple[tuple[str, ...], str, Any]] = []
            buf = self._text_buffers.get(ns)
            if buf is None:
                buf = _TextCoalesceBuffer(namespace=ns)
                self._text_buffers[ns] = buf
            body = _msg_to_wire_dict(msg)
            interval_due = False
            if body is not None:
                if buf.template_msg is None:
                    buf.template_msg = dict(body)
                    if isinstance(metadata, dict):
                        buf.template_meta = dict(metadata)
                interval_due = (
                    bool(buf.parts)
                    and buf.last_activity_monotonic > 0
                    and (now - buf.last_activity_monotonic) >= self._coalesce_interval_s
                )
                for piece in extract_text_from_ai_message(body):
                    if piece:
                        buf.parts.append(piece)
                buf.last_activity_monotonic = now
            if _chunk_position_last(msg):
                out.extend(self._flush_text_buffer(ns, final=True))
            elif interval_due:
                out.extend(self._flush_text_buffer(ns, final=False))
            return out

        out = self._flush_text_buffer(ns, final=False)
        out.append((ns, mode, data))
        return out

    def flush(self) -> list[tuple[tuple[str, ...], str, Any]]:
        """Flush any buffered text and goal-completion at stream end."""
        out = self._flush_all_text_buffers(final=True)
        out.extend(self._flush_goal_completion(final=True))
        return out

    def strip_tool_metadata_for_batch(self, wire_data: Any) -> Any:
        """Return wire message data with tool_calls/chunks removed after batch emit."""
        if not isinstance(wire_data, (tuple, list)) or len(wire_data) != _MSG_PAIR_LEN:
            return wire_data
        msg_wire = wire_data[0]
        if not isinstance(msg_wire, dict):
            return wire_data
        body = msg_wire.get("data") if isinstance(msg_wire.get("data"), dict) else msg_wire
        if not isinstance(body, dict):
            return wire_data
        if not (
            _wire_has_tool_invocation(body)
            or body.get("tool_calls")
            or body.get("tool_call_chunks")
        ):
            return wire_data
        cleaned = dict(body)
        cleaned.pop("tool_calls", None)
        cleaned.pop("tool_call_chunks", None)
        meta = wire_data[1] if len(wire_data) > 1 else {}
        if "data" in msg_wire and isinstance(msg_wire.get("data"), dict):
            outer = dict(msg_wire)
            outer["data"] = cleaned
            return (outer, meta)
        return (cleaned, meta)

    def _ingest_goal_completion(
        self,
        namespace: tuple[str, ...],
        msg: Any,
        metadata: Any,
    ) -> list[tuple[tuple[str, ...], str, Any]]:
        wire_data = prepare_stream_data_for_wire((msg, metadata))
        msg_wire = wire_data[0] if isinstance(wire_data, (tuple, list)) and wire_data else msg
        if not isinstance(msg_wire, dict):
            return [(namespace, "messages", wire_data)]

        if self._mode == "batch":
            self._accumulate_goal_completion(
                namespace, msg_wire, wire_data[1] if len(wire_data) > 1 else {}
            )
            return []

        if not self._adaptive_decision_made:
            self._accumulate_goal_completion(
                namespace, msg_wire, wire_data[1] if len(wire_data) > 1 else {}
            )
            chars = len(self._joined_gc_text())
            if chars >= self._adaptive_threshold_chars:
                self._effective_mode = "batch"
                self._adaptive_decision_made = True
                return []
            return [(namespace, "messages", wire_data)]

        self._accumulate_goal_completion(
            namespace, msg_wire, wire_data[1] if len(wire_data) > 1 else {}
        )
        return []

    def _flush_all_text_buffers(self, *, final: bool) -> list[tuple[tuple[str, ...], str, Any]]:
        out: list[tuple[tuple[str, ...], str, Any]] = []
        for ns in list(self._text_buffers.keys()):
            out.extend(self._flush_text_buffer(ns, final=final))
        return out

    def _flush_text_buffer(
        self,
        namespace: tuple[str, ...],
        *,
        final: bool,
    ) -> list[tuple[tuple[str, ...], str, Any]]:
        buf = self._text_buffers.pop(namespace, None)
        if buf is None or not buf.parts:
            return []
        text = "".join(buf.parts)
        msg = dict(buf.template_msg or {"type": "AIMessageChunk"})
        msg.setdefault("type", "AIMessageChunk")
        msg["content"] = text
        if final:
            msg["chunk_position"] = "last"
        elif "chunk_position" in msg:
            msg.pop("chunk_position", None)
        meta: dict[str, Any] = {}
        if isinstance(buf.template_meta, dict):
            meta = dict(buf.template_meta)
        self._coalesce_flush_count += 1
        wire = prepare_stream_data_for_wire((msg, meta))
        return [(namespace, "messages", wire)]

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

    def _joined_gc_text(self) -> str:
        if self._gc is None:
            return ""
        return "".join(self._gc.parts)

    def _flush_goal_completion(self, *, final: bool) -> list[tuple[tuple[str, ...], str, Any]]:
        if self._gc is None or not self._gc.parts:
            self._gc = None
            return []

        text = self._joined_gc_text()

        if self._file_output_threshold_chars > 0 and len(text) >= self._file_output_threshold_chars:
            return self._emit_file_output_message(text)

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
        """Write goal_completion to file, return path."""
        if self._file_output_dir:
            output_dir = Path(self._file_output_dir)
        elif self._workspace:
            output_dir = Path(self._workspace) / ".soothe" / "output"
        else:
            output_dir = Path.home() / ".soothe" / "output"

        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"synthesis_{timestamp}_{uuid.uuid4().hex[:8]}.md"

        file_path = output_dir / filename
        file_path.write_text(text)

        return str(file_path)


__all__ = [
    "AGENT_LOOP_COMPLETED",
    "StreamDeliveryCoalescer",
    "StreamDeliveryMode",
    "_plain_text_ai_message",
]
