"""Mount non-blocking filesystem change previews in the TUI chat."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from soothe_cli.runtime.state.file_tracker import (
    FILE_CHANGE_TOOLS,
    file_change_action_label,
    file_change_label_from_preview_data,
    file_change_preview_alias_already_shown,
    find_mounted_file_change_widget,
    parse_insert_line_arg,
    parse_line_range_args,
)
from soothe_cli.tui.file_change_renderers import (
    build_file_change_preview,
    update_preview_data_from_record,
)

if TYPE_CHECKING:
    from soothe_cli.runtime.state.file_tracker import FileOperationRecord, FileOpTracker
    from soothe_cli.tui.textual_adapter import TextualUIAdapter

logger = logging.getLogger(__name__)


def textual_widget_id(prefix: str, tool_call_id: str) -> str:
    """Build a Textual-safe widget id from a unified tool call id.

    Unified ids use colons (e.g. ``JWZ_01:s:write_file:23``) which Textual rejects.

    Args:
        prefix: Stable prefix (e.g. ``file-preview``).
        tool_call_id: LangChain / unified tool call id.

    Returns:
        Identifier containing only letters, digits, underscores, and hyphens.
    """
    raw = f"{prefix}-{tool_call_id}"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw)
    if not safe:
        safe = f"{prefix}-unknown"
    if safe[0].isdigit():
        safe = f"_{safe}"
    return safe


async def _register_file_change_widget(
    adapter: TextualUIAdapter,
    widget: Any,
    *,
    tcid: str,
    log_message: str,
    log_args: tuple[Any, ...],
) -> bool:
    """Mount a file-change widget and register it on the adapter."""
    try:
        await adapter._mount_message(widget)
    except asyncio.CancelledError:
        raise
    except Exception:
        adapter._file_change_previews_shown.add(tcid)
        logger.warning("Failed to mount file change preview", exc_info=True)
        return False
    adapter._file_change_previews_shown.add(tcid)
    adapter._file_change_widgets[tcid] = widget
    logger.debug(log_message, *log_args)
    return True


async def mount_file_change_preview(
    adapter: TextualUIAdapter,
    *,
    tool_name: str,
    args: dict[str, Any],
    tool_call_id: str | None,
    assistant_id: str | None,
    file_op_tracker: FileOpTracker | None = None,
) -> None:
    """Mount a preview card once per tool call when args are known.

    Does not block tool execution; duplicates are suppressed via
    ``adapter._file_change_previews_shown``.

    When ``file_op_tracker`` already holds a completed record for this call
    (result-before-preview race), the card is mounted as finalized past tense
    (e.g. ``Edited``) instead of an in-flight ``Editing`` preview.

    Args:
        adapter: Active textual UI adapter for the turn.
        tool_name: Filesystem tool name.
        args: Parsed tool arguments.
        tool_call_id: LangChain tool call id.
        assistant_id: Agent id for path resolution.
        file_op_tracker: Optional tracker with ``recently_completed`` lookups.
    """
    if tool_name not in FILE_CHANGE_TOOLS:
        return
    tcid = str(tool_call_id or "").strip()
    if not tcid or file_change_preview_alias_already_shown(
        adapter._file_change_previews_shown,
        tcid,
        tool_name=tool_name,
    ):
        return
    path_str = str(args.get("file_path") or args.get("path") or "").strip()
    if not path_str and tool_name != "write_file":
        return
    if tool_name == "write_file" and not str(args.get("content") or "").strip():
        return
    if tool_name == "edit_file" and not (
        str(args.get("old_string") or "") or str(args.get("new_string") or "")
    ):
        return
    if tool_name == "edit_file_lines" and parse_line_range_args(args) is None:
        return
    if tool_name == "insert_lines" and parse_insert_line_arg(args) is None:
        return
    if tool_name == "delete_lines" and parse_line_range_args(args) is None:
        return
    if tool_name == "apply_diff" and not str(args.get("diff") or "").strip():
        return

    built = build_file_change_preview(tool_name, args, assistant_id=assistant_id)
    if built is None:
        return
    widget_cls, data = built
    completed = None
    if file_op_tracker is not None:
        completed = file_op_tracker.take_recently_completed(tcid, tool_name=tool_name)
    if completed is not None:
        # Prefer streamed args for edit diffs when the early result has no
        # before/after snapshot; still apply on-disk data when present.
        if completed.diff or (
            completed.tool_name == "write_file" and completed.after_content is not None
        ):
            update_preview_data_from_record(data, completed)
        label = file_change_action_label(completed)
    else:
        label = file_change_label_from_preview_data(tool_name, data)
    widget = widget_cls(data, action_label=label)
    if completed is not None:
        widget._finalized = True
        widget._expanded = False
    widget.id = textual_widget_id("file-preview", tcid)
    if completed is not None:
        log_message = (
            "Mounted completed file change preview (late args) tool=%s tool_call_id=%s path=%s"
        )
    else:
        log_message = "Mounted file change preview tool=%s tool_call_id=%s path=%s"
    await _register_file_change_widget(
        adapter,
        widget,
        tcid=tcid,
        log_message=log_message,
        log_args=(tool_name, tcid, path_str),
    )


async def finalize_file_change_preview(
    adapter: TextualUIAdapter,
    *,
    record: FileOperationRecord,
) -> bool:
    """Upgrade a mounted preview card to its completed state.

    Returns:
        True when an existing preview widget was finalized in place.
    """
    tcid = str(record.tool_call_id or "").strip()
    if not tcid:
        return False
    widget_key, widget = find_mounted_file_change_widget(
        adapter._file_change_widgets,
        tcid,
        tool_name=str(record.tool_name or ""),
    )
    if widget is None:
        logger.debug(
            "No mounted file preview for completion tool=%s tool_call_id=%s keys=%s",
            record.tool_name,
            tcid,
            sorted(adapter._file_change_widgets),
        )
        return False
    await widget.finalize_from_record(record)
    logger.debug(
        "Finalized file change preview tool=%s mounted_key=%s completed_id=%s",
        record.tool_name,
        widget_key,
        tcid,
    )
    return True


async def mount_completed_file_change_preview(
    adapter: TextualUIAdapter,
    *,
    record: FileOperationRecord,
    assistant_id: str | None,
) -> bool:
    """Mount a collapsed completed preview when no in-flight card was shown.

    Returns:
        True when a completed preview card was mounted from the tracker record.
    """
    tool_name = str(record.tool_name or "").strip()
    tcid = str(record.tool_call_id or "").strip()
    if tool_name not in FILE_CHANGE_TOOLS or not tcid:
        return False
    if file_change_preview_alias_already_shown(
        adapter._file_change_previews_shown,
        tcid,
        tool_name=tool_name,
    ):
        return False
    if not record.diff:
        return False

    args = dict(record.args or {})
    built = build_file_change_preview(tool_name, args, assistant_id=assistant_id)
    if built is None:
        return False
    widget_cls, data = built
    update_preview_data_from_record(data, record)
    widget = widget_cls(data, action_label=file_change_action_label(record))
    widget._finalized = True
    widget._expanded = False
    widget.id = textual_widget_id("file-preview", tcid)
    return await _register_file_change_widget(
        adapter,
        widget,
        tcid=tcid,
        log_message="Mounted completed file change preview tool=%s tool_call_id=%s",
        log_args=(tool_name, tcid),
    )


async def complete_file_change_preview(
    adapter: TextualUIAdapter,
    *,
    record: FileOperationRecord,
    assistant_id: str | None,
) -> bool:
    """Finalize an in-flight preview or mount a completed card from the record."""
    if await finalize_file_change_preview(adapter, record=record):
        return True
    return await mount_completed_file_change_preview(
        adapter,
        record=record,
        assistant_id=assistant_id,
    )


def handle_file_change_result_without_active_track(
    tracker: FileOpTracker,
    tool_message: Any,
    *,
    tool_name: str,
    tool_call_id: str | None,
) -> FileOperationRecord | None:
    """DEBUG-log and stash a filesystem tool result that beat the preview mount.

    Returns:
        Stashed :class:`FileOperationRecord` for late mount finalization, or None.
    """
    logger.debug(
        "File-change tool result with no active track tool=%s tool_call_id=%s "
        "(result-before-preview race)",
        tool_name,
        tool_call_id,
    )
    return tracker.stash_untracked_file_change_result(tool_message)
