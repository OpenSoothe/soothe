"""Map progress ``DisplayLine`` values to plain text for TUI widgets."""

from __future__ import annotations

from typing import Any

from soothe_cli.events.policy.essential_events import is_essential_progress_event_type
from soothe_cli.events.stream.display_line import DisplayLine


def format_display_line_for_tui(line: DisplayLine) -> str:
    """Serialize pipeline ``DisplayLine`` for TUI widgets."""
    return line.format().lstrip("\n").rstrip()


def format_progress_event_lines_for_tui(
    event_data: dict[str, Any],
    namespace: tuple[str, ...],
    *,
    pipeline: Any,
    task_scope: tuple[str, str] | None = None,
) -> list[str]:
    """Format progress events through ``StreamDisplayPipeline``."""
    event_type = str(event_data.get("type", ""))

    if is_essential_progress_event_type(event_type) or event_type.startswith("soothe.subagent."):
        event_for_pipeline = dict(event_data)
        event_for_pipeline["namespace"] = list(namespace)
        if task_scope:
            event_for_pipeline["task_scope"] = task_scope
        lines = pipeline.process(event_for_pipeline)

        rendered: list[str] = []
        for line in lines:
            line_text = format_display_line_for_tui(line)
            if line_text:
                rendered.append(line_text)
        return rendered

    return []
