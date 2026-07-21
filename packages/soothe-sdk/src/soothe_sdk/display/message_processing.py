"""Shared message processing utilities for CLI and TUI modes.

This module provides helper functions for message handling logic to ensure
consistent behavior between headless CLI mode and the TUI interface. Lives
in the SDK so the host-resident ``CardBinder`` can reuse it
without importing client code.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Mapping
from typing import Any, NamedTuple

# ============================================================================
# Shared Tool Call Streaming Helpers
# ============================================================================


class PendingToolCallFinalize(NamedTuple):
    """Result of finalizing a pending streamed tool call."""

    parsed_args: dict[str, Any] | None
    pending_state: dict[str, Any]
    needs_emit: bool
    raw_args_str: str

    @classmethod
    def empty(cls) -> PendingToolCallFinalize:
        """Sentinel when the tool call id is missing or unknown."""
        return cls(None, {}, False, "")


def seed_pending_tool_calls_from_message(
    pending_tool_calls: dict[str, dict[str, Any]],
    message: Any,
    *,
    is_main: bool = True,
) -> None:
    """Register ``message.tool_calls`` entries when chunks did not stream args yet.

      Parallel execute waves sometimes emit a final ``AIMessage`` with ``tool_calls``
    but empty ``tool_call_chunks``; seeding preserves full kwargs for the TUI overlay.
    """
    raw = getattr(message, "tool_calls", None)
    if not raw and isinstance(message, dict):
        raw = message.get("tool_calls")
    if not isinstance(raw, list):
        return
    for tc in normalize_tool_calls_list(raw):
        tc_id = str(tc.get("id") or "").strip()
        if not tc_id:
            continue
        tc_name = str(tc.get("name") or "").strip()
        args = tc.get("args")
        if isinstance(args, str) and args.strip():
            try:
                parsed = json.loads(args)
                args_dict = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                args_dict = {}
            args_str = args
            is_complete = bool(args_dict)
        elif isinstance(args, dict) and args:
            args_dict = args
            args_str = json.dumps(args)
            is_complete = True
        else:
            args_dict = {}
            args_str = ""
            is_complete = False
        existing = pending_tool_calls.get(tc_id)
        if existing:
            if is_complete and args_str:
                existing["args_str"] = args_str
                existing["is_complete_json"] = True
            if tc_name and not existing.get("name"):
                existing["name"] = tc_name
            continue
        pending_tool_calls[tc_id] = {
            "name": tc_name,
            "args_str": args_str,
            "is_complete_json": is_complete,
            "emitted": False,
            "is_main": is_main,
        }


def accumulate_tool_call_chunks(
    pending_tool_calls: dict[str, dict[str, Any]],
    tool_call_chunks: list[dict[str, Any]],
    *,
    is_main: bool = True,
    last_active_id: str = "",
) -> str:
    """Accumulate streaming tool call chunks into pending_tool_calls.

    LangChain streams tool args in chunks - first chunk has the tool name but
    empty args, subsequent chunks contain partial JSON strings. This function
    tracks and accumulates them.

    Args:
        pending_tool_calls: Dict to store pending tool calls (tool_call_id -> state).
        tool_call_chunks: List of tool_call_chunk dicts from AIMessageChunk.
        is_main: Whether this is from the main agent.
        last_active_id: Previous last active tool_call_id for orphan chunk attachment.

    Returns:
        Updated last_active_id (tool_call_id of most recently seen chunk with id).
    """
    # Track the most recently active tool_call_id for orphan chunk attachment
    current_last_active = last_active_id

    for tcc in tool_call_chunks:
        if not isinstance(tcc, dict):
            continue
        tc_id_raw = tcc.get("id")
        tc_id = str(tc_id_raw) if tc_id_raw not in (None, "") else ""
        tc_name = tcc.get("name")
        tc_args = tcc.get("args", "")

        # First chunk with a tool name: register the pending tool call
        if tc_name and tc_id and tc_id not in pending_tool_calls:
            if isinstance(tc_args, str):
                args_str = tc_args
                is_complete = False  # String may be partial JSON
            elif isinstance(tc_args, dict) and tc_args:
                args_str = json.dumps(tc_args)
                is_complete = True  # Dict yields complete JSON
            else:
                args_str = ""
                is_complete = False  # Empty or missing args
            pending_tool_calls[tc_id] = {
                "name": tc_name,
                "args_str": args_str,
                "is_complete_json": is_complete,
                "emitted": False,
                "is_main": is_main,
            }
            current_last_active = tc_id  # Track most recently registered tool
        # Some providers send final args as a dict on a later chunk (replace previous)
        elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, dict) and tc_args:
            pending_tool_calls[tc_id]["args_str"] = json.dumps(tc_args)
            pending_tool_calls[tc_id]["is_complete_json"] = True
            current_last_active = tc_id
        # Subsequent chunks: accumulate partial JSON strings for this tool call id
        elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, str) and tc_args:
            # If args_str already contains complete JSON, provider refined args → restart
            if pending_tool_calls[tc_id].get("is_complete_json"):
                pending_tool_calls[tc_id]["args_str"] = tc_args
                pending_tool_calls[tc_id]["is_complete_json"] = False
            else:
                # Normal partial accumulation
                pending_tool_calls[tc_id]["args_str"] += tc_args
            current_last_active = tc_id
        elif tc_args and isinstance(tc_args, str) and tc_args:
            # Orphan chunks (no id) — attach to the most recently active tool call
            # NOT the first pending tool, which would mix args across tools
            if current_last_active and current_last_active in pending_tool_calls:
                if not pending_tool_calls[current_last_active].get("emitted"):
                    pending_tool_calls[current_last_active]["args_str"] += tc_args

    return current_last_active


def _tool_id_from_chunk_dict(tcc: dict[str, Any]) -> str:
    tc_id_raw = tcc.get("id")
    return str(tc_id_raw) if tc_id_raw not in (None, "") else ""


def _tool_id_from_call_dict(tc: dict[str, Any]) -> str:
    return str(tc.get("id") or "").strip()


def tool_ids_touched_by_stream_message(message: Any) -> set[str]:
    """Return tool_call_ids referenced on one stream message (chunks, calls, blocks)."""
    ids: set[str] = set()
    if isinstance(message, dict):
        for tcc in message.get("tool_call_chunks") or []:
            if isinstance(tcc, dict):
                tid = _tool_id_from_chunk_dict(tcc)
                if tid:
                    ids.add(tid)
        for tc in message.get("tool_calls") or []:
            if isinstance(tc, dict):
                tid = _tool_id_from_call_dict(tc)
                if tid:
                    ids.add(tid)
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") in (
                    "tool_call",
                    "tool_call_chunk",
                    "tool_use",
                ):
                    tid = str(block.get("id") or "").strip()
                    if tid:
                        ids.add(tid)
        return ids

    for tcc in getattr(message, "tool_call_chunks", None) or []:
        if isinstance(tcc, dict):
            tid = _tool_id_from_chunk_dict(tcc)
            if tid:
                ids.add(tid)
    for tc in getattr(message, "tool_calls", None) or []:
        if isinstance(tc, dict):
            tid = _tool_id_from_call_dict(tc)
            if tid:
                ids.add(tid)
    content = getattr(message, "content", None)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in (
                "tool_call",
                "tool_call_chunk",
                "tool_use",
            ):
                tid = str(block.get("id") or "").strip()
                if tid:
                    ids.add(tid)
    for block in getattr(message, "content_blocks", None) or []:
        if isinstance(block, dict) and block.get("type") in (
            "tool_call",
            "tool_call_chunk",
            "tool_use",
        ):
            tid = str(block.get("id") or "").strip()
            if tid:
                ids.add(tid)
    return ids


def ingest_tool_call_stream_state(
    pending_tool_calls: dict[str, dict[str, Any]],
    message: Any,
    *,
    is_main: bool = True,
    last_active_id: str = "",
) -> str:
    """Accumulate ``tool_call_chunks`` and seed ``tool_calls`` from one stream message.

    Works for LangChain message objects and wire dicts (host WebSocket path).

    Args:
        pending_tool_calls: Dict to store pending tool calls.
        message: Message with tool_call_chunks and/or tool_calls.
        is_main: Whether this is from the main agent.
        last_active_id: Previous last active tool_call_id for orphan attachment.

    Returns:
        Updated last_active_id for subsequent calls.
    """
    if isinstance(message, dict):
        chunks = message.get("tool_call_chunks")
        if isinstance(chunks, list):
            last_active_id = accumulate_tool_call_chunks(
                pending_tool_calls, chunks, is_main=is_main, last_active_id=last_active_id
            )
        seed_pending_tool_calls_from_message(pending_tool_calls, message, is_main=is_main)
        return last_active_id
    last_active_id = accumulate_tool_call_chunks(
        pending_tool_calls,
        getattr(message, "tool_call_chunks", None) or [],
        is_main=is_main,
        last_active_id=last_active_id,
    )
    seed_pending_tool_calls_from_message(pending_tool_calls, message, is_main=is_main)
    return last_active_id


def tool_lookup_step_id(tool_call_id: str) -> str:
    """Return the execute-step id encoded in a unified tool_call_id, if any."""
    from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

    sid, _, _, _ = parse_unified_tool_call_id(str(tool_call_id).strip())
    return sid or ""


def _pending_or_overlay_id_matches_lookup(
    candidate_id: str,
    lookup_id: str,
    *,
    tool_name: str,
) -> bool:
    """True when a pending/overlay key refers to the same logical tool call as ``lookup_id``."""
    cid = str(candidate_id).strip()
    lid = str(lookup_id).strip()
    if not cid or not lid:
        return False
    if cid == lid:
        return True

    from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

    cand_step, cand_type, cand_tidx, cand_info = parse_unified_tool_call_id(cid)
    lookup_step, lookup_type, lookup_tidx, lookup_info = parse_unified_tool_call_id(lid)

    # Unified wire ids: always require the same execute step (parallel ``task:0`` rows).
    if lookup_step and cand_step:
        if lookup_step != cand_step:
            return False
        if lookup_type == "s" and cand_type == "s":
            return lookup_info == cand_info
        if lookup_type == "t" and cand_type == "t":
            return lookup_tidx == cand_tidx and lookup_info == cand_info
        return False

    # Non-unified ids: only match when names align and ids are identical (handled above).
    _ = tool_name
    return False


def _resolve_pending_lookup_tool_name(
    tool_call_id: str,
    *,
    tool_name: str | None = None,
) -> str:
    """Resolve the tool name used to match pending stream buffers to a logical call."""
    name = (tool_name or "").strip()
    if name and name != "tool":
        return name
    tcid = str(tool_call_id).strip()
    if tcid:
        from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

        _, _, _, tool_info = parse_unified_tool_call_id(tcid)
        if tool_info:
            head = tool_info.split(".")[0].split(":")[0].strip()
            if head and head != "tool":
                return head
    return name


def richest_pending_args_for_lookup(
    pending_tool_calls: Mapping[str, dict[str, Any]],
    tool_call_id: str,
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Return parsed args for ``tool_call_id`` from the pending buffer.

    Only pending entries whose unified id matches ``tool_call_id`` (or same step and
    tool_info for ``task``) are considered.
    """
    if not isinstance(pending_tool_calls, Mapping):
        return {}
    tcid = str(tool_call_id).strip()
    if tcid:
        direct = pending_tool_calls.get(tcid)
        if isinstance(direct, dict):
            parsed = try_parse_pending_tool_call_args(direct)
            if parsed:
                return parsed
    name = _resolve_pending_lookup_tool_name(tcid, tool_name=tool_name)
    if not name or name == "tool":
        return {}
    best: dict[str, Any] = {}
    for pid, pend in list(pending_tool_calls.items()):
        if not isinstance(pend, dict):
            continue
        if str(pend.get("name") or "").strip() != name:
            continue
        if not _pending_or_overlay_id_matches_lookup(str(pid), tcid, tool_name=name):
            continue
        parsed = try_parse_pending_tool_call_args(pend)
        if not parsed:
            continue
        if len(parsed) > len(best):
            best = parsed
    return best


