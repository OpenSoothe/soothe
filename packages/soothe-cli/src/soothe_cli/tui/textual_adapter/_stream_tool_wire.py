"""Apply typed ``soothe.stream.tool_call.update`` events to the TUI adapter."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE
from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

from soothe_cli.tui.textual_adapter._stream_formatting import (
    _ensure_task_delegation_card,
    enrich_task_delegation_args,
)
from soothe_cli.tui.widgets.messages import ToolCallMessage

if TYPE_CHECKING:
    from soothe_cli.tui.step_task_routing import StepTaskRouter
    from soothe_cli.tui.textual_adapter._adapter import TextualUIAdapter


async def apply_tool_call_wire_update(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    data: dict[str, Any],
    ns_key: tuple[str, ...],
    show_tool_ui: bool,
    pending_tool_calls_lc: dict[str, dict[str, Any]],
) -> bool:
    """Seed pending tool state and refresh cards from a wire tool-call update event.

    Returns:
        True when ``data`` was a handled tool-call update.
    """
    if str(data.get("type", "")) != STREAM_TOOL_CALL_UPDATE:
        return False
    if not show_tool_ui:
        return True

    tcid = str(data.get("tool_call_id", "")).strip()
    if not tcid:
        return True

    name = str(data.get("name") or "").strip() or "tool"
    raw_args = data.get("args")
    if not isinstance(raw_args, dict) or not raw_args:
        return True

    args_str = json.dumps(raw_args, separators=(",", ":"))
    is_main = ns_key == ()
    pending_tool_calls_lc[tcid] = {
        "name": name,
        "args_str": args_str,
        "is_complete_json": True,
        "emitted": False,
        "is_main": is_main,
    }

    if is_main and name == "task":
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        bound_step_id = parsed_sid or router.step_id_for_tool(tcid)
        raw_st = raw_args.get("subagent_type", "")
        subagent_type = raw_st.strip() if isinstance(raw_st, str) else ""
        if subagent_type:
            router.register_task_spawn(
                tcid,
                subagent_type,
                step_id=bound_step_id,
            )
        await _ensure_task_delegation_card(
            adapter,
            lookup_id=tcid,
            parsed_args=enrich_task_delegation_args(
                adapter,
                tcid,
                raw_args,
                pending_tool_calls_lc=pending_tool_calls_lc,
            ),
            show_tool_ui=show_tool_ui,
            pending_tool_calls_lc=pending_tool_calls_lc,
        )
        return True

    if is_main:
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        bound_step_id = parsed_sid or router.step_id_for_tool(tcid)
        if bound_step_id:
            step_w = adapter._current_step_messages.get(bound_step_id)
            if step_w is not None:
                if step_w.has_tool_call_row(tcid):
                    step_w.update_tool_args(tcid, raw_args)
                else:
                    step_w.add_tool_call(tcid, name, raw_args)
                adapter._tool_to_step[tcid] = step_w

    card = adapter._current_tool_messages.get(tcid) or adapter._tool_display_by_call_id.get(tcid)
    if isinstance(card, ToolCallMessage):
        card.refresh_tool_args(raw_args)

    return True
