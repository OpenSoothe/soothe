"""Apply typed ``soothe.stream.tool_call.update`` events to the TUI adapter."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE
from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

from soothe_cli.events.tools.tool_call_resolution import merge_tool_display_args
from soothe_cli.tui.textual_adapter._stream_formatting import (
    alias_subgraph_pending_and_overlay,
    canonical_subgraph_tool_ids,
)

if TYPE_CHECKING:
    from soothe_cli.tui.step_task_routing import StepTaskRouter
    from soothe_cli.tui.textual_adapter._adapter import TextualUIAdapter
    from soothe_cli.tui.textual_adapter._turn_ui_batch import TurnToolUiCoalescer


async def apply_tool_call_wire_update(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    data: dict[str, Any],
    ns_key: tuple[str, ...],
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
    ui_coalesce: TurnToolUiCoalescer | None = None,
) -> bool:
    """Seed pending tool state from a wire tool-call update event (no tool-card UI)."""
    if str(data.get("type", "")) != STREAM_TOOL_CALL_UPDATE:
        return False

    if ns_key:
        router.on_subgraph_namespace(ns_key)

    tcid = str(data.get("tool_call_id", "")).strip()
    if not tcid:
        return True

    name = str(data.get("name") or "").strip() or "tool"
    raw_args = data.get("args")
    if not isinstance(raw_args, dict) or not raw_args:
        return True

    if ui_coalesce is not None and ui_coalesce.note_wire_apply(tcid, raw_args):
        return True

    overlay = streaming_overlay if streaming_overlay is not None else {}
    is_main = ns_key == ()
    ts = router.resolve_task_scope(ns_key) if ns_key else None
    merge_id, row_key = (
        (tcid, tcid) if is_main else canonical_subgraph_tool_ids(ns_key, tcid, task_scope=ts)
    )

    for key in {tcid, merge_id, row_key}:
        if not key:
            continue
        overlay[key] = dict(raw_args)
        pending_tool_calls_lc[key] = {
            "name": name,
            "args_str": json.dumps(raw_args, separators=(",", ":")),
            "is_complete_json": True,
            "emitted": False,
            "is_main": is_main,
        }

    if ns_key:
        alias_subgraph_pending_and_overlay(pending_tool_calls_lc, overlay, router, ns_key)

    display_args = merge_tool_display_args(
        merge_id or tcid,
        block_args=raw_args,
        streaming_overlay=overlay,
        pending_tool_calls_lc=pending_tool_calls_lc,
        tool_name=name,
    )

    if is_main and name == "task":
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        bound_step_id = parsed_sid or router.step_id_for_tool(tcid)
        raw_st = display_args.get("subagent_type", "")
        subagent_type = raw_st.strip() if isinstance(raw_st, str) else ""
        if subagent_type:
            router.register_task_spawn(tcid, subagent_type, step_id=bound_step_id)
        return True

    if is_main:
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        bound_step_id = parsed_sid or router.step_id_for_tool(tcid)
        if bound_step_id:
            step_w = adapter._current_step_messages.get(bound_step_id)
            if step_w is not None and name != "task":
                if step_w.has_tool_call_row(tcid):
                    step_w.update_tool_args(tcid, display_args)
                else:
                    step_w.add_tool_call(tcid, name, display_args)
                adapter._tool_to_step[tcid] = step_w
        return True

    _merge_buf, display_key = canonical_subgraph_tool_ids(ns_key, tcid, task_scope=ts)
    if display_key:
        router.buffer_subgraph_tool(
            ns_key=ns_key,
            lookup_id=tcid,
            display_key=display_key,
            tool_name=name,
            args=display_args,
        )
    return True
