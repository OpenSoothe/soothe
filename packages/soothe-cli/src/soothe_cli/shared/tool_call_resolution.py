"""Canonical merge of tool-call identity and arguments for UX display.

LangChain streams the same logical tool call through several channels on one chunk:

* ``AIMessage.tool_calls`` — often the most complete structured args.
* ``content_blocks`` / list ``content`` — parallel copies that may have empty ``args``.
* Accumulated ``tool_call_chunks`` — JSON built incrementally; passed in as an overlay.

This module merges those sources once per chunk so the TUI (and future callers) do not
duplicate precedence rules across merge/backfill helpers.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from soothe_cli.shared.message_processing import (
    extract_tool_args_dict,
    normalize_tool_calls_list,
    try_parse_pending_tool_call_args,
)

logger = logging.getLogger(__name__)


def infer_tool_name_from_call_id(tool_call_id: str) -> str | None:
    """Recover a real tool name from common ``functions.<name>:<idx>`` id shapes.

    Some transports set ``name`` to the literal ``\"tool\"`` or leave it empty while
    the id still encodes the actual tool (e.g. ``functions.ls:0`` → ``ls``).

    Args:
        tool_call_id: LangChain / provider tool call id.

    Returns:
        Inferred snake_case tool name, or ``None`` if not recognized.
    """
    tid = (tool_call_id or "").strip()
    if not tid:
        return None
    prefix = "functions."
    if not tid.startswith(prefix):
        return None
    rest = tid[len(prefix) :]
    if ":" in rest:
        rest = rest.split(":", 1)[0]
    name = rest.strip()
    if not name or name == "tool":
        return None
    return name


def tool_args_meaningful(raw: Any) -> bool:
    """True if ``raw`` yields a non-empty normalized argument dict."""
    if raw is None:
        return False
    if isinstance(raw, dict):
        return bool(extract_tool_args_dict(raw))
    if isinstance(raw, str):
        return bool(raw.strip())
    return True


def _args_from_toolish_block(block: dict[str, Any]) -> dict[str, Any]:
    """Normalize args from a ``tool_call`` / ``tool_use`` / ``tool_call_chunk`` block."""
    btype = block.get("type")
    payload: dict[str, Any] = dict(block)
    if btype == "tool_use" and "args" not in block and block.get("input") is not None:
        payload = {"args": block.get("input"), "name": block.get("name"), "id": block.get("id")}
    return extract_tool_args_dict(payload)


def is_toolish_display_block(block: dict[str, Any]) -> bool:
    """True for blocks that represent a tool invocation in the UI stream."""
    return block.get("type") in (
        "tool_call",
        "tool_call_chunk",
        "tool_use",
        "non_standard",
    )


@dataclass(frozen=True, slots=True)
class ResolvedToolInvocation:
    """One tool call with merged display arguments."""

    tool_call_id: str
    name: str
    args: dict[str, Any]


def _pick_args_from_sources(
    *,
    from_streaming: dict[str, Any],
    from_tool_call_attr: dict[str, Any],
    from_block: dict[str, Any],
) -> dict[str, Any]:
    """Prefer streaming, then ``tool_calls`` attribute, then block copy."""
    for cand in (from_streaming, from_tool_call_attr, from_block):
        if tool_args_meaningful(cand):
            return extract_tool_args_dict(cand)
    return {}


def resolve_tool_invocations_for_display(
    message: Any,
    expanded_tool_blocks: list[dict[str, Any]],
    *,
    streaming_overlay: Mapping[str, dict[str, Any]] | None = None,
) -> list[ResolvedToolInvocation]:
    """Merge tool identity and kwargs from all chunk sources.

    Args:
        message: ``AIMessage`` / ``AIMessageChunk`` (after non-standard expansion).
        expanded_tool_blocks: Tool-ish blocks only, in stream order (first id occurrence
            defines ordering for duplicates).
        streaming_overlay: Optional ``tool_call_id -> args dict`` from accumulated
            ``tool_call_chunks`` (already parsed JSON objects).

    Returns:
        Ordered list of resolved invocations, including ids only present on
        ``message.tool_calls`` or in the streaming overlay.
    """
    streaming_overlay = streaming_overlay or {}

    block_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    order: list[str] = []
    for b in expanded_tool_blocks:
        if not isinstance(b, dict) or not is_toolish_display_block(b):
            continue
        tid_raw = b.get("id")
        if tid_raw is None:
            continue
        tid = str(tid_raw)
        if not tid:
            continue
        name = str(b.get("name") or "")
        args = _args_from_toolish_block(b)
        if tid not in block_by_id:
            order.append(tid)
        block_by_id[tid] = (name, args)

    tc_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    raw_tc = getattr(message, "tool_calls", None)
    if isinstance(raw_tc, list):
        for tc in normalize_tool_calls_list(raw_tc):
            tid = str(tc.get("id") or "")
            if not tid:
                continue
            name = str(tc.get("name") or "")
            tc_by_id[tid] = (name, extract_tool_args_dict(tc))

    all_ids: list[str] = []
    seen: set[str] = set()
    for tid in list(order) + list(tc_by_id.keys()) + list(streaming_overlay.keys()):
        if not tid or tid in seen:
            continue
        seen.add(tid)
        all_ids.append(tid)

    out: list[ResolvedToolInvocation] = []
    for tid in all_ids:
        block_name, block_args = block_by_id.get(tid, ("", {}))
        tc_name, tc_args = tc_by_id.get(tid, ("", {}))
        stream_args = streaming_overlay.get(tid, {})
        name = tc_name or block_name or ""
        if not name or name == "tool":
            inferred = infer_tool_name_from_call_id(tid)
            if inferred:
                name = inferred
        if not name:
            name = "tool"
        merged = _pick_args_from_sources(
            from_streaming=stream_args,
            from_tool_call_attr=tc_args,
            from_block=block_args,
        )
        out.append(ResolvedToolInvocation(tool_call_id=tid, name=name, args=merged))

    return out


def materialize_ai_blocks_with_resolved_tools(
    expanded_blocks: list[dict[str, Any]],
    message: Any,
    *,
    streaming_overlay: Mapping[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return display blocks with tool arguments merged from all chunk sources.

    Preserves order of ``expanded_blocks``; appends tool calls that exist only on
    ``message.tool_calls`` or the streaming overlay (same behavior as the former
    append + backfill + merge passes).
    """
    tool_only = [b for b in expanded_blocks if isinstance(b, dict) and is_toolish_display_block(b)]
    resolved = resolve_tool_invocations_for_display(
        message,
        tool_only,
        streaming_overlay=streaming_overlay,
    )
    res_map = {r.tool_call_id: r for r in resolved}
    seen_tool_ids: set[str] = {str(b.get("id")) for b in tool_only if b.get("id") is not None}

    out: list[dict[str, Any]] = []
    for b in expanded_blocks:
        if not isinstance(b, dict):
            out.append(b)
            continue
        if b.get("type") == "text":
            out.append(b)
            continue
        if is_toolish_display_block(b):
            tid = str(b.get("id") or "")
            if tid and tid in res_map:
                r = res_map[tid]
                out.append(
                    {
                        "type": "tool_call",
                        "name": r.name,
                        "args": r.args,
                        "id": tid,
                    }
                )
            else:
                out.append(b)
        else:
            out.append(b)

    for r in resolved:
        if r.tool_call_id not in seen_tool_ids:
            out.append(
                {
                    "type": "tool_call",
                    "name": r.name,
                    "args": r.args,
                    "id": r.tool_call_id,
                }
            )
    return out


