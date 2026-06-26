"""SubAgent/Task delegation card widget (IG-629, RFC-628 Part II).

Subagent cards appear immediately after their parent step card, showing
tool activity for delegated tasks. They subclass CognitionStepMessage
with a simplified lifecycle and 🎯 header glyph.
"""

from __future__ import annotations

import logging
from time import time
from typing import TYPE_CHECKING, Any

from textual.content import Content

from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SubAgentMessageMixin:
    """Mixin providing SubAgent-specific header glyph and status sync.

    Applied to CognitionStepMessage instances created as SubAgent cards.
    The parent class handles all activity rendering and lifecycle;
    this mixin overrides only the header and adds step-sync callback.
    """

    _subagent_type: str = ""
    _parent_step_id: str = ""
    _parent_task_key: str = ""

    def _init_subagent_fields(
        self,
        subagent_type: str,
        parent_step_id: str,
        parent_task_key: str,
    ) -> None:
        """Initialize SubAgent-specific fields (call from subclass __init__)."""
        self._subagent_type = str(subagent_type or "?").strip() or "?"
        self._parent_step_id = str(parent_step_id or "").strip()
        self._parent_task_key = str(parent_task_key or "").strip()
        # SubAgent cards are born running (created when task call streams in)
        self._status = "running"
        self._start_time = time()

    def _subagent_header_content(self) -> Content:
        """Header with 🎯 glyph and subagent type prefix."""
        desc = getattr(self, "_description", "") or "(task)"
        label = f"{self._subagent_type}({desc})"
        return _assemble_card_header(self, "🎯 ", label)

    def sync_status_to_step(self, step_widget: Any, success: bool) -> None:
        """Update parent step's task row icon when SubAgent completes.

        Args:
            step_widget: Parent CognitionStepMessage instance.
            success: True for success, False for error.
        """
        if not self._parent_task_key:
            return
        sync_fn = getattr(step_widget, "_sync_task_row_status_from_subagent", None)
        if callable(sync_fn):
            sync_fn(self._parent_task_key, success)


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
        subagent_type: Subagent type name (e.g., "explore", "code-review").
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
        card, "🎯 ", f"{card._subagent_type}({description})"
    )

    # Override _build_row_index to filter by task_idx
    from soothe_cli.tui.widgets.messages.cognition_step_activity import (
        StepRowIndex,
        count_distinct_tool_call_ids,
    )

    def _subagent_build_row_index(self: Any) -> StepRowIndex:
        """Build row index filtered to only include rows for this task_idx.

        IG-629: For SubAgent cards, type 't' subgraph tools are treated as
        main_tools for display purposes (they're the primary activity).
        """
        from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

        # Filter rows to only include subgraph tools for this task
        filtered_rows = []
        for row in self._rows:
            tcid = str(row.tool_call_id).strip()
            if not tcid:
                continue
            _, type_code, idx, _ = parse_unified_tool_call_id(tcid)
            # Only include type=t rows with matching task_idx
            if type_code == "t" and idx == self._subagent_task_idx:
                filtered_rows.append(row)

        # IG-629: For SubAgent cards, filtered subgraph tools become main_tools
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
    "SubAgentMessageMixin",
    "create_subagent_card",
]
