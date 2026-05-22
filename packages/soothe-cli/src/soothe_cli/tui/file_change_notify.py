"""Mount non-blocking filesystem change previews in the TUI chat."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe_cli.runtime.state.file_tracker import FILE_CHANGE_TOOLS, parse_line_range_args
from soothe_cli.tui.file_change_renderers import (
    build_file_change_preview,
    file_change_preview_label,
)

if TYPE_CHECKING:
    from soothe_cli.tui.textual_adapter import TextualUIAdapter

logger = logging.getLogger(__name__)


async def mount_file_change_preview(
    adapter: TextualUIAdapter,
    *,
    tool_name: str,
    args: dict[str, Any],
    tool_call_id: str | None,
    assistant_id: str | None,
) -> None:
    """Mount a preview card once per tool call when args are known.

    Does not block tool execution; duplicates are suppressed via
    ``adapter._file_change_previews_shown``.

    Args:
        adapter: Active textual UI adapter for the turn.
        tool_name: Filesystem tool name.
        args: Parsed tool arguments.
        tool_call_id: LangChain tool call id.
        assistant_id: Agent id for path resolution.
    """
    if tool_name not in FILE_CHANGE_TOOLS:
        return
    tcid = str(tool_call_id or "").strip()
    if not tcid or tcid in adapter._file_change_previews_shown:
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

    built = build_file_change_preview(tool_name, args, assistant_id=assistant_id)
    if built is None:
        return
    widget_cls, data = built
    label = file_change_preview_label(tool_name)
    try:
        widget = widget_cls(data, action_label=label)
        widget.id = f"file-preview-{tcid}"
        await adapter._mount_message(widget)
        adapter._file_change_previews_shown.add(tcid)
    except Exception:
        logger.debug("Failed to mount file change preview", exc_info=True)