def try_parse_pending_tool_call_args(
    pending: dict[str, Any],
) -> dict[str, Any] | None:
    """Try to parse the accumulated args_str as JSON.

    Args:
        pending: Pending tool call state dict with 'args_str' key.

    Returns:
        Parsed args dict if valid JSON, None otherwise.
    """
    args_str = pending.get("args_str", "")
    if not args_str:
        return None
    try:
        parsed = json.loads(args_str)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def finalize_pending_tool_call(
    pending_tool_calls: dict[str, dict[str, Any]],
    tool_call_id: str,
) -> PendingToolCallFinalize:
    """Finalize and remove a pending tool call when its result arrives.

    Args:
        pending_tool_calls: Dict of pending tool calls.
        tool_call_id: ID of the tool call to finalize.

    Returns:
        Parsed args, pending state, emit flag, and raw args string.
        If not found, returns :meth:`PendingToolCallFinalize.empty`.
    """
    str_id = str(tool_call_id) if tool_call_id else ""
    if not str_id or str_id not in pending_tool_calls:
        return PendingToolCallFinalize.empty()

    pending = pending_tool_calls[str_id]
    parsed_args = None
    needs_emit = not pending.get("emitted", False)
    raw_args_str = pending.get("args_str", "")

    if needs_emit:
        # Try to parse args one more time
        if raw_args_str:
            with contextlib.suppress(json.JSONDecodeError):
                result = json.loads(raw_args_str)
                if isinstance(result, dict):
                    parsed_args = result
        pending["emitted"] = True

    # Clean up the pending entry
    del pending_tool_calls[str_id]
    return PendingToolCallFinalize(parsed_args, pending, needs_emit, raw_args_str)


