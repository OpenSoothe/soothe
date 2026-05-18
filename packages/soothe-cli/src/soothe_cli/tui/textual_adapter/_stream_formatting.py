"""Display/formatting utilities for the TUI streaming adapter."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_cli.tui.file_ops import FileOpTracker
    from soothe_cli.tui.textual_adapter._adapter import TextualUIAdapter

from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.utils import get_tool_display_name
from soothe_sdk.ux.task_namespace import (
    TaskScope,
    parse_unified_tool_call_id,
    row_key_for_subgraph_tool,
    scoped_subgraph_tool_key,
)

from soothe_cli.cli.stream.display_line import DisplayLine
from soothe_cli.shared.events.essential_events import is_essential_progress_event_type
from soothe_cli.shared.tools.message_processing import format_tool_call_args
from soothe_cli.shared.tools.tool_call_resolution import (
    merge_tool_display_args,
    tool_args_meaningful,
)
from soothe_cli.tui._session_stats import SessionStats
from soothe_cli.tui.formatting import format_duration
from soothe_cli.tui.step_task_routing import StepTaskRouter
from soothe_cli.tui.widgets.messages import CognitionStepMessage, ToolCallMessage


def _is_summarization_chunk(metadata: dict | None) -> bool:
    """Check if a message chunk is from summarization middleware.

    The summarization model is invoked with
    `config={"metadata": {"lc_source": "summarization"}}`
    (see `langchain.agents.middleware.summarization`), which
    LangChain's callback system merges into the stream metadata dict.

    Args:
        metadata: The metadata dict from the stream chunk.

    Returns:
        Whether the chunk is from summarization and should be filtered.
    """
    if metadata is None:
        return False
    return metadata.get("lc_source") == "summarization"


def print_usage_table(
    stats: SessionStats,
    wall_time: float,
    console: Any,
) -> None:
    """Print a model-usage stats table to a Rich console.

    When the session spans multiple models each gets its own row with a
    totals row appended; single-model sessions show one row.

    Args:
        stats: Cumulative session stats.
        wall_time: Total wall-clock time in seconds.
        console: Rich console for output.
    """
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


def _format_display_line_for_tui(line: DisplayLine) -> str:
    """Serialize pipeline ``DisplayLine`` for TUI widgets.

    Leading spaces encode parent/child layout (step result vs step header, etc.).
    Strips only newline separators and trailing whitespace.
    """
    return line.format().lstrip("\n").rstrip()


def _format_progress_event_lines_for_tui(
    event_data: dict[str, Any],
    namespace: tuple[str, ...],
    *,
    pipeline: Any,
    task_scope: TaskScope | None = None,
) -> list[str]:
    """Format progress events with the same pipeline as CLI.

    ``StreamDisplayPipeline`` applies verbosity tiers (curated ``soothe.subagent.*`` at NORMAL).
    """
    event_type = str(event_data.get("type", ""))

    # Essential progress + curated subagent wire events
    if is_essential_progress_event_type(event_type) or event_type.startswith("soothe.subagent."):
        event_for_pipeline = dict(event_data)
        event_for_pipeline["namespace"] = list(namespace)
        if task_scope:
            event_for_pipeline["task_scope"] = task_scope
        lines = pipeline.process(event_for_pipeline)

        rendered: list[str] = []
        for line in lines:
            line_text = _format_display_line_for_tui(line)
            if line_text:
                rendered.append(line_text)
        return rendered

    return []


def _format_task_scoped_tool_invocation_line(
    task_scope: TaskScope,
    tool_name: str,
    tool_args: dict[str, Any],
) -> str:
    """One stderr-style line for Task subgraph tools (⚙ prefix, display name, args)."""
    from soothe_cli.cli.stream.task_scope import format_task_scope_prefix

    display_name = get_tool_display_name(tool_name)
    raw_fb = tool_args.get("_raw", "")
    raw_fallback = raw_fb if isinstance(raw_fb, str) else ""
    args_str = format_tool_call_args(tool_name, {"args": tool_args, "_raw": raw_fallback})
    core = f"{display_name}({args_str})"
    tcid, st = task_scope[0], task_scope[1]
    core = f"{format_task_scope_prefix(tcid, st)} {core}"
    return f"⚙ {core}"


def _raw_tool_content_for_presentation(message: Any) -> str:
    """Serialize tool message body for ``PresentationEngine.format_tool_result_status_line``."""
    from collections.abc import Mapping

    from langchain_core.messages import ToolMessage

    from soothe_cli.shared.tools.tool_message_format import format_tool_message_content

    if isinstance(message, ToolMessage):
        return format_tool_message_content(getattr(message, "content", ""))
    if isinstance(message, Mapping):
        return format_tool_message_content(dict(message).get("content"))
    return ""


_TASK_DESC_KEYS = ("description", "prompt", "task", "instruction")


def _resolve_existing_subgraph_row_key(parent: Any, row_key: str) -> str:
    """Return the row key if it exists on parent (IG-418: unified IDs only)."""
    key = str(row_key).strip()
    if not key:
        return key
    # IG-418: Unified IDs are canonical; no legacy fallback needed
    return key


def canonical_subgraph_tool_ids(
    ns_key: tuple[str, ...],
    raw_tool_call_id: str,
    *,
    task_scope: TaskScope | None,
) -> tuple[str, str]:
    """Return ``(merge_lookup_id, row_key)`` for a subgraph tool invocation.

    When the execute step is known, ``row_key`` uses unified ``{step}:t{n}:{tool}`` form
    so pending buffers, wire updates, and task-card rows share one id.
    """
    raw = str(raw_tool_call_id).strip()
    if not raw:
        return "", ""
    row_key = row_key_for_subgraph_tool(ns_key, raw, task_scope=task_scope)
    _, type_code, _, _ = parse_unified_tool_call_id(row_key)
    if type_code == "t":
        return row_key, row_key
    return raw, row_key


def refresh_subgraph_tool_rows_from_overlay(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    ns_key: tuple[str, ...],
    streaming_overlay: dict[str, dict[str, Any]],
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    message: Any = None,
) -> None:
    """Push overlay kwargs onto existing task-card tool rows when they arrive late.

    IG-418: Only process tool rows that belong to the current namespace.
    Parallel execution means multiple namespaces share streaming_overlay, but each
    namespace should only refresh its own tool rows.
    """
    from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

    if not ns_key or not streaming_overlay:
        return
    # Get the task scope for this namespace to filter relevant tool_call_ids
    ts = router.resolve_task_scope(ns_key)
    if ts is None:
        return
    step_id = ts[2] if ts else ""
    if not step_id:
        return

    for tcid, oargs in streaming_overlay.items():
        if not isinstance(oargs, dict) or not oargs:
            continue
        parsed_sid, type_code, _, _ = parse_unified_tool_call_id(str(tcid))
        if type_code != "t":
            continue
        # IG-418: Only process tool rows for this namespace's step
        if parsed_sid != step_id:
            continue
        merged = merge_tool_display_args(
            str(tcid),
            block_args=oargs,
            streaming_overlay=streaming_overlay,
            pending_tool_calls_lc=pending_tool_calls_lc,
            message=message,
        )
        if refresh_subgraph_parent_tool_row(
            adapter,
            router,
            ns_key=ns_key,
            lookup_id=str(tcid),
            parsed_args=merged,
        ):
            import logging as _logging

            _logging.getLogger(__name__).debug(
                "Subagent tool row args refreshed from overlay: id=%s keys=%s",
                tcid,
                sorted(merged.keys()) if isinstance(merged, dict) else [],
            )


def refresh_subgraph_parent_tool_row(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    ns_key: tuple[str, ...],
    lookup_id: str,
    parsed_args: dict[str, Any],
) -> bool:
    """Update an existing task-card tool row when fuller args arrive on a later chunk."""
    from soothe_cli.shared.tools.tool_call_resolution import tool_args_meaningful

    if not tool_args_meaningful(parsed_args):
        return False
    ts = router.resolve_task_scope(ns_key)
    _merge_id, row_key = canonical_subgraph_tool_ids(ns_key, str(lookup_id).strip(), task_scope=ts)
    if not row_key:
        return False
    parent = (
        router.resolve_parent(
            ts,
            step_cards=adapter._current_step_messages,
            tool_display_by_call_id=adapter._tool_display_by_call_id,
        )
        if ts
        else None
    )
    if parent is None:
        parent = router.resolve_task_parent_for_unified_inner_tool(
            str(lookup_id).strip(),
            tool_display_by_call_id=adapter._tool_display_by_call_id,
        )
    if parent is None:
        return False
    resolved_key = _resolve_existing_subgraph_row_key(parent, row_key)
    if not getattr(parent, "has_tool_call_row", lambda _x: False)(resolved_key):
        return False
    update_fn = getattr(parent, "update_tool_args", None)
    if not callable(update_fn):
        return False
    update_fn(resolved_key, parsed_args)
    return True


def alias_subgraph_pending_and_overlay(
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    streaming_overlay: dict[str, dict[str, Any]],
    router: StepTaskRouter,
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
        # IG-418: Unified IDs are canonical; single alias only
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
    """Use execute-step prose when the model has not streamed task kwargs yet."""
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
    """Merge stream sources and fall back to step description for task cards."""
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


async def sync_pending_step_cards_from_plan(
    adapter: TextualUIAdapter,
    *,
    steps: list[dict[str, Any]],
) -> None:
    """Mount step cards in ``pending`` state for planned steps not yet executing.

    Dependency-blocked steps appear here before ``step.started``; ready steps transition
    to running when execution begins.
    """
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


def _sync_task_delegation_step_row(
    adapter: TextualUIAdapter,
    *,
    lookup_id: str,
    display_args: dict[str, Any],
    raw_args: str = "",
    bound_step_id: str = "",
) -> bool:
    """Mirror the main-graph ``task`` delegation on the execute step card.

    Inner subagent tools stay on the dedicated ``ToolCallMessage`` task card; the step
    card gets a summary row (``explore: …``) so parallel execute waves show delegation
    activity next to other step-level tools.
    """
    import logging as _logging

    _log = _logging.getLogger(__name__)
    tcid = str(lookup_id).strip()
    if not tcid:
        return False
    sid = (bound_step_id or "").strip()
    if not sid:
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        sid = parsed_sid or ""
    if not sid:
        return False
    step_w = adapter._current_step_messages.get(sid)
    if step_w is None:
        return False
    row_args = dict(display_args or {})
    if raw_args:
        row_args.setdefault("_raw", raw_args)
    if step_w.has_tool_call_row(tcid):
        if row_args:
            step_w.update_tool_args(tcid, row_args)
    else:
        step_w.add_tool_call(tcid, "task", row_args, raw_args=raw_args)
        _log.debug(
            "Task delegation row on step card: id=%s step_id=%s",
            tcid,
            sid,
        )
    adapter._tool_to_step[tcid] = step_w
    # ``tool_display_by_call_id`` stays on the task card for subgraph parent resolution.
    return True


async def _ensure_task_delegation_card(
    adapter: TextualUIAdapter,
    *,
    lookup_id: str,
    parsed_args: dict[str, Any],
    show_tool_ui: bool,
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
    pending_tool_calls_lc: dict[str, dict[str, Any]] | None = None,
) -> ToolCallMessage | None:
    """Mount or refresh a standalone Task subagent card (not a step row)."""
    if not show_tool_ui or not lookup_id:
        return None
    display_args = enrich_task_delegation_args(
        adapter,
        lookup_id,
        parsed_args,
        streaming_overlay=streaming_overlay,
        pending_tool_calls_lc=pending_tool_calls_lc,
    )
    if not _task_args_has_description(display_args) and not tool_args_meaningful(display_args):
        return None
    existing = adapter._current_tool_messages.get(
        lookup_id
    ) or adapter._tool_display_by_call_id.get(lookup_id)
    parsed_sid, _, _, _ = parse_unified_tool_call_id(lookup_id)
    if isinstance(existing, ToolCallMessage):
        if display_args:
            existing.refresh_tool_args(display_args)
        _sync_task_delegation_step_row(
            adapter,
            lookup_id=lookup_id,
            display_args=display_args,
            bound_step_id=parsed_sid or "",
        )
        return existing
    task_card = ToolCallMessage("task", display_args, tool_call_id=lookup_id)
    await adapter._mount_message(task_card)
    task_card.set_running()
    adapter._current_tool_messages[lookup_id] = task_card
    adapter._tool_display_by_call_id[lookup_id] = task_card
    raw = ""
    if pending_tool_calls_lc:
        pend = pending_tool_calls_lc.get(lookup_id)
        if isinstance(pend, dict):
            raw = str(pend.get("args_str", ""))
    _sync_task_delegation_step_row(
        adapter,
        lookup_id=lookup_id,
        display_args=display_args,
        raw_args=raw,
        bound_step_id=parsed_sid or "",
    )
    return task_card


def _is_step_level_task_tool_id(tool_call_id: str) -> bool:
    """True for unified main-graph ``task`` delegation ids (``{step}:s:task…``)."""
    _, type_code, _, tool_info = parse_unified_tool_call_id(tool_call_id)
    if type_code != "s":
        return False
    head = (tool_info or "").split(":")[0].split(".")[0]
    return head == "task"


def _task_tool_call_ids_for_step(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    step_id: str,
    *,
    pending_tool_calls_lc: dict[str, dict[str, Any]] | None = None,
) -> set[str]:
    """Collect task delegation tool_call_ids associated with an execute step."""
    sid = step_id.strip()
    if not sid:
        return set()
    out: set[str] = set()
    scope = router._spawns_by_step_id.get(sid)
    if scope and scope[0]:
        out.add(str(scope[0]))
    for tcid in list((pending_tool_calls_lc or {}).keys()):
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        if parsed_sid == sid and _is_step_level_task_tool_id(tcid):
            out.add(tcid)
    for tcid in adapter._current_tool_messages:
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        if parsed_sid == sid and _is_step_level_task_tool_id(tcid):
            out.add(tcid)
    for tcid in adapter._tool_display_by_call_id:
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        if parsed_sid == sid and _is_step_level_task_tool_id(tcid):
            out.add(tcid)
    return out


async def refresh_task_cards_for_step(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    step_id: str,
    *,
    streaming_overlay: dict[str, dict[str, Any]] | None,
    pending_tool_calls_lc: dict[str, dict[str, Any]] | None,
    show_tool_ui: bool,
) -> None:
    """Mount or refresh task cards once the step card exists (step description fallback)."""
    import logging as _logging

    if not show_tool_ui:
        return
    _log = _logging.getLogger(__name__)
    pending = pending_tool_calls_lc or {}
    overlay = streaming_overlay
    if overlay is None and pending:
        from langchain_core.messages import AIMessageChunk

        from soothe_cli.shared.tools.tool_call_resolution import build_streaming_args_overlay

        overlay = build_streaming_args_overlay(AIMessageChunk(content=""), pending)
    overlay = overlay or {}
    for tcid in _task_tool_call_ids_for_step(
        adapter, router, step_id, pending_tool_calls_lc=pending
    ):
        display_args = enrich_task_delegation_args(
            adapter,
            tcid,
            overlay.get(tcid, {}),
            streaming_overlay=overlay,
            pending_tool_calls_lc=pending,
        )
        if not _task_args_has_description(display_args) and not tool_args_meaningful(display_args):
            continue
        card = await _ensure_task_delegation_card(
            adapter,
            lookup_id=tcid,
            parsed_args=display_args,
            show_tool_ui=show_tool_ui,
            streaming_overlay=overlay,
            pending_tool_calls_lc=pending,
        )
        if card is not None:
            _log.debug(
                "Task card refreshed for step: step_id=%s tool_call_id=%s",
                step_id,
                tcid,
            )


async def sync_task_delegation_cards_from_stream(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    streaming_overlay: dict[str, dict[str, Any]],
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    show_tool_ui: bool,
) -> None:
    """Refresh task delegation cards whenever streaming overlay gains task kwargs."""
    import logging as _logging

    if not show_tool_ui:
        return
    _log = _logging.getLogger(__name__)
    for tcid, overlay_args in streaming_overlay.items():
        if not _is_step_level_task_tool_id(tcid):
            continue
        if not tool_args_meaningful(overlay_args):
            continue
        step_id, _, _, _ = parse_unified_tool_call_id(tcid)
        raw_st = overlay_args.get("subagent_type", "")
        subagent_type = raw_st.strip() if isinstance(raw_st, str) else ""
        router.register_task_spawn(
            tcid,
            subagent_type or "?",
            step_id=step_id or router.step_id_for_tool(tcid),
        )
        card = await _ensure_task_delegation_card(
            adapter,
            lookup_id=tcid,
            parsed_args=overlay_args,
            show_tool_ui=show_tool_ui,
            streaming_overlay=streaming_overlay,
            pending_tool_calls_lc=pending_tool_calls_lc,
        )
        if card is not None:
            _log.debug(
                "Task card synced from stream overlay: id=%s keys=%s",
                tcid,
                sorted(overlay_args.keys()),
            )


async def _ensure_early_tool_row_mount(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    lookup_id: str,
    buffer_name: str,
    parsed_args: dict[str, Any],
    raw_args: str,
    ns_key: tuple[str, ...],
    is_main_agent: bool,
    show_tool_ui: bool,
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    file_op_tracker: FileOpTracker,
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Mount or refresh a tool row as soon as ``tool_call_id`` and name are known.

    Uses empty args when kwargs are still streaming so step/task cards update in real time.
    """
    import logging as _logging

    if not show_tool_ui or not lookup_id or not buffer_name:
        return False

    _log = _logging.getLogger(__name__)

    if is_main_agent and buffer_name == "task":
        parsed_step_id, _, _, _ = parse_unified_tool_call_id(lookup_id)
        bound_step_id = parsed_step_id or router.step_id_for_tool(lookup_id)
        raw_st = parsed_args.get("subagent_type", "")
        subagent_type = raw_st.strip() if isinstance(raw_st, str) else ""
        router.register_task_spawn(
            lookup_id,
            subagent_type or "?",
            step_id=bound_step_id,
        )
        if adapter._set_spinner:
            await adapter._set_spinner("Tools")
        display_args = enrich_task_delegation_args(
            adapter,
            lookup_id,
            parsed_args,
            streaming_overlay=streaming_overlay,
            pending_tool_calls_lc=pending_tool_calls_lc,
        )
        task_card = await _ensure_task_delegation_card(
            adapter,
            lookup_id=lookup_id,
            parsed_args=display_args,
            show_tool_ui=show_tool_ui,
            streaming_overlay=streaming_overlay,
            pending_tool_calls_lc=pending_tool_calls_lc,
        )
        if task_card is not None:
            _log.debug(
                "Task delegation card mounted early: id=%s step_id=%s",
                lookup_id,
                bound_step_id,
            )
            return True
        return False

    if is_main_agent:
        parsed_sid, _, _, _ = parse_unified_tool_call_id(lookup_id)
        bound_step_id = parsed_sid or router.step_id_for_tool(lookup_id)
        if bound_step_id:
            step_w = adapter._current_step_messages.get(bound_step_id)
            if step_w is not None:
                if adapter._set_spinner:
                    await adapter._set_spinner("Tools")
                if not step_w.has_tool_call_row(lookup_id):
                    step_w.add_tool_call(
                        lookup_id,
                        buffer_name,
                        parsed_args,
                        raw_args=raw_args,
                    )
                    adapter._tool_to_step[lookup_id] = step_w
                    _log.debug(
                        "Tool row mounted early on step: name=%s id=%s step_id=%s",
                        buffer_name,
                        lookup_id,
                        bound_step_id,
                    )
                elif parsed_args:
                    step_w.update_tool_args(lookup_id, parsed_args)
                return True
        if buffer_name != "task":
            router.buffer_main_tool(
                lookup_id,
                buffer_name,
                parsed_args,
                raw_args=raw_args,
            )
            adapter._tool_display_by_call_id[lookup_id] = None
            return True
        return False

    if await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        router,
        lookup_id=lookup_id,
        buffer_name=buffer_name,
        parsed_args=parsed_args,
        buffer_id=lookup_id,
        ns_key=ns_key,
        show_tool_ui=show_tool_ui,
        is_main_agent=False,
        pending_tool_calls_lc=pending_tool_calls_lc,
        file_op_tracker=file_op_tracker,
        streaming_overlay=streaming_overlay,
    ):
        return True
    ts_buf = router.resolve_task_scope(ns_key)
    _merge_buf, display_key = canonical_subgraph_tool_ids(ns_key, lookup_id, task_scope=ts_buf)
    if display_key:
        router.buffer_subgraph_tool(
            ns_key=ns_key,
            lookup_id=lookup_id,
            display_key=display_key,
            tool_name=buffer_name,
            args=parsed_args,
            raw_args=raw_args,
        )
    return False


