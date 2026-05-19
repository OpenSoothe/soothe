"""Stream helpers for the TUI adapter (step cards and tool-arg state only)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_cli.tui.textual_adapter._adapter import TextualUIAdapter

from soothe_sdk.ux.task_namespace import (
    TaskScope,
    parse_unified_tool_call_id,
    row_key_for_subgraph_tool,
)

from soothe_cli.events.duration_format import format_duration
from soothe_cli.events.tools.tool_call_resolution import merge_tool_display_args
from soothe_cli.tui._session_stats import SessionStats
from soothe_cli.tui.widgets.messages import CognitionStepMessage

_TASK_DESC_KEYS = ("description", "prompt", "task", "instruction")


def _is_summarization_chunk(metadata: dict | None) -> bool:
    """Return True when metadata marks a summarization middleware chunk."""
    if metadata is None:
        return False
    return metadata.get("lc_source") == "summarization"


def print_usage_table(
    stats: SessionStats,
    wall_time: float,
    console: Any,
) -> None:
    """Print a model-usage stats table to a Rich console."""
    from rich.table import Table

    from soothe_cli.tui._session_stats import format_token_count

    has_time = wall_time >= 0.1  # noqa: PLR2004
    if not (stats.request_count or stats.input_tokens or has_time):
        return

    if stats.per_model:
        multi_model = len(stats.per_model) > 1
        table = Table(
            show_header=True,
            header_style="bold",
            box=None,
            padding=(0, 2, 0, 0),
            show_edge=False,
        )
        table.add_column("Model", style="dim")
        table.add_column("Reqs", justify="right", style="dim")
        table.add_column("InputTok", justify="right", style="dim")
        table.add_column("OutputTok", justify="right", style="dim")

        if multi_model:
            for model_name, ms in stats.per_model.items():
                table.add_row(
                    model_name,
                    str(ms.request_count),
                    format_token_count(ms.input_tokens),
                    format_token_count(ms.output_tokens),
                )
            table.add_row(
                "Total",
                str(stats.request_count),
                format_token_count(stats.input_tokens),
                format_token_count(stats.output_tokens),
            )
        else:
            model_label = next(iter(stats.per_model))
            table.add_row(
                model_label,
                str(stats.request_count),
                format_token_count(stats.input_tokens),
                format_token_count(stats.output_tokens),
            )

        console.print()
        console.print("[bold]Usage Stats[/bold]")
        console.print(table)
    if has_time:
        console.print()
        console.print(
            f"Agent active  {format_duration(wall_time)}",
            style="dim",
            highlight=False,
        )


def canonical_subgraph_tool_ids(
    ns_key: tuple[str, ...],
    raw_tool_call_id: str,
    *,
    task_scope: TaskScope | None,
) -> tuple[str, str]:
    """Return ``(merge_lookup_id, row_key)`` for a subgraph tool invocation."""
    raw = str(raw_tool_call_id).strip()
    if not raw:
        return "", ""
    row_key = row_key_for_subgraph_tool(ns_key, raw, task_scope=task_scope)
    _, type_code, _, _ = parse_unified_tool_call_id(row_key)
    if type_code == "t":
        return row_key, row_key
    return raw, row_key


def alias_subgraph_pending_and_overlay(
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    streaming_overlay: dict[str, dict[str, Any]],
    router: Any,
    ns_key: tuple[str, ...],
) -> None:
    """Mirror provider tool-call ids under unified task-level ids when scope is bound."""
    ts = router.resolve_task_scope(ns_key)
    if ts is None:
        return
    for oid, pend in list(pending_tool_calls_lc.items()):
        if not isinstance(pend, dict):
            continue
        merge_id, _row = canonical_subgraph_tool_ids(ns_key, oid, task_scope=ts)
        if not merge_id or merge_id == oid:
            continue
        if merge_id not in pending_tool_calls_lc:
            pending_tool_calls_lc[merge_id] = dict(pend)
        oargs = streaming_overlay.get(oid)
        if isinstance(oargs, dict) and oargs:
            prev = streaming_overlay.get(merge_id)
            if isinstance(prev, dict) and prev:
                merged = dict(prev)
                merged.update(oargs)
                streaming_overlay[merge_id] = merged
            else:
                streaming_overlay[merge_id] = dict(oargs)


def _task_args_has_description(args: dict[str, Any]) -> bool:
    for key in _TASK_DESC_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return True
    return False


def _step_description_for_task_card(adapter: TextualUIAdapter, step_id: str) -> str:
    step_w = adapter._current_step_messages.get(step_id.strip())
    if step_w is None:
        return ""
    desc = getattr(step_w, "_description", None)
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    return ""


def enrich_task_delegation_args(
    adapter: TextualUIAdapter,
    lookup_id: str,
    parsed_args: dict[str, Any],
    *,
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
    pending_tool_calls_lc: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge stream sources and fall back to step description for task delegations."""
    merged = merge_tool_display_args(
        lookup_id,
        block_args=parsed_args,
        streaming_overlay=streaming_overlay,
        pending_tool_calls_lc=pending_tool_calls_lc,
        tool_name="task",
    )
    if _task_args_has_description(merged):
        return merged
    step_id, type_code, _, _ = parse_unified_tool_call_id(lookup_id)
    if type_code != "s" or not step_id:
        return merged
    fallback = _step_description_for_task_card(adapter, step_id)
    if fallback:
        out = dict(merged)
        out.setdefault("description", fallback)
        return out
    return merged


def mark_parallel_plan_step_cards_running(adapter: TextualUIAdapter) -> None:
    """Show all pending plan step cards as running during a parallel execute wave."""
    for widget in adapter._current_step_messages.values():
        if widget._status == "pending":
            widget.set_running()


async def sync_pending_step_cards_from_plan(
    adapter: TextualUIAdapter,
    *,
    steps: list[dict[str, Any]],
    execution_mode: str = "",
) -> None:
    """Mount step cards in ``pending`` state for planned steps not yet executing."""
    planned_ids = {
        str(row.get("id", "")).strip()
        for row in steps
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }
    for sid, widget in list(adapter._current_step_messages.items()):
        if widget._status == "pending" and sid not in planned_ids:
            if widget.is_mounted:
                await widget.remove()
            adapter._current_step_messages.pop(sid, None)
            for ns, bound in list(adapter._step_by_namespace.items()):
                if bound is widget:
                    adapter._step_by_namespace.pop(ns, None)

    for row in steps:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id", "")).strip()
        if not sid or sid in adapter._current_step_messages:
            continue
        desc = str(row.get("description", "")).strip() or "(step)"
        step_widget = CognitionStepMessage(
            step_id=sid,
            description=desc,
            id=f"step-{uuid.uuid4().hex[:8]}",
        )
        await adapter._mount_message(step_widget)
        adapter._current_step_messages[sid] = step_widget

    if execution_mode == "parallel":
        mark_parallel_plan_step_cards_running(adapter)
