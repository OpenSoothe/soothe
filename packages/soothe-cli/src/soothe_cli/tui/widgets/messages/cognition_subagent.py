"""SubAgent/Task delegation card widget (IG-513, RFC-628 Part II).

Subagent cards appear immediately after their parent step card, showing
tool activity for delegated tasks. They subclass CognitionStepMessage
with a simplified lifecycle and SubAgent-specific header text.
"""

from __future__ import annotations

from time import time
from typing import Any

from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header


def create_subagent_card(
    step_id: str,
    description: str,
    subagent_type: str,
    parent_step_id: str,
    parent_task_key: str,
    task_idx: int = 0,
    **kwargs: Any,
) -> Any:
    """Factory function to create a SubAgent card widget.

    This creates a CognitionStepMessage instance with SubAgent-specific
    fields initialized. The caller is responsible for mounting the widget.

    Args:
        step_id: Parent step ID (same as parent step card, for row classification).
        description: Task description from tool args.
        subagent_type: Subagent type name (e.g., "deep_research", "browser_use").
        parent_step_id: ID of the parent step card.
        parent_task_key: Key to match the task row on the parent step.
        task_idx: Task index within the step (used for filtering subgraph rows).
        **kwargs: Additional arguments for CognitionStepMessage.

    Returns:
        CognitionStepMessage instance configured as a SubAgent card.
    """
    from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage

    # Create base step card with parent step ID (for row classification)
    card = CognitionStepMessage(
        step_id=step_id,
        description=description,
        **kwargs,
    )

    # Inject SubAgent mixin fields
    card._subagent_type = str(subagent_type or "?").strip() or "?"
    card._parent_step_id = str(parent_step_id or "").strip()
    card._parent_task_key = str(parent_task_key or "").strip()
    card._subagent_task_idx = task_idx  # For filtering rows by task index
    card._status = "running"
    card._start_time = time()

    # Replace header method with SubAgent version
    card._step_header_content = lambda: _assemble_card_header(
        card,
        f"{card._subagent_type}({description})",
        status=getattr(card, "_status", "running"),
        spinner_position=getattr(card, "_spinner_position", 0),
        animate_running=getattr(card, "_status", "") == "running",
    )

    def sync_status_to_step(step_widget: Any, success: bool) -> None:
        """Update parent step's task row icon when this SubAgent completes."""
        if not card._parent_task_key:
            return
        sync_fn = getattr(step_widget, "_sync_task_row_status_from_subagent", None)
        if callable(sync_fn):
            sync_fn(card._parent_task_key, success)

    card.sync_status_to_step = sync_status_to_step  # type: ignore[attr-defined]

    # Override _build_row_index to filter by task_idx
    from soothe_cli.tui.widgets.messages.cognition_step_activity import (
        StepRowIndex,
        count_distinct_tool_call_ids,
    )

    def _subagent_build_row_index(self: Any) -> StepRowIndex:
        """Build row index filtered to only include rows for this task_idx.

        IG-513: For SubAgent cards, type 't' subgraph tools are treated as
        main_tools for display purposes (they're the primary activity).
        """
        from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

        from soothe_cli.tui.widgets.messages.cognition_step_activity import (
            is_task_metadata_only_tool_row,
        )

        # Filter rows to only include subgraph tools for this task
        filtered_rows = []
        for row in self._rows:
            tcid = str(row.tool_call_id).strip()
            if not tcid:
                continue
            if is_task_metadata_only_tool_row(row):
                continue
            _, type_code, idx, _ = parse_unified_tool_call_id(tcid)
            # Only include type=t rows with matching task_idx
            if type_code == "t" and idx == self._subagent_task_idx:
                filtered_rows.append(row)

        # IG-513: For SubAgent cards, filtered subgraph tools become main_tools
        # (they're the primary activity, not nested children)
        return StepRowIndex(
            task_delegations=[],  # No task delegations inside SubAgent
            main_tools=filtered_rows,  # Subgraph tools become main activity
            total_tool_count=count_distinct_tool_call_ids(filtered_rows),
            main_tool_count=len(filtered_rows),
            task_delegation_count=0,
        )

    card._build_row_index = lambda: _subagent_build_row_index(card)

    return card


__all__ = [
    "create_subagent_card",
]
