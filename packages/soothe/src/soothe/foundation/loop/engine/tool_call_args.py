"""Collect and wire tool-call kwargs during Act-phase streaming.

Two sources are merged into one lookup table keyed by provider and unified ids:

1. **Invocation registry** (middleware) — authoritative for main-graph Kimi-style runs
   that stream ``ToolMessage`` without ``AIMessage`` tool metadata.
2. **Stream AI messages** — ``tool_calls`` / ``tool_call_chunks`` when the model emits them
   (subagents and providers that stream tool metadata).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

from soothe.foundation.loop.engine.tool_call_id import (
    _rewrite_tool_message_tool_call_id,
    _unified_tool_call_id_for_stream,
)
from soothe.middleware.tool_call_args_registry import (
    coerce_tool_call_args,
    get_recorded_tool_call_args,
)
from soothe.utils.text_preview import log_preview

logger = logging.getLogger(__name__)


def _chunk_args_dict(chunk: dict[str, Any]) -> dict[str, Any]:
    """Extract parsed args from one ``tool_call_chunk`` block."""
    cargs = chunk.get("args")
    if isinstance(cargs, dict) and cargs:
        return dict(cargs)
    if isinstance(cargs, str) and cargs.strip():
        return coerce_tool_call_args(cargs)
    return {}


def _store(
    dest: dict[str, dict[str, Any]],
    tool_call_id: str,
    args: dict[str, Any],
    *,
    aliases: tuple[str, ...] = (),
) -> None:
    """Store kwargs under ``tool_call_id`` and optional alias ids (later writes win)."""
    key = str(tool_call_id or "").strip()
    if not key or not args:
        return
    payload = dict(args)
    dest[key] = payload
    for alias in aliases:
        aid = str(alias or "").strip()
        if aid:
            dest[aid] = dict(payload)


def _predict_unified_id(
    step_id: str,
    *,
    raw_tool_call_id: str = "",
    tool_name: str = "",
    chunk_index: Any = None,
    task_idx: int | None = None,
) -> str:
    """Map provider ids or chunk index+name to unified wire ``tool_call_id``."""
    sid = str(step_id).strip()
    if not sid:
        return str(raw_tool_call_id or "").strip()
    raw_tid = str(raw_tool_call_id or "").strip()
    if not raw_tid:
        name = str(tool_name or "").strip()
        if name and chunk_index is not None:
            try:
                idx = int(chunk_index)
            except (TypeError, ValueError):
                idx = None
            if idx is not None:
                raw_tid = f"{name}:{idx}"
    if not raw_tid:
        return ""
    return _unified_tool_call_id_for_stream(sid, raw_tid, task_idx=task_idx)


def _record_from_ai_message(
    msg: BaseMessage,
    dest: dict[str, dict[str, Any]],
    *,
    step_id: str = "",
    task_idx: int | None = None,
) -> None:
    """Merge tool kwargs from an AI message into *dest* (stream path)."""
    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return

    from soothe.foundation.loop.engine.tool_call_enrichment import (
        _backfill_tool_calls_args_from_chunks,
    )

    filled = _backfill_tool_calls_args_from_chunks(msg)
    sid = str(step_id).strip()
    for tc in getattr(filled, "tool_calls", None) or []:
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id") or "").strip()
        args = coerce_tool_call_args(tc.get("args"))
        if not args:
            continue
        aliases: list[str] = []
        if sid and tid:
            unified = _predict_unified_id(sid, raw_tool_call_id=tid, task_idx=task_idx)
            if unified and unified != tid:
                aliases.append(unified)
        _store(dest, tid, args, aliases=tuple(aliases))
    for ch in getattr(filled, "tool_call_chunks", None) or []:
        if not isinstance(ch, dict):
            continue
        tid = str(ch.get("id") or "").strip()
        args = _chunk_args_dict(ch)
        if not args:
            continue
        name = str(ch.get("name") or "").strip()
        aliases: list[str] = []
        if sid:
            unified = _predict_unified_id(
                sid,
                raw_tool_call_id=tid,
                tool_name=name,
                chunk_index=ch.get("index"),
                task_idx=task_idx,
            )
            if unified:
                if not tid:
                    tid = unified
                elif unified != tid:
                    aliases.append(unified)
        if tid:
            _store(dest, tid, args, aliases=tuple(aliases))


def _stream_update_has_displayable_args(args: Any) -> bool:
    """True when wire kwargs are real invocation parameters (not placeholders)."""
    if not isinstance(args, dict) or not args:
        return False
    if args.get("_subgraph_tool") is True:
        from soothe_sdk.display.message_processing import extract_tool_args_dict

        remainder = {k: v for k, v in args.items() if k != "_subgraph_tool"}
        return bool(extract_tool_args_dict(remainder))
    return True


def filter_redundant_stream_tool_updates(
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop stream tool updates when every entry already has complete invocation args.

    Daemon ``tool_call_updates_batch`` carries the same kwargs; keep partial-arg updates
    for providers that stream tool JSON incrementally.

    Task delegations and ``_subgraph_tool`` placeholders are never treated as complete —
    the TUI needs those wire events for subagent card labels and later arg hydration.
    """
    if not updates:
        return []
    for upd in updates:
        if not isinstance(upd, dict):
            return updates
        if str(upd.get("name") or "").strip() == "task":
            return updates
        args = upd.get("args")
        if not _stream_update_has_displayable_args(args):
            return updates
    return []


