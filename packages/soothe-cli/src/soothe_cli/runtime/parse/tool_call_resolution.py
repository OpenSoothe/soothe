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

from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

from soothe_cli.runtime.parse.message_processing import (
    extract_tool_args_dict,
    normalize_tool_calls_list,
    try_parse_pending_tool_call_args,
)

logger = logging.getLogger(__name__)


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
    from_message_tool_calls: dict[str, Any],
    from_streaming: dict[str, Any],
    from_tool_call_attr: dict[str, Any],
    from_block: dict[str, Any],
) -> dict[str, Any]:
    """Merge kwargs from all sources; later sources override earlier partial values.

    Order (lowest → highest priority): block buffer, streaming overlay, pending
    buffer, ``message.tool_calls``. This keeps early partial stream args visible until
    complete JSON arrives on pending or the wire message.
    """
    merged: dict[str, Any] = {}
    for cand in (
        from_block,
        from_streaming,
        from_tool_call_attr,
        from_message_tool_calls,
    ):
        if not isinstance(cand, dict):
            continue
        parsed = extract_tool_args_dict(cand)
        if parsed:
            merged.update(parsed)
    return merged


def merge_tool_display_args(
    tool_call_id: str,
    *,
    block_args: dict[str, Any] | None = None,
    streaming_overlay: Mapping[str, dict[str, Any]] | None = None,
    pending_tool_calls_lc: Mapping[str, dict[str, Any]] | None = None,
    message: Any = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Merge kwargs from block buffer, ``tool_call_chunks`` overlay, and pending JSON.

    CoreAgent executes with complete args; the stream often splits them across channels.
    The TUI must prefer the richest source on every chunk so task descriptions and tool
    kwargs appear as soon as they are available.
    """
    tcid = str(tool_call_id).strip()
    stream_args: dict[str, Any] = {}
    if tcid and streaming_overlay:
        raw = streaming_overlay.get(tcid)
        if isinstance(raw, dict):
            stream_args = dict(raw)
        if not stream_args:
            from soothe_cli.runtime.parse.message_processing import (
                _resolve_pending_lookup_tool_name,
            )

            lookup_name = _resolve_pending_lookup_tool_name(tcid, tool_name=tool_name)
            if lookup_name and pending_tool_calls_lc:
                from soothe_cli.runtime.parse.message_processing import (
                    _pending_or_overlay_id_matches_lookup,
                )

                best: dict[str, Any] = {}
                for oid, oargs in streaming_overlay.items():
                    if oid == tcid or not isinstance(oargs, dict) or not oargs:
                        continue
                    if not _pending_or_overlay_id_matches_lookup(
                        str(oid), tcid, tool_name=lookup_name
                    ):
                        continue
                    pend = pending_tool_calls_lc.get(str(oid))
                    if (
                        isinstance(pend, dict)
                        and str(pend.get("name") or "").strip() == lookup_name
                        and len(oargs) > len(best)
                    ):
                        best = dict(oargs)
                stream_args = best
    pend_parsed: dict[str, Any] = {}
    if tcid and pending_tool_calls_lc:
        from soothe_cli.runtime.parse.message_processing import richest_pending_args_for_lookup

        pend_parsed = richest_pending_args_for_lookup(
            pending_tool_calls_lc,
            tcid,
            tool_name=tool_name,
        )
    message_args: dict[str, Any] = {}
    if tcid and message is not None:
        raw_tc = getattr(message, "tool_calls", None)
        if raw_tc is None and isinstance(message, dict):
            raw_tc = message.get("tool_calls")
        if isinstance(raw_tc, list):
            normalized = normalize_tool_calls_list(raw_tc)
            for tc in normalized:
                if str(tc.get("id") or "").strip() == tcid:
                    message_args = extract_tool_args_dict(tc)
                    break
            if not message_args:
                from soothe_cli.runtime.parse.message_processing import (
                    _resolve_pending_lookup_tool_name,
                )

                lookup_name = _resolve_pending_lookup_tool_name(tcid, tool_name=tool_name)
                if lookup_name:
                    matches = [
                        tc for tc in normalized if str(tc.get("name") or "").strip() == lookup_name
                    ]
                    if len(matches) == 1:
                        message_args = extract_tool_args_dict(matches[0])
                    elif matches:
                        from soothe_cli.runtime.parse.message_processing import (
                            _pending_or_overlay_id_matches_lookup,
                        )

                        scoped = [
                            tc
                            for tc in matches
                            if _pending_or_overlay_id_matches_lookup(
                                str(tc.get("id") or ""),
                                tcid,
                                tool_name=lookup_name,
                            )
                        ]
                        best: dict[str, Any] = {}
                        for tc in scoped:
                            cand = extract_tool_args_dict(tc)
                            if len(cand) > len(best):
                                best = cand
                        message_args = best
    block = block_args if isinstance(block_args, dict) else {}
    return _pick_args_from_sources(
        from_message_tool_calls=message_args,
        from_streaming=stream_args,
        from_tool_call_attr=pend_parsed,
        from_block=block,
    )


def resolve_stream_tool_name(
    tool_call_id: str,
    *,
    chunk_name: str | None,
    pending_tool_calls_lc: Mapping[str, dict[str, Any]] | None = None,
) -> str:
    """Resolve display tool name when the chunk uses a placeholder ``tool`` label."""
    name = (chunk_name or "").strip()
    if name and name != "tool":
        return name
    tcid = str(tool_call_id).strip()
    if tcid and pending_tool_calls_lc:
        pend = pending_tool_calls_lc.get(tcid)
        if isinstance(pend, dict):
            pend_name = str(pend.get("name") or "").strip()
            if pend_name and pend_name != "tool":
                return pend_name
    # IG-418: Extract tool name from unified format
    _sid, _type_code, _, tool_info = parse_unified_tool_call_id(tcid)
    if tool_info:
        # tool_info is like "ls:0" or "task:5" - extract the tool name
        head = tool_info.split(":")[0].split(".")[0].strip()
        if head and head != "tool":
            return head
    return name or "tool"


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
            # IG-418: Extract tool name from unified format
            _sid, _type_code, _, tool_info = parse_unified_tool_call_id(tid)
            if tool_info:
                head = tool_info.split(":")[0].split(".")[0].strip()
                if head and head != "tool":
                    name = head
        if not name:
            name = "tool"
        merged = _pick_args_from_sources(
            from_message_tool_calls=tc_args,
            from_streaming=stream_args,
            from_tool_call_attr={},
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
    *,
    only_ids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map ``tool_call_id`` → parsed args dict from ``tool_call_chunks`` accumulation.

    When ``only_ids`` is set, only those pending entries are parsed (incremental path).
    Otherwise every pending entry is considered (legacy / final flush).
    """
    from langchain_core.messages import AIMessageChunk

    from soothe_cli.runtime.parse.message_processing import tool_ids_touched_by_stream_message

    overlay: dict[str, dict[str, Any]] = {}
    chunk_pos = getattr(message, "chunk_position", None)
    is_final_chunk = (not isinstance(message, AIMessageChunk)) or chunk_pos == "last"

    if only_ids is not None:
        ids_to_scan = only_ids
    else:
        ids_to_scan = tool_ids_touched_by_stream_message(message)
        if not ids_to_scan:
            ids_to_scan = set(pending_tool_calls_lc.keys())
    if not ids_to_scan:
        return overlay

    for tc_id in ids_to_scan:
        pend = pending_tool_calls_lc.get(str(tc_id))
        if not isinstance(pend, dict):
            continue
        parsed = try_parse_pending_tool_call_args(pend)
        if parsed is None:
            continue
        name = str(pend.get("name") or "")
        if not name:
            continue
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
    "is_toolish_display_block",
    "materialize_ai_blocks_with_resolved_tools",
    "merge_tool_display_args",
    "resolve_stream_tool_name",
    "resolve_tool_invocations_for_display",
    "tool_args_meaningful",
]
