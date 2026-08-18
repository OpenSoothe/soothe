"""Typed WebSocket stream events for tool-call UI.

Supplements LangGraph ``messages`` chunks with explicit tool kwargs so clients
do not depend on fragile LangChain message shape drift across ``model_dump`` /
``tool_call_chunks`` / ``tool_calls``.
"""

from __future__ import annotations

import json
from typing import Any

STREAM_TOOL_CALL_UPDATE = "soothe.stream.tool_call.update"
TOOL_CALL_UPDATES_BATCH = "tool_call_updates_batch"


def tool_call_update_event(
    *,
    tool_call_id: str,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Build a ``mode=custom`` payload with complete tool invocation kwargs."""
    return {
        "type": STREAM_TOOL_CALL_UPDATE,
        "tool_call_id": str(tool_call_id).strip(),
        "name": str(name or "").strip() or "tool",
        "args": dict(args or {}),
    }


def unified_tool_update_allowed_without_args(tool_call_id: str) -> bool:
    """True when a wire update may omit kwargs (unified main or subgraph tool rows).

    Step-level ``task`` delegations are excluded; they are ingested via dedicated paths.
    Raw provider ids (non-unified) still require parsed args before batching.
    """
    from soothe_sdk.ux.task_namespace import (
        is_inner_subgraph_task_tool_id,
        is_step_level_task_tool_id,
        parse_unified_tool_call_id,
    )

    tcid = str(tool_call_id or "").strip()
    if not tcid or is_step_level_task_tool_id(tcid) or is_inner_subgraph_task_tool_id(tcid):
        return False
    _, type_code, _, tool_info = parse_unified_tool_call_id(tcid)
    if type_code not in ("s", "t"):
        return False
    return (tool_info or "").split(":")[0] != "task"


def _args_dict_from_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    raw = tc.get("args")
    if isinstance(raw, dict) and raw:
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    inp = tc.get("input")
    if isinstance(inp, dict) and inp:
        return dict(inp)
    return {}


def _wire_message_body(msg: dict[str, Any]) -> dict[str, Any]:
    data = msg.get("data")
    if isinstance(data, dict):
        return data
    return msg


def extract_tool_call_updates_from_wire_message(
    msg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract ``soothe.stream.tool_call.update`` payloads from a wire AI message dict."""
    if not isinstance(msg, dict):
        return []
    body = _wire_message_body(msg)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(tc: dict[str, Any]) -> None:
        tid = str(tc.get("id") or "").strip()
        if not tid or tid in seen:
            return
        args = _args_dict_from_tool_call(tc)
        name = str(tc.get("name") or "").strip() or "tool"
        if not args and not unified_tool_update_allowed_without_args(tid):
            return
        seen.add(tid)
        out.append(
            tool_call_update_event(
                tool_call_id=tid,
                name=name,
                args=dict(args or {}),
            )
        )

    for tc in body.get("tool_calls") or []:
        if isinstance(tc, dict):
            _append(tc)

    for chunk in body.get("tool_call_chunks") or []:
        if not isinstance(chunk, dict):
            continue
        tid = str(chunk.get("id") or "").strip()
        name = str(chunk.get("name") or "").strip() or "tool"
        if not tid or tid in seen:
            continue
        args = _args_dict_from_tool_call(chunk)
        if not args and not unified_tool_update_allowed_without_args(tid):
            continue
        seen.add(tid)
        out.append(
            tool_call_update_event(
                tool_call_id=tid,
                name=name,
                args=dict(args or {}),
            )
        )

    return out


__all__ = [
    "STREAM_TOOL_CALL_UPDATE",
    "TOOL_CALL_UPDATES_BATCH",
    "extract_tool_call_updates_from_wire_message",
    "tool_call_update_event",
    "unified_tool_update_allowed_without_args",
]
