"""SubAgent card widget factory — intake-only orphan wired subagents.

In-step ``task`` delegations no longer mount a SubAgent card; their activity
stays on the parent step card. This factory remains for orphan (intake-only)
wired invokes that have no parent step task row.
"""

from __future__ import annotations

from time import time
from typing import Any

from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header


def create_subagent_card(
    step_id: str,
    description: str,
    subagent_type: str,
    *,
    task_idx: int = 0,
    **kwargs: Any,
) -> Any:
    """Factory function to create an orphan SubAgent card widget.

    This creates a CognitionStepMessage instance with SubAgent-specific
    fields initialized. The caller is responsible for mounting the widget.

    Args:
        step_id: Display step id (synthetic for orphans).
        description: Task description from tool args.
        subagent_type: Subagent type name (e.g., "deep_research", "browser_use").
        task_idx: Task index within the step (used for filtering subgraph rows).
        **kwargs: Additional arguments for CognitionStepMessage.

    Returns:
        CognitionStepMessage instance configured as a SubAgent card.
    """
    from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage

    card = CognitionStepMessage(
        step_id=step_id,
        description=description,
        **kwargs,
    )

    card._subagent_type = str(subagent_type or "?").strip() or "?"
    card._subagent_task_idx = task_idx
    card._status = "running"
    card._start_time = time()

    card._step_header_content = lambda: _assemble_card_header(
        card,
        f"{card._subagent_type}({description})",
        status=getattr(card, "_status", "running"),
        glyph_override=get_glyphs().subagent_prefix,
        spinner_position=getattr(card, "_spinner_position", 0),
        animate_running=getattr(card, "_status", "") == "running",
    )

    from soothe_cli.tui.widgets.messages.cognition_step_activity import (
        StepRowIndex,
        count_distinct_tool_call_ids,
    )

    def _subagent_build_row_index(self: Any) -> StepRowIndex:
        """Build row index filtered to only include rows for this task_idx.

        For orphan SubAgent cards, type 't' subgraph tools are treated as
        main_tools for display purposes (they're the primary activity).
        """
        from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

        from soothe_cli.tui.widgets.messages.cognition_step_activity import (
            is_task_metadata_only_tool_row,
        )

        filtered_rows = []
        for row in self._rows:
            tcid = str(row.tool_call_id).strip()
            if not tcid:
                continue
            if is_task_metadata_only_tool_row(row):
                continue
            _, type_code, idx, _ = parse_unified_tool_call_id(tcid)
            if type_code == "t" and idx == self._subagent_task_idx:
                filtered_rows.append(row)

        return StepRowIndex(
            task_delegations=[],
            main_tools=filtered_rows,
            children_by_task={},
            total_tool_count=count_distinct_tool_call_ids(filtered_rows),
            main_tool_count=len(filtered_rows),
            task_delegation_count=0,
        )

    card._build_row_index = lambda: _subagent_build_row_index(card)

    return card


__all__ = [
    "create_subagent_card",
]