def _try_register_task_scoped_inner_tool_pending(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    lookup_id: str | None,
    buffer_name: str | None,
    parsed_args: dict[str, Any],
    is_main_agent: bool,
    ns_key: tuple[str, ...],
    show_tool_ui: bool,
    presentation: Any,
) -> None:
    """Record pending invocation line for Task subgraph tools (no standalone card)."""
    if not lookup_id or not buffer_name or is_main_agent:
        return
    if buffer_name == "task":
        return
    ts_r = router.resolve_task_scope(ns_key)
    if not ts_r or not ts_r[0]:
        return
    parent = router.resolve_parent(
        ts_r,
        step_cards=adapter._current_step_messages,
        tool_display_by_call_id=adapter._tool_display_by_call_id,
    )
    if parent is None:
        return
    # IG-403: Skip text-based pending line when parent has tool row infrastructure
    # (tool rows render the invocation directly — text fallback would duplicate it).
    if isinstance(parent, ToolCallMessage):
        return
    if not show_tool_ui or not presentation.tier_visible(VerbosityTier.NORMAL):
        return
    row_key = scoped_subgraph_tool_key(ns_key, str(lookup_id))
    adapter._task_inner_tool_pending_lines[row_key] = _format_task_scoped_tool_invocation_line(
        ts_r,
        buffer_name,
        parsed_args,
    )
    adapter._task_inner_tool_start_times[row_key] = time.time()