def wire_updates_from_ai_message(msg: BaseMessage) -> list[dict[str, Any]]:
    """Build ``soothe.stream.tool_call.update`` payloads from a post-backfill AI message."""
    from soothe_sdk.ux.stream_tool_wire import (
        tool_call_update_event,
        unified_tool_update_allowed_without_args,
    )

    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(tid: str, name: str, args: dict[str, Any]) -> None:
        key = tid.strip()
        if not key or key in seen:
            return
        if not args and not unified_tool_update_allowed_without_args(key):
            return
        seen.add(key)
        out.append(
            tool_call_update_event(
                tool_call_id=key,
                name=name.strip() or "tool",
                args=dict(args or {}),
            )
        )

    for tc in getattr(msg, "tool_calls", None) or []:
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id") or "").strip()
        name = str(tc.get("name") or "").strip()
        if not tid or not name:
            continue
        args = coerce_tool_call_args(tc.get("args"))
        _append(tid, name, args)

    for ch in getattr(msg, "tool_call_chunks", None) or []:
        if not isinstance(ch, dict):
            continue
        tid = str(ch.get("id") or "").strip()
        name = str(ch.get("name") or "").strip()
        if not tid or not name or tid in seen:
            continue
        args = _chunk_args_dict(ch)
        _append(tid, name, args)

    return out


def format_args_for_log(args: dict[str, Any], *, max_chars: int = 500) -> str:
    """Serialize tool kwargs for debug logs (truncated)."""
    if not args:
        return "{}"
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(args)
    return log_preview(text, chars=max_chars)


@dataclass
class ToolCallArgsCollector:
    """Per Act-wave accumulator: provider + unified id → tool kwargs."""

    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup(self, tool_call_id: str) -> dict[str, Any]:
        """Return kwargs for a provider or unified ``tool_call_id``."""
        key = str(tool_call_id or "").strip()
        if not key:
            return {}
        stored = self.by_id.get(key)
        return dict(stored) if isinstance(stored, dict) else {}

    def ingest_invocation_registry(self, provider_tool_call_id: str) -> dict[str, Any]:
        """Copy kwargs from middleware invocation capture (provider id)."""
        args = get_recorded_tool_call_args(provider_tool_call_id)
        if args:
            _store(self.by_id, provider_tool_call_id, args)
        return args

    def record_ai_pair(
        self,
        before_rewrite: BaseMessage,
        after_rewrite: BaseMessage,
        *,
        step_id: str = "",
        task_idx: int | None = None,
    ) -> None:
        """Record kwargs from pre- and post-id-rewrite AI messages (stream path)."""
        _record_from_ai_message(before_rewrite, self.by_id, step_id=step_id, task_idx=task_idx)
        _record_from_ai_message(after_rewrite, self.by_id, step_id=step_id, task_idx=task_idx)

    def promote_tool_message(
        self,
        msg: ToolMessage,
        *,
        step_id: str,
        task_idx: int | None = None,
    ) -> tuple[ToolMessage, list[dict[str, Any]]]:
        """Rewrite ``tool_call_id``, merge invocation args, return wire update events."""
        from soothe_sdk.ux.stream_tool_wire import tool_call_update_event

        raw_tcid = str(getattr(msg, "tool_call_id", "") or "").strip()
        self.ingest_invocation_registry(raw_tcid)

        modified = _rewrite_tool_message_tool_call_id(msg, step_id, task_idx=task_idx)
        unified_tcid = str(getattr(modified, "tool_call_id", "") or "").strip()
        if self.lookup(raw_tcid) and unified_tcid:
            _store(self.by_id, unified_tcid, self.lookup(raw_tcid))

        wire_events: list[dict[str, Any]] = []
        args = self.lookup(unified_tcid)
        if unified_tcid and args:
            tname = str(getattr(modified, "name", "") or "").strip() or "tool"
            wire_events.append(
                tool_call_update_event(
                    tool_call_id=unified_tcid,
                    name=tname,
                    args=dict(args),
                )
            )
        return modified, wire_events

    def subgraph_placeholder_update(
        self,
        tool_call_id: str,
        tool_name: str,
    ) -> dict[str, Any] | None:
        """Subagent wire update: real args when known, else ``_subgraph_tool`` placeholder."""
        from soothe_sdk.ux.stream_tool_wire import tool_call_update_event
        from soothe_sdk.ux.task_namespace import is_unified_tool_call_id

        tcid = str(tool_call_id or "").strip()
        tname = str(tool_name or "").strip() or "unknown"
        if not tcid or tname == "task" or not is_unified_tool_call_id(tcid):
            return None
        args = dict(self.lookup(tcid) or {})
        if not args:
            args = {"_subgraph_tool": True}
        return tool_call_update_event(tool_call_id=tcid, name=tname, args=args)


__all__ = [
    "ToolCallArgsCollector",
    "format_args_for_log",
    "filter_redundant_stream_tool_updates",
    "wire_updates_from_ai_message",
]