def build_streaming_args_overlay(
    message: Any,
    pending_tool_calls_lc: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Map ``tool_call_id`` → parsed args dict from ``tool_call_chunks`` accumulation.

    Updates the overlay on every chunk whenever JSON parses successfully. A prior
    version stopped after the first parse (``tui_stream_mounted``), which froze the
    overlay when ``args_str`` grew across chunks so the TUI kept ``read_file(…)``
    headers even after the path arrived in the accumulated string.
    """
    from langchain_core.messages import AIMessageChunk

    overlay: dict[str, dict[str, Any]] = {}
    chunk_pos = getattr(message, "chunk_position", None)
    is_final_chunk = (not isinstance(message, AIMessageChunk)) or chunk_pos == "last"

    for tc_id, pend in list(pending_tool_calls_lc.items()):
        parsed = try_parse_pending_tool_call_args(pend)
        if parsed is None:
            continue
        name = str(pend.get("name") or "")
        if not name:
            continue
        # Omit empty dicts — they are non-meaningful for merge/display (IG-300).
        if not parsed:
            continue
        str_id = str(tc_id)
        overlay[str_id] = parsed
        if logger.isEnabledFor(logging.DEBUG):
            args_preview = str(parsed)[:200]
            logger.debug(
                "tool_stream_overlay id=%s name=%s keys=%s chunk_position=%r is_final=%s preview=%s",
                str_id,
                name,
                sorted(parsed.keys()) if isinstance(parsed, dict) else "?",
                chunk_pos,
                is_final_chunk,
                args_preview,
            )
    return overlay


__all__ = [
    "ResolvedToolInvocation",
    "build_streaming_args_overlay",
    "infer_tool_name_from_call_id",
    "is_toolish_display_block",
    "materialize_ai_blocks_with_resolved_tools",
    "resolve_tool_invocations_for_display",
    "tool_args_meaningful",
]
