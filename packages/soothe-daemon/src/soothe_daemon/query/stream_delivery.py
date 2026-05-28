"""Daemon-side stream delivery shaping for loop event broadcast (RFC-614).

Three goal_completion delivery modes (IG-441):

- ``batch``: Buffer entire goal_completion synthesis, emit one ``AIMessageChunk``
  with ``chunk_position="last"`` at ``agent_loop.completed``. No real-time
  visibility — intended for headless automation.

- ``adaptive`` (default): Two-phase streaming.

  1. *Streaming phase* — every goal_completion chunk is forwarded individually
     until cumulative emitted chars reach ``adaptive_threshold_chars``.
  2. *Chunked-streaming phase* — once threshold crossed the coalescer
     buffers further chunks and emits intermediate ``AIMessageChunk`` blocks
     when either ``adaptive_block_chars`` of text or ``adaptive_block_interval_s``
     elapse since the last block. The final block at ``agent_loop.completed``
     carries ``chunk_position="last"``. Each block reuses the same
     ``phase="goal_completion"`` tag so the TUI continues appending to the same
     ``AssistantMessage`` card (see IG-440 for chunk identity preservation).

- ``streaming``: Raw passthrough at the LLM's native generation speed. Every
  goal_completion chunk is forwarded immediately with no buffering. Highest
  wire-frame count, lowest latency, best for local/low-latency clients that
  want token-level fidelity (debugging, inline rendering experiments).

When ``file_output_threshold_chars`` > 0 the goal_completion path stays in
pure-batch buffering regardless of mode/phase so the final file_output
decision sees the complete text.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from soothe.core.events.visibility import is_custom_stream_payload_client_visible
from soothe.foundation import extract_text_from_ai_message
from soothe_sdk.client.wire import prepare_stream_data_for_wire
from soothe_sdk.core.events import AGENT_LOOP_COMPLETED
from soothe_sdk.ux.loop_stream import assistant_output_phase
from soothe_sdk.ux.stream_tool_wire import (
    TOOL_CALL_UPDATES_BATCH,
    extract_tool_call_updates_from_wire_message,
)

StreamDeliveryMode = Literal["batch", "adaptive", "streaming"]


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


@dataclass
class _ToolBatchBuffer:
    """Debounced accumulator for ``tool_call_updates_batch`` per namespace."""

    namespace: tuple[str, ...]
    updates: list[dict[str, Any]] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
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
        adaptive_threshold_chars: int = 1000,
        adaptive_block_chars: int = 500,
        adaptive_block_interval_ms: int = 250,
        file_output_threshold_chars: int = 0,
        file_output_preview_chars: int = 500,
        file_output_dir: str | None = None,
        workspace: str | None = None,
        message_coalesce_enabled: bool = True,
        coalesce_interval_ms: int = 200,
        tool_batch_enabled: bool = True,
        tool_batch_interval_ms: int = 200,
        suppress_redundant_stream_tool_updates: bool = True,
        skip_redundant_tool_message_wire: bool = False,
    ) -> None:
        self._mode: StreamDeliveryMode = mode
        self._adaptive_threshold_chars = adaptive_threshold_chars
        # IG-441: chunked-streaming phase 2 controls
        self._adaptive_block_chars = max(adaptive_block_chars, 1)
        self._adaptive_block_interval_s = max(adaptive_block_interval_ms, 50) / 1000.0
        self._file_output_threshold_chars = file_output_threshold_chars
        self._file_output_preview_chars = file_output_preview_chars
        self._file_output_dir = file_output_dir
        self._workspace = workspace
        self._message_coalesce_enabled = message_coalesce_enabled
        self._coalesce_interval_s = max(coalesce_interval_ms, 50) / 1000.0
        self._tool_batch_enabled = tool_batch_enabled
        self._tool_batch_interval_s = max(tool_batch_interval_ms, 50) / 1000.0
        self._suppress_redundant_stream_tool_updates = suppress_redundant_stream_tool_updates
        self._skip_redundant_tool_message_wire = skip_redundant_tool_message_wire
        self._gc: _GoalCompletionBuffer | None = None
        self._text_buffers: dict[tuple[str, ...], _TextCoalesceBuffer] = {}
        self._tool_batches: dict[tuple[str, ...], _ToolBatchBuffer] = {}
        self._turn_complete_pending = False
        # IG-441: per-turn phase tracker for goal_completion delivery.
        # - ``streaming`` → individual chunk passthrough (mode ``streaming`` stays here
        #   forever; mode ``adaptive`` starts here and transitions on threshold).
        # - ``chunked_streaming`` → block flushes (mode ``adaptive`` after threshold).
        # - ``batch`` → buffer everything, single shot at final flush (mode ``batch``
        #   or when file_output overrides the active mode).
        self._gc_phase: Literal["streaming", "chunked_streaming", "batch"] = (
            "batch" if mode == "batch" else "streaming"
        )
        self._coalesce_flush_count = 0
        self._gc_block_flush_count = 0
        # Track cumulative streamed goal_completion chars to detect threshold crossing
        self._gc_streamed_chars: int = 0
        # Last monotonic time we emitted a chunked-streaming block (for interval flush)
        self._gc_last_block_monotonic: float = 0.0

    @property
    def turn_complete_pending(self) -> bool:
        """True after ``agent_loop.completed`` was ingested (caller should signal idle)."""
        return self._turn_complete_pending

    @property
    def coalesce_flush_count(self) -> int:
        """Number of text-coalesce flushes this turn (metrics)."""
        return self._coalesce_flush_count

    @property
    def goal_completion_block_flush_count(self) -> int:
        """Number of intermediate goal_completion block flushes this turn (IG-441)."""
        return self._gc_block_flush_count

    @property
    def goal_completion_phase(self) -> Literal["streaming", "chunked_streaming", "batch"]:
        """Current adaptive goal_completion phase (IG-441; for diagnostics/tests)."""
        return self._gc_phase

    def consume_turn_complete_pending(self) -> bool:
        """Return and clear the turn-complete flag."""
        pending = self._turn_complete_pending
        self._turn_complete_pending = False
        return pending

    def should_skip_tool_message_wire(self, msg: Any) -> bool:
        """Return True when an empty tool result wire frame adds no client value."""
        if not self._skip_redundant_tool_message_wire:
            return False
        body = _msg_to_wire_dict(msg)
        if body is None:
            return False
        content = body.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            text = "".join(parts).strip()
        else:
            text = str(content or "").strip()
        return not text

    def ingest(
        self,
        namespace: tuple[str, ...] | list[str],
        mode: str,
        data: Any,
    ) -> list[tuple[tuple[str, ...], str, Any]]:
        """Return zero or more stream tuples to broadcast for this ingested chunk."""
        ns = tuple(namespace) if namespace else ()
        now = time.monotonic()
        out_prefix = self._flush_due_tool_batches(now)
        # IG-441: time-based block flush in adaptive chunked-streaming phase
        out_prefix.extend(self._maybe_flush_goal_completion_block(now))

        if mode == "updates":
            if _updates_has_interrupt(data):
                return out_prefix + [(ns, mode, data)]
            return out_prefix

        if mode == "custom" and isinstance(data, dict) and data.get("type") == AGENT_LOOP_COMPLETED:
            out = self._flush_all_text_buffers(final=True)
            out.extend(self._flush_goal_completion(final=True))
            out.append((ns, mode, data))
            self._turn_complete_pending = True
            return out_prefix + out

        if mode == "custom":
            if isinstance(data, dict) and not is_custom_stream_payload_client_visible(data):
                return out_prefix + self._maybe_flush_tool_batch(ns, now, force=False)
            if (
                self._suppress_redundant_stream_tool_updates
                and isinstance(data, dict)
                and self._should_suppress_stream_tool_update(ns, data)
            ):
                out = self._flush_all_text_buffers(final=False)
                out.extend(self._maybe_flush_tool_batch(ns, now, force=False))
                return out_prefix + out
            out = self._flush_all_text_buffers(final=False)
            out.extend(self._maybe_flush_tool_batch(ns, now, force=False))
            out.append((ns, mode, data))
            return out_prefix + out

        if mode != "messages":
            return out_prefix + [(ns, mode, data)]

        if not isinstance(data, (tuple, list)) or len(data) != _MSG_PAIR_LEN:
            return out_prefix + [(ns, mode, data)]

        msg, metadata = data[0], data[1] if len(data) > 1 else {}

        if _is_tool_wire_message(msg):
            out = self._flush_text_buffer(ns, final=False)
            out.extend(self._flush_tool_batch(ns, force=True))
            if not self.should_skip_tool_message_wire(msg):
                out.append((ns, mode, data))
            return out_prefix + out

        phase = assistant_output_phase(msg)
        if phase == "goal_completion":
            out = self._flush_text_buffer(ns, final=False)
            out.extend(self._ingest_goal_completion(ns, msg, metadata))
            return out_prefix + out

        if not self._message_coalesce_enabled:
            return out_prefix + [(ns, mode, data)]

        if _wire_has_tool_invocation(_msg_to_wire_dict(msg) or {}):
            out = self._flush_text_buffer(ns, final=False)
            wire_data = prepare_stream_data_for_wire((msg, metadata))
            msg_wire = wire_data[0] if isinstance(wire_data, (tuple, list)) and wire_data else None
            if isinstance(msg_wire, dict):
                tool_updates = list(extract_tool_call_updates_from_wire_message(msg_wire))
                if tool_updates and self._tool_batch_enabled:
                    self._accumulate_tool_batch(ns, tool_updates, now)
                    wire_data = self.strip_tool_metadata_for_batch(wire_data)
                    out.extend(self._maybe_flush_tool_batch(ns, now, force=False))
                    body = wire_data[0] if wire_data else None
                    if isinstance(body, dict):
                        from soothe_sdk.client.wire import flatten_enveloped_message_dict

                        flat = flatten_enveloped_message_dict(body)
                        text = "".join(extract_text_from_ai_message(flat)).strip()
                        has_phase = bool(flat.get("phase"))
                        if text or has_phase:
                            out.append((ns, mode, wire_data))
                    return out_prefix + out
            out.append((ns, mode, data))
            return out_prefix + out

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
            return out_prefix + out

        out = self._flush_text_buffer(ns, final=False)
        out.append((ns, mode, data))
        return out_prefix + out

    def _flush_due_tool_batches(self, now: float) -> list[tuple[tuple[str, ...], str, Any]]:
        out: list[tuple[tuple[str, ...], str, Any]] = []
        for ns in list(self._tool_batches.keys()):
            out.extend(self._maybe_flush_tool_batch(ns, now, force=False))
        return out

    def flush(self) -> list[tuple[tuple[str, ...], str, Any]]:
        """Flush any buffered text and goal-completion at stream end."""
        out = self._flush_all_text_buffers(final=True)
        out.extend(self._flush_all_tool_batches(force=True))
        out.extend(self._flush_goal_completion(final=True))
        return out

    def _accumulate_tool_batch(
        self,
        namespace: tuple[str, ...],
        updates: list[dict[str, Any]],
        now: float,
    ) -> None:
        buf = self._tool_batches.get(namespace)
        if buf is None:
            buf = _ToolBatchBuffer(namespace=namespace)
            self._tool_batches[namespace] = buf
        for upd in updates:
            if not isinstance(upd, dict):
                continue
            tid = str(upd.get("tool_call_id") or "").strip()
            if tid and tid in buf.seen_ids:
                continue
            if tid:
                buf.seen_ids.add(tid)
            buf.updates.append(upd)
        buf.last_activity_monotonic = now

    def _should_suppress_stream_tool_update(
        self,
        namespace: tuple[str, ...],
        data: dict[str, Any],
    ) -> bool:
        from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

        if str(data.get("type", "")) != STREAM_TOOL_CALL_UPDATE:
            return False
        tid = str(data.get("tool_call_id") or "").strip()
        if not tid:
            return False
        buf = self._tool_batches.get(namespace)
        if buf is None:
            return False
        return tid in buf.seen_ids

    def _maybe_flush_tool_batch(
        self,
        namespace: tuple[str, ...],
        now: float,
        *,
        force: bool,
    ) -> list[tuple[tuple[str, ...], str, Any]]:
        buf = self._tool_batches.get(namespace)
        if buf is None or not buf.updates:
            return []
        interval_due = (
            buf.last_activity_monotonic > 0
            and (now - buf.last_activity_monotonic) >= self._tool_batch_interval_s
        )
        if not force and not interval_due:
            return []
        return self._flush_tool_batch(namespace, force=True)

    def _flush_tool_batch(
        self,
        namespace: tuple[str, ...],
        *,
        force: bool,
    ) -> list[tuple[tuple[str, ...], str, Any]]:
        if not force:
            return self._maybe_flush_tool_batch(namespace, time.monotonic(), force=True)
        buf = self._tool_batches.pop(namespace, None)
        if buf is None or not buf.updates:
            return []
        return [
            (
                namespace,
                "custom",
                {
                    "type": TOOL_CALL_UPDATES_BATCH,
                    "updates": list(buf.updates),
                    "count": len(buf.updates),
                },
            )
        ]

    def _flush_all_tool_batches(self, *, force: bool) -> list[tuple[tuple[str, ...], str, Any]]:
        out: list[tuple[tuple[str, ...], str, Any]] = []
        for ns in list(self._tool_batches.keys()):
            out.extend(self._flush_tool_batch(ns, force=force))
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
        """Route a goal_completion message through the active delivery phase.

        - ``batch``: always accumulate; ``_flush_goal_completion(final=True)``
          emits a single message at agent_loop.completed.
        - ``streaming``: passthrough each chunk; track cumulative chars and
          transition to ``chunked_streaming`` once ``adaptive_threshold_chars``
          is reached.
        - ``chunked_streaming``: accumulate into the goal_completion buffer
          and flush intermediate blocks when char or time thresholds are met
          (IG-441).
        """
        wire_data = prepare_stream_data_for_wire((msg, metadata))
        msg_wire = wire_data[0] if isinstance(wire_data, (tuple, list)) and wire_data else msg
        if not isinstance(msg_wire, dict):
            return [(namespace, "messages", wire_data)]

        meta = wire_data[1] if isinstance(wire_data, (tuple, list)) and len(wire_data) > 1 else {}

        # file_output is incompatible with any streaming variant: we need to see
        # total chars at final flush to decide between file vs. wire delivery.
        # Force pure-batch buffering whenever file_output is enabled.
        if self._mode == "batch" or self._file_output_threshold_chars > 0:
            self._accumulate_goal_completion(namespace, msg_wire, meta)
            return []

        # Mode "streaming" is raw passthrough at the LLM's native rate — no
        # buffering, no threshold-based transition, never enters
        # chunked_streaming. The phase tracker stays in "streaming" forever.
        if self._mode == "streaming":
            return [(namespace, "messages", wire_data)]

        chunk_chars = len("".join(extract_text_from_ai_message(msg_wire)))

        if self._gc_phase == "streaming":
            projected_chars = (
                self._gc_streamed_chars
                + (len(self._joined_gc_text()) if self._gc else 0)
                + chunk_chars
            )
            if projected_chars < self._adaptive_threshold_chars:
                # Phase 1: low-latency passthrough.
                self._gc_streamed_chars += chunk_chars
                return [(namespace, "messages", wire_data)]
            # Threshold crossed → enter chunked-streaming phase. Buffer this
            # chunk and let the threshold check below decide whether to flush
            # immediately as the first block.
            self._gc_phase = "chunked_streaming"
            self._gc_last_block_monotonic = time.monotonic()

        # Phase 2: chunked-streaming. Accumulate and flush blocks on demand.
        self._accumulate_goal_completion(namespace, msg_wire, meta)
        return self._maybe_flush_goal_completion_block(time.monotonic())

    def _maybe_flush_goal_completion_block(
        self, now: float
    ) -> list[tuple[tuple[str, ...], str, Any]]:
        """Emit an intermediate goal_completion block if size or time threshold met.

        Called from ``_ingest_goal_completion`` and from periodic ingest entry to
        ensure long synthesis streams emit visible progress at least every
        ``adaptive_block_interval_s`` seconds without crossing
        ``adaptive_block_chars`` characters.
        """
        if self._gc_phase != "chunked_streaming":
            return []
        if self._gc is None or not self._gc.parts:
            return []
        size_due = self._gc.char_count >= self._adaptive_block_chars
        time_due = (
            self._gc_last_block_monotonic > 0.0
            and (now - self._gc_last_block_monotonic) >= self._adaptive_block_interval_s
        )
        if not (size_due or time_due):
            return []
        return self._emit_goal_completion_block(now, final=False)

    def _emit_goal_completion_block(
        self, now: float, *, final: bool
    ) -> list[tuple[tuple[str, ...], str, Any]]:
        """Flush the goal_completion buffer as an intermediate or final block.

        Each block keeps the same ``phase="goal_completion"`` tag so the TUI
        appends it onto the same ``AssistantMessage`` card (IG-440). Only the
        final block carries ``chunk_position="last"``.
        """
        if self._gc is None or not self._gc.parts:
            return []
        text = self._joined_gc_text()
        namespace = self._gc.namespace
        template_msg = dict(self._gc.template_msg or {})
        template_meta = dict(self._gc.template_meta or {})

        # Reset buffer text but keep template + namespace for further blocks.
        self._gc.parts = []
        self._gc.char_count = 0
        self._gc_last_block_monotonic = now
        if not final:
            self._gc_block_flush_count += 1

        msg = dict(template_msg)
        msg.setdefault("type", "AIMessageChunk")
        msg["content"] = text
        msg["phase"] = "goal_completion"
        if final:
            msg["chunk_position"] = "last"
        else:
            msg.pop("chunk_position", None)

        wire = prepare_stream_data_for_wire((msg, template_meta))
        if final:
            # Final flush clears the buffer entirely.
            self._gc = None
            self._gc_streamed_chars = 0
            self._gc_phase = "batch" if self._mode == "batch" else "streaming"
        return [(namespace, "messages", wire)]

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
        """Flush remaining buffered goal_completion text.

        Called at stream end (``flush``) and on ``agent_loop.completed``. The
        text may be empty if the entire synthesis was already streamed (pure
        adaptive streaming phase) or if the chunked-streaming blocks emptied
        the buffer between block flushes. file_output_threshold short-circuits
        to a file-summary message regardless of phase.
        """
        if self._gc is None or not self._gc.parts:
            emit_terminal_marker = (
                final
                and self._gc is not None
                and self._gc_phase == "chunked_streaming"
                and self._gc_block_flush_count > 0
            )
            terminal: list[tuple[tuple[str, ...], str, Any]] = []
            if emit_terminal_marker:
                terminal = self._emit_goal_completion_terminal_marker()
            self._gc = None
            self._gc_streamed_chars = 0
            self._gc_phase = "batch" if self._mode == "batch" else "streaming"
            self._gc_last_block_monotonic = 0.0
            return terminal

        text = self._joined_gc_text()

        if self._file_output_threshold_chars > 0 and len(text) >= self._file_output_threshold_chars:
            return self._emit_file_output_message(text)

        return self._emit_goal_completion_block(time.monotonic(), final=final)

    def _emit_goal_completion_terminal_marker(self) -> list[tuple[tuple[str, ...], str, Any]]:
        """Emit a final ``chunk_position=last`` marker when buffered text is empty.

        In adaptive chunked-streaming, a large one-shot message can emit an
        intermediate block and leave the goal_completion buffer empty before
        ``agent_loop.completed`` arrives. Clients still need a terminal marker
        to finalize streaming state.
        """
        if self._gc is None:
            return []
        namespace = self._gc.namespace
        msg = dict(self._gc.template_msg or {})
        msg.setdefault("type", "AIMessageChunk")
        msg["phase"] = "goal_completion"
        msg["content"] = ""
        msg["chunk_position"] = "last"
        meta = dict(self._gc.template_meta or {})
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
        # Reset adaptive streaming counter and phase when buffer cleared
        self._gc_streamed_chars = 0
        self._gc_phase = "batch" if self._mode == "batch" else "streaming"
        self._gc_last_block_monotonic = 0.0
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
