"""Textual ``Content`` rows for tool call widgets (presentation only)."""

from __future__ import annotations

from typing import Any

from textual.content import Content

from soothe_cli.events.core.presentation_engine import PresentationEngine
from soothe_cli.events.duration_format import format_duration
from soothe_cli.events.tools.tool_labels import (
    format_task_delegation_cli_command,
    format_tool_cli_style_command,
)
from soothe_cli.tui.config import get_glyphs


def format_tool_call_row(
    tool_name: str,
    tool_args: dict[str, Any] | None,
    *,
    phase: str,
    output: str = "",
    duration_ms: int = 0,
    running_spinner: str | None = None,
    running_elapsed_secs: float | None = None,
    branch_glyph: str | None = None,
    is_task_row: bool = False,
) -> Content:
    """One-line tool row: invocation label, arrow, status/result."""
    if phase not in ("pending", "running", "success", "error", "rejected", "skipped"):
        phase = "pending"

    lhs_plain = (
        format_task_delegation_cli_command(tool_name, tool_args)
        if is_task_row
        else format_tool_cli_style_command(tool_name, tool_args)
    )
    tool_prefix = get_glyphs().tool_prefix

    if branch_glyph is not None:
        rest = (
            lhs_plain[len(tool_prefix) :].lstrip()
            if lhs_plain.startswith(tool_prefix)
            else lhs_plain
        )
        lhs = f"{branch_glyph} {rest}"
    else:
        lhs = lhs_plain

    def _cmd_with_spinner(spinner: str) -> str:
        if lhs_plain.startswith(tool_prefix):
            rest = lhs_plain[len(tool_prefix) :].lstrip()
            return f"{spinner} {rest}"
        return f"{spinner} {lhs_plain}"

    arrow = " → "

    if phase == "pending":
        return Content.assemble(lhs, Content.styled(f"{arrow}…", "dim"))

    if phase == "running":
        if branch_glyph is not None:
            if running_elapsed_secs is not None and running_elapsed_secs >= 0:
                dur = format_duration(float(running_elapsed_secs))
                tail = f"{arrow}running ({dur})"
            else:
                tail = f"{arrow}running"
            return Content.assemble(lhs, Content.styled(tail, "dim"))
        spin = running_spinner or get_glyphs().spinner_frames[0]
        cmd = _cmd_with_spinner(spin)
        if running_elapsed_secs is not None and running_elapsed_secs >= 0:
            dur = format_duration(float(running_elapsed_secs))
            tail = f"{arrow}running ({dur})"
        else:
            tail = f"{arrow}running"
        return Content.assemble(cmd, Content.styled(tail, "dim"))

    if phase == "rejected":
        return Content.assemble(lhs, Content.styled(f"{arrow}rejected", "italic"))

    if phase == "skipped":
        return Content.assemble(lhs, Content.styled(f"{arrow}skipped", "dim"))

    presentation = PresentationEngine()
    is_error = phase == "error"
    rhs = presentation.format_tool_result_status_line(
        tool_name,
        output,
        is_error=is_error,
        duration_ms=duration_ms,
    )
    return Content.assemble(lhs, Content.styled(arrow, "dim"), rhs)
