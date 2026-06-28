"""Unified tool call ID generation and stream rewriting (IG-416).

This module provides functions for generating unified tool_call_ids that combine
step_id, task_idx, and tool name into a consistent format. These IDs enable
proper tracking of tool calls across root-graph and subgraph execution.

ID Format:
- Step-level: `{step_id}:s:{tool}:{idx}` (root graph tools)
- Task-level: `{step_id}:t{task_idx}:{tool}:{idx}` (subagent inner tools)
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from soothe_sdk.ux.task_namespace import (
    _format_unified_tool_call_id,
    _shorten_tool_call_id,
    _task_index_from_task_tool_call_id,
    normalize_unified_tool_call_id,
    parse_unified_tool_call_id,
)


def _make_step_tool_call_id(step_id: str, raw_tid: str, call_idx: int) -> str:
    """Generate unified step-level tool call ID.

    Format: {step_wire}:s:{tool}:{idx}

    Examples:
        ('GHT-01', 'functions.task:0', 0) → 'GHT_01:s:task:0'
        ('GHT-01', 'functions.read_file:1', 1) → 'GHT_01:s:read_file:1'
    """
    short_tid = _shorten_tool_call_id(raw_tid)
    return _format_unified_tool_call_id(step_id, "s", short_tid)


def _make_task_inner_tool_call_id(step_id: str, task_idx: int, raw_tid: str) -> str:
    """Generate unified task-level (subagent inner) tool call ID.

    Format: {step_wire}:t{task_idx}:{tool}:{idx}

    Examples:
        ('GHT-01', 0, 'functions.read_file:1') → 'GHT_01:t0:read_file:1'
        ('GHT-01', 0, 'functions.grep:2') → 'GHT_01:t0:grep:2'
    """
    short_tid = _shorten_tool_call_id(raw_tid)
    return _format_unified_tool_call_id(step_id, f"t{task_idx}", short_tid)


def _unified_tool_call_id_for_stream(
    step_id: str,
    raw_tid: str,
    *,
    task_idx: int | None,
) -> str:
    """Build step- or task-level unified tool_call_id for stream rewriting."""
    if task_idx is None:
        return _make_step_tool_call_id(step_id, raw_tid, 0)
    return _make_task_inner_tool_call_id(step_id, task_idx, raw_tid)


@dataclass
class _SubgraphNamespaceTaskBinder:
    """Map LangGraph subgraph namespaces to main-graph ``task:N`` indices."""

    _pending_indices: deque[int] = field(default_factory=deque)
    _ns_to_idx: dict[tuple[str, ...], int] = field(default_factory=dict)

    def note_main_graph_task_invocations(self, msg: BaseMessage, step_id: str) -> None:
        """Queue ``task`` indices from step-level delegations before subgraphs start."""
        if not isinstance(msg, (AIMessage, AIMessageChunk)):
            return
        sid = str(step_id).strip()
        if not sid:
            return
        seen: set[int] = set()
        for source in (
            getattr(msg, "tool_calls", None) or [],
            getattr(msg, "tool_call_chunks", None) or [],
        ):
            for tc in source:
                if not isinstance(tc, dict):
                    continue
                if str(tc.get("name") or "").strip() != "task":
                    continue
                tid = str(tc.get("id") or "").strip()
                if not tid:
                    continue
                idx = _task_index_from_task_tool_call_id(tid)
                if idx is None or idx in seen:
                    continue
                seen.add(idx)
                self._pending_indices.append(idx)

    def task_idx_for_namespace(self, namespace: tuple[str, ...]) -> int:
        """Return the ``task`` index bound to a subgraph namespace (FIFO by default)."""
        if not namespace:
            return 0
        bound = self._ns_to_idx.get(namespace)
        if bound is not None:
            return bound
        idx = self._pending_indices.popleft() if self._pending_indices else 0
        self._ns_to_idx[namespace] = idx
        return idx


def _rewrite_tool_call_ids_to_unified(
    msg: BaseMessage,
    step_id: str,
    *,
    task_idx: int | None = None,
) -> BaseMessage:
    """Rewrite tool_call_ids in AI message/chunk to unified format.

    IG-416: Transforms provider tool_call_ids like ``functions.task:0`` to
    ``{step_id}:s:{tool}`` (root) or ``{step_id}:t{idx}:{tool}`` (subgraph).

    Returns the original message if no modifications needed, or a new
    message object with rewritten IDs.
    """
    sid = str(step_id).strip()
    if not sid:
        return msg

    def _needs_unified(raw_id: str) -> bool:
        if not raw_id:
            return False
        parsed_sid, type_code, parsed_tidx, _ = parse_unified_tool_call_id(raw_id)
        if parsed_sid == sid and type_code == "s":
            return False
        if parsed_sid == sid and type_code == "t" and task_idx is not None:
            return parsed_tidx != task_idx
        return True

    needs_rewrite = False
    seen_ids: set[str] = set()

    if isinstance(msg, AIMessageChunk):
        for tc in getattr(msg, "tool_call_chunks", None) or []:
            if isinstance(tc, dict) and "id" in tc:
                raw_id = str(tc.get("id", ""))
                if raw_id and raw_id not in seen_ids:
                    seen_ids.add(raw_id)
                    if _needs_unified(raw_id):
                        needs_rewrite = True
                        break
        if not needs_rewrite:
            for tc in getattr(msg, "tool_calls", None) or []:
                if isinstance(tc, dict) and "id" in tc:
                    raw_id = str(tc.get("id", ""))
                    if raw_id and raw_id not in seen_ids:
                        seen_ids.add(raw_id)
                        if _needs_unified(raw_id):
                            needs_rewrite = True
                            break
    elif isinstance(msg, AIMessage):
        for tc in getattr(msg, "tool_calls", None) or []:
            if isinstance(tc, dict) and "id" in tc:
                raw_id = str(tc.get("id", ""))
                if raw_id and raw_id not in seen_ids:
                    seen_ids.add(raw_id)
                    if _needs_unified(raw_id):
                        needs_rewrite = True
                        break

    if not needs_rewrite:
        return msg

    modified = deepcopy(msg)

    def _unified(raw_id: str) -> str:
        parsed_sid, type_code, _, _ = parse_unified_tool_call_id(raw_id)
        if parsed_sid and type_code in ("s", "t"):
            return normalize_unified_tool_call_id(raw_id)
        return _unified_tool_call_id_for_stream(sid, raw_id, task_idx=task_idx)

    if isinstance(modified, AIMessageChunk):
        new_chunks = []
        for tc in getattr(modified, "tool_call_chunks", None) or []:
            if isinstance(tc, dict):
                new_tc = dict(tc)
                raw_id = str(tc.get("id", ""))
                if raw_id:
                    new_tc["id"] = _unified(raw_id)
                new_chunks.append(new_tc)
        if hasattr(modified, "tool_call_chunks") and new_chunks:
            if hasattr(modified, "__dict__"):
                modified.__dict__["tool_call_chunks"] = new_chunks

        new_calls = []
        for tc in getattr(modified, "tool_calls", None) or []:
            if isinstance(tc, dict):
                new_tc = dict(tc)
                raw_id = str(tc.get("id", ""))
                if raw_id:
                    new_tc["id"] = _unified(raw_id)
                new_calls.append(new_tc)
        if hasattr(modified, "tool_calls") and new_calls:
            if hasattr(modified, "__dict__"):
                modified.__dict__["tool_calls"] = new_calls

    elif isinstance(modified, AIMessage):
        new_calls = []
        for tc in getattr(modified, "tool_calls", None) or []:
            if isinstance(tc, dict):
                new_tc = dict(tc)
                raw_id = str(tc.get("id", ""))
                if raw_id:
                    new_tc["id"] = _unified(raw_id)
                new_calls.append(new_tc)
        if hasattr(modified, "__dict__"):
            modified.__dict__["tool_calls"] = new_calls

    return modified


def _rewrite_tool_message_tool_call_id(
    msg: BaseMessage,
    step_id: str,
    *,
    task_idx: int | None = None,
) -> BaseMessage:
    """Align ``ToolMessage.tool_call_id`` with unified AIMessage ids (IG-416).

    Args:
        msg: Stream message (typically ``ToolMessage``).
        step_id: Current execute step id.
        task_idx: When set, use task-level ``{step_id}:t{idx}:…`` ids (subgraph).

    Returns:
        Original message when unchanged, or a shallow-copied ``ToolMessage``.
    """
    if not isinstance(msg, ToolMessage):
        return msg
    sid = str(step_id).strip()
    if not sid:
        return msg
    raw_id = str(getattr(msg, "tool_call_id", "") or "").strip()
    if not raw_id:
        return msg
    parsed_sid, type_code, _, _ = parse_unified_tool_call_id(raw_id)
    if parsed_sid and type_code in ("s", "t"):
        return msg
    unified = _unified_tool_call_id_for_stream(sid, raw_id, task_idx=task_idx)
    return msg.model_copy(update={"tool_call_id": unified})


def _extract_tool_name_from_ai_chunk(msg: BaseMessage, tool_call_id: str) -> str:
    """Extract tool name for a specific tool_call_id from AI message/chunk.

    Args:
        msg: AIMessage or AIMessageChunk containing tool call info.
        tool_call_id: The tool_call_id to extract info for.

    Returns:
        Tool name string, or empty string if not found.
    """
    tool_name: str = ""

    if isinstance(msg, AIMessageChunk):
        # Check tool_call_chunks first (streaming)
        for tc in getattr(msg, "tool_call_chunks", None) or []:
            if not isinstance(tc, dict):
                continue
            tid = tc.get("id")
            if isinstance(tid, str) and tid.strip() == tool_call_id:
                tool_name = str(tc.get("name", "") or "").strip()
                break
        # Fallback to tool_calls if not found in chunks
        if not tool_name:
            for tc in getattr(msg, "tool_calls", None) or []:
                if not isinstance(tc, dict):
                    continue
                tid = tc.get("id")
                if isinstance(tid, str) and tid.strip() == tool_call_id:
                    tool_name = str(tc.get("name", "") or "").strip()
                    break
    elif isinstance(msg, AIMessage):
        for tc in getattr(msg, "tool_calls", None) or []:
            if not isinstance(tc, dict):
                continue
            tid = tc.get("id")
            if isinstance(tid, str) and tid.strip() == tool_call_id:
                tool_name = str(tc.get("name", "") or "").strip()
                break

    return tool_name


__all__ = [
    "_extract_tool_name_from_ai_chunk",
    "_make_step_tool_call_id",
    "_make_task_inner_tool_call_id",
    "_rewrite_tool_call_ids_to_unified",
    "_rewrite_tool_message_tool_call_id",
    "_SubgraphNamespaceTaskBinder",
    "_unified_tool_call_id_for_stream",
]