async def _mount_subagent_inner_tool_row_if_resolved(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    lookup_id: str,
    buffer_name: str | None,
    parsed_args: dict[str, Any],
    buffer_id: Any,
    ns_key: tuple[Any, ...],
    show_tool_ui: bool,
    is_main_agent: bool,
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    file_op_tracker: FileOpTracker,
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Attach a subgraph tool as a row on the parent Task/step card when scope resolves.

    Used for subagent tools when no standalone card is mounted (including IG-300 stream
    elision): :func:`_try_register_task_scoped_inner_tool_pending` skips text fallback for
    ``ToolCallMessage`` parents, so rows must still be registered here.

    Returns:
        True if a parent card was found and the row was attached.
    """
    ts_inner = router.resolve_task_scope(ns_key)
    parent_for_inner = (
        router.resolve_parent(
            ts_inner,
            step_cards=adapter._current_step_messages,
            tool_display_by_call_id=adapter._tool_display_by_call_id,
        )
        if ts_inner
        else None
    )
    if parent_for_inner is None:
        parent_for_inner = router.resolve_task_parent_for_unified_inner_tool(
            str(lookup_id),
            tool_display_by_call_id=adapter._tool_display_by_call_id,
        )
    if (
        not show_tool_ui
        or is_main_agent
        or parent_for_inner is None
        or (buffer_name or "") == "task"
    ):
        return False
    merge_id, row_key = canonical_subgraph_tool_ids(ns_key, str(lookup_id), task_scope=ts_inner)
    tool_name = (buffer_name or "").strip() or "tool"
    merged_args = merge_tool_display_args(
        merge_id or str(lookup_id),
        block_args=parsed_args,
        streaming_overlay=streaming_overlay,
        pending_tool_calls_lc=pending_tool_calls_lc,
        tool_name=tool_name,
    )
    file_op_tracker.start_operation(buffer_name, merged_args, buffer_id)
    if adapter._set_spinner:
        await adapter._set_spinner("Tools")
    raw = ""
    pend = pending_tool_calls_lc.get(merge_id or str(lookup_id))
    if not isinstance(pend, dict):
        pend = pending_tool_calls_lc.get(str(lookup_id))
    # IG-416: Don't fallback to tool_name lookup - each tool_call_id is unique
    # Multiple calls like ls.0, ls.1, ls.2 should NOT share the same pending args
    if isinstance(pend, dict):
        raw = str(pend.get("args_str", ""))
    resolved_row_key = _resolve_existing_subgraph_row_key(parent_for_inner, row_key)
    if getattr(parent_for_inner, "has_tool_call_row", lambda _x: False)(resolved_row_key):
        update_fn = getattr(parent_for_inner, "update_tool_args", None)
        if callable(update_fn):
            update_fn(resolved_row_key, merged_args)
    else:
        parent_for_inner.add_tool_call(
            row_key,
            buffer_name or "tool",
            merged_args,
            raw_args=raw,
        )
    adapter._tool_to_step[row_key] = parent_for_inner
    adapter._tool_display_by_call_id[row_key] = parent_for_inner
    import logging as _logging

    _logging.getLogger(__name__).debug(
        "Subagent tool row on parent: name=%s tool_call_id=%s parent=%s",
        buffer_name,
        lookup_id,
        type(parent_for_inner).__name__,
    )
    return True


async def _flush_router_pending_subgraph_tools(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    show_tool_ui: bool,
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    file_op_tracker: FileOpTracker,
) -> int:
    """Mount subgraph tool rows that were buffered while parent scope was unresolved.

    Returns:
        Count of pending subgraph tools successfully mounted.
    """
    routed: set[str] = set()
    for item in router.pending_subgraph_tools():
        if await _mount_subagent_inner_tool_row_if_resolved(
            adapter,
            router,
            lookup_id=item.lookup_id,
            buffer_name=item.tool_name,
            parsed_args=item.args,
            buffer_id=item.lookup_id,
            ns_key=item.ns_key,
            show_tool_ui=show_tool_ui,
            is_main_agent=False,
            pending_tool_calls_lc=pending_tool_calls_lc,
            file_op_tracker=file_op_tracker,
        ):
            routed.add(item.display_key)
    router.take_routed_subgraph_tools(routed)
    return len(routed)
