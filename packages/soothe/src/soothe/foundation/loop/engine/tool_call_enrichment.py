"""Tool call argument enrichment and normalization (IG-416, IG-449).

This module provides functions for processing tool call arguments during
streaming: normalizing raw args to dict, backfilling empty args from chunks,
enriching task kwargs with descriptions, and ensuring JSON string format.

Used by executor.py for stream processing and by tool_call_args.py for
argument collection during Act-phase streaming.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

_TASK_KWARG_DESC_KEYS = ("description", "prompt", "task", "instruction")


def _coerce_tool_call_args_mapping(raw: Any) -> dict[str, Any]:
    """Normalize tool-call ``args`` to a dict when possible."""
    if isinstance(raw, dict):
        inp = raw.get("input")
        if isinstance(inp, dict) and inp:
            return dict(inp)
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass
    return {}


def _task_kwargs_have_description(args: dict[str, Any]) -> bool:
    for key in _TASK_KWARG_DESC_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return True
    return False


def _chunk_args_dict(chunk: dict[str, Any]) -> dict[str, Any]:
    """Extract parsed args from one ``tool_call_chunk`` block."""
    cargs = chunk.get("args")
    if isinstance(cargs, dict) and cargs:
        return dict(cargs)
    if isinstance(cargs, str) and cargs.strip():
        return _coerce_tool_call_args_mapping(cargs)
    return {}


def _backfill_tool_calls_args_from_chunks(msg: BaseMessage) -> BaseMessage:
    """Fill empty ``tool_calls[].args`` from ``tool_call_chunks`` on the same message.

    Some providers emit a terminal ``AIMessage`` whose ``tool_calls`` have ``{}`` while
    the accumulated chunk args on the same object are complete. The TUI needs those
    kwargs on ``tool_calls`` for wire deserialization and overlay seeding.
    """
    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return msg
    chunks = getattr(msg, "tool_call_chunks", None) or []
    calls = getattr(msg, "tool_calls", None) or []
    if not chunks or not calls:
        return msg

    args_by_id: dict[str, dict[str, Any]] = {}
    args_by_index: dict[int, dict[str, Any]] = {}
    for tc in chunks:
        if not isinstance(tc, dict):
            continue
        parsed = _chunk_args_dict(tc)
        if not parsed:
            continue
        tid = str(tc.get("id") or "").strip()
        if tid:
            args_by_id[tid] = parsed
        idx_raw = tc.get("index")
        if idx_raw is not None:
            try:
                args_by_index[int(idx_raw)] = parsed
            except (TypeError, ValueError):
                pass

    if not args_by_id and not args_by_index:
        return msg

    changed = False
    new_calls: list[dict[str, Any]] = []
    for call_idx, tc in enumerate(calls):
        if not isinstance(tc, dict):
            new_calls.append(tc)
            continue
        tid = str(tc.get("id") or "").strip()
        existing_args = tc.get("args")
        empty = existing_args is None or existing_args == {} or existing_args == ""
        fill: dict[str, Any] | None = None
        if empty and tid and tid in args_by_id:
            fill = args_by_id[tid]
        elif empty and call_idx in args_by_index:
            fill = args_by_index[call_idx]
        if fill is not None:
            patched = dict(tc)
            patched["args"] = fill
            new_calls.append(patched)
            changed = True
        else:
            new_calls.append(tc)

    if not changed:
        return msg
    modified = deepcopy(msg)
    if hasattr(modified, "__dict__"):
        modified.__dict__["tool_calls"] = new_calls
    return modified


def _patch_task_tool_call_dict(
    tc: dict[str, Any],
    *,
    step_description: str,
    step_subagent: str | None,
) -> tuple[dict[str, Any], bool]:
    """Fill missing ``task`` kwargs from execute-step metadata (main graph only)."""
    if str(tc.get("name") or "").strip() != "task":
        return tc, False
    args = _coerce_tool_call_args_mapping(tc.get("args"))
    desc = (step_description or "").strip()
    sub = (step_subagent or "").strip() if step_subagent else ""
    if _task_kwargs_have_description(args):
        if sub and not str(args.get("subagent_type") or "").strip():
            merged = dict(args)
            merged["subagent_type"] = sub
            patched = dict(tc)
            patched["args"] = merged
            return patched, True
        return tc, False
    if not desc and not sub:
        return tc, False
    merged = dict(args)
    if desc:
        merged.setdefault("description", desc)
    if sub:
        merged.setdefault("subagent_type", sub)
    patched = dict(tc)
    patched["args"] = merged
    return patched, True


def _enrich_execute_step_task_kwargs_on_message(
    msg: BaseMessage,
    *,
    step_description: str,
    step_subagent: str | None,
    task_idx: int | None,
) -> BaseMessage:
    """Ensure main-graph ``task`` tool calls carry a description for TUI delegation cards.

    Parallel execute often streams ``tool_calls`` with empty ``args`` and no
    ``tool_call_chunks`` on the terminal chunk. The model still has the step brief in the
    HumanMessage envelope; copy wire ``preferred_subagent`` onto ``task`` kwargs when set
    at emit time so clients always receive a real delegation description.
    """
    if task_idx is not None:
        return msg
    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return msg
    desc = (step_description or "").strip()
    sub = (step_subagent or "").strip() if step_subagent else ""
    if not desc and not sub:
        return msg

    changed = False
    modified = deepcopy(msg)

    new_calls: list[Any] = []
    for tc in getattr(modified, "tool_calls", None) or []:
        if isinstance(tc, dict):
            patched, did = _patch_task_tool_call_dict(
                tc, step_description=desc, step_subagent=sub or None
            )
            new_calls.append(patched)
            changed = changed or did
        else:
            new_calls.append(tc)
    if changed and hasattr(modified, "__dict__"):
        modified.__dict__["tool_calls"] = new_calls

    new_chunks: list[Any] = []
    chunk_changed = False
    for tc in getattr(modified, "tool_call_chunks", None) or []:
        if isinstance(tc, dict):
            chunk_tc = dict(tc)
            if str(chunk_tc.get("name") or "").strip() == "task":
                inner_args = _chunk_args_dict(chunk_tc)
                if not _task_kwargs_have_description(inner_args):
                    merged = dict(inner_args)
                    if desc:
                        merged.setdefault("description", desc)
                    if sub:
                        merged.setdefault("subagent_type", sub)
                    chunk_tc["args"] = json.dumps(merged, separators=(",", ":"))
                    chunk_changed = True
            new_chunks.append(chunk_tc)
        else:
            new_chunks.append(tc)
    if chunk_changed and hasattr(modified, "__dict__"):
        modified.__dict__["tool_call_chunks"] = new_chunks
        changed = True

    return modified if changed else msg


def _stringify_tool_call_chunk_args_on_message(msg: BaseMessage) -> BaseMessage:
    """Ensure ``tool_call_chunks[].args`` are JSON strings (LangChain wire invariant)."""
    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return msg
    chunks = getattr(msg, "tool_call_chunks", None) or []
    if not chunks:
        return msg

    changed = False
    new_chunks: list[Any] = []
    for tc in chunks:
        if not isinstance(tc, dict):
            new_chunks.append(tc)
            continue
        block = dict(tc)
        args = block.get("args")
        if isinstance(args, dict):
            block["args"] = json.dumps(args, separators=(",", ":"))
            changed = True
        new_chunks.append(block)
    if not changed:
        return msg
    modified = deepcopy(msg)
    if hasattr(modified, "__dict__"):
        modified.__dict__["tool_call_chunks"] = new_chunks
    return modified


__all__ = [
    "_backfill_tool_calls_args_from_chunks",
    "_chunk_args_dict",
    "_coerce_tool_call_args_mapping",
    "_enrich_execute_step_task_kwargs_on_message",
    "_patch_task_tool_call_dict",
    "_stringify_tool_call_chunk_args_on_message",
    "_task_kwargs_have_description",
    "_TASK_KWARG_DESC_KEYS",
]
