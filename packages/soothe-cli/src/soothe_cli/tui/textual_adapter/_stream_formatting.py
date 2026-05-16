"""Display/formatting utilities for the TUI streaming adapter."""

from __future__ import annotations

import time
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
from soothe_cli.tui._session_stats import SessionStats
from soothe_cli.tui.formatting import format_duration
from soothe_cli.tui.step_task_routing import StepTaskRouter
from soothe_cli.tui.widgets.messages import ToolCallMessage


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


async def _ensure_task_delegation_card(
    adapter: TextualUIAdapter,
    *,
    lookup_id: str,
    parsed_args: dict[str, Any],
    show_tool_ui: bool,
) -> ToolCallMessage | None:
    """Mount or refresh a standalone Task subagent card (not a step row)."""
    if not show_tool_ui or not lookup_id:
        return None
    existing = adapter._current_tool_messages.get(
        lookup_id
    ) or adapter._tool_display_by_call_id.get(lookup_id)
    if isinstance(existing, ToolCallMessage):
        if parsed_args:
            existing.refresh_tool_args(parsed_args)
        return existing
    task_card = ToolCallMessage("task", parsed_args, tool_call_id=lookup_id)
    await adapter._mount_message(task_card)
    task_card.set_running()
    adapter._current_tool_messages[lookup_id] = task_card
    adapter._tool_display_by_call_id[lookup_id] = task_card
    return task_card


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
        task_card = await _ensure_task_delegation_card(
            adapter,
            lookup_id=lookup_id,
            parsed_args=parsed_args,
            show_tool_ui=show_tool_ui,
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
    ):
        return True
    display_key = scoped_subgraph_tool_key(ns_key, lookup_id)
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
    row_key = row_key_for_subgraph_tool(ns_key, str(lookup_id), task_scope=ts_inner)
    file_op_tracker.start_operation(buffer_name, parsed_args, buffer_id)
    if adapter._set_spinner:
        await adapter._set_spinner("Tools")
    raw = ""
    pend = pending_tool_calls_lc.get(str(lookup_id))
    if isinstance(pend, dict):
        raw = str(pend.get("args_str", ""))
    parent_for_inner.add_tool_call(
        row_key,
        buffer_name or "tool",
        parsed_args,
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