def extract_tool_brief(tool_name: str, content: str | dict | Any, max_length: int = 120) -> str:
    r"""Extract a concise one-line summary from tool result content.

    Flattens multimodal content, then truncates to ``max_length`` (web tools use
    the first line only).

    Args:
        tool_name: Name of the tool that produced the content.
        content: Tool result content (string, dict, or ToolOutput).
        max_length: Maximum length of the brief.

    Returns:
        One-line summary suitable for status lines and logging.
    """
    from soothe_sdk.display.tool_message_format import format_tool_message_content

    text = format_tool_message_content(content)
    if not text:
        return ""
    web_tools = {"wizsearch_search", "wizsearch_crawl", "web_search", "fetch_url"}
    if tool_name in web_tools:
        first_line = text.split("\n", 1)[0].strip()
        if first_line:
            return first_line[:max_length]
    return text.replace("\n", " ")[:max_length]


def coerce_tool_call_args_to_dict(raw: Any) -> dict[str, Any]:
    """Normalize tool arguments for display.

    ``tool_call_chunk`` content blocks use a JSON string; merged ``tool_calls`` use dicts
    (see LangChain ``ToolCall`` / ``ToolCallChunk``).
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}
    return {}


# Keys that are metadata on tool-call blocks / ``tool_calls`` entries, not tool parameters.
_TOOL_CALL_METADATA_KEYS: frozenset[str] = frozenset(
    {"name", "id", "type", "index", "tool_call_id"},
)


def extract_tool_args_dict(tool_like: Any) -> dict[str, Any]:
    """Flatten tool arguments from a ``tool_calls`` entry, content block, or args dict.

    Providers and transports differ: some use ``args``, others ``arguments`` (JSON string),
    Anthropic-style ``input``, or top-level parameter keys without an ``args`` envelope.
    """
    if not isinstance(tool_like, dict):
        return coerce_tool_call_args_to_dict(tool_like)

    base = coerce_tool_call_args_to_dict(tool_like.get("args"))
    if base:
        return base

    base = coerce_tool_call_args_to_dict(tool_like.get("arguments"))
    if base:
        return base

    inp = tool_like.get("input")
    if isinstance(inp, dict) and inp:
        return dict(inp)
    if isinstance(inp, str) and inp.strip():
        base = coerce_tool_call_args_to_dict(inp)
        if base:
            return base

    raw_s = tool_like.get("_raw") or tool_like.get("raw_args_str")
    if isinstance(raw_s, str) and raw_s.strip():
        base = coerce_tool_call_args_to_dict(raw_s)
        if base:
            return base

    skip = _TOOL_CALL_METADATA_KEYS | {
        "args",
        "arguments",
        "input",
        "_raw",
        "raw_args_str",
        "value",
        "_subgraph_tool",
    }
    flat = {k: v for k, v in tool_like.items() if k not in skip}
    if flat:
        return flat

    return {}


def coerce_tool_call_entry_to_dict(tc: Any) -> dict[str, Any] | None:
    """Normalize a ``tool_calls`` entry to a plain dict (handles Pydantic models)."""
    if isinstance(tc, dict):
        return tc
    model_dump = getattr(tc, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            return None
    return None


def normalize_tool_calls_list(raw: list[Any]) -> list[dict[str, Any]]:
    """Coerce ``msg.tool_calls`` to ``dict`` entries for display logic."""
    out: list[dict[str, Any]] = []
    for tc in raw:
        coerced = coerce_tool_call_entry_to_dict(tc)
        if coerced:
            out.append(coerced)
    return out


def tool_calls_have_any_arg_dict(tc_list: list[Any]) -> bool:
    """True if any tool call has non-empty coerced argument dict."""
    return any(extract_tool_args_dict(tc) for tc in normalize_tool_calls_list(tc_list))


def _normalize_tool_name_for_arg_map(tool_name: str) -> str:
    """Map API tool names (any casing) to snake_case for stats / registry lookup."""
    if not tool_name:
        return tool_name
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tool_name).lower()
