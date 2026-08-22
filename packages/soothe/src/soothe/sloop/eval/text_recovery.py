"""Recover decompose_task proposals from LLM text output (RFC-905 fail-safe).

When an Eval step's LLM emits continuation subtasks as text/JSON instead of
calling the ``decompose_task`` tool, this module extracts the JSON payload
from the final assistant text and constructs ``DecompositionProposal``
objects so the downstream RECONCILE station can still commit the children.

The recovery is conservative: only well-formed ``{"subtasks": [...]}`` payloads
with at least one valid subtask are accepted. Malformed or missing JSON returns
an empty list — the caller proceeds as if no proposal was found.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from soothe_nano.utils.json_parsing import _extract_balanced_json_object

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask

logger = logging.getLogger(__name__)


def _parse_subtask(item: Any) -> ProposedSubtask | None:
    """Parse one subtask dict into a ProposedSubtask, or None on failure."""
    if not isinstance(item, dict):
        return None
    description = (item.get("description") or "").strip()
    if not description:
        return None
    try:
        return ProposedSubtask.model_validate(item)
    except Exception:
        logger.debug("[eval_recovery] subtask validation failed: %s", item, exc_info=True)
        return None


def recover_proposals_from_text(
    text: str,
    *,
    parent_step_id: str,
) -> list[DecompositionProposal]:
    """Extract DecompositionProposals from LLM text output.

    Scans ``text`` for a JSON object containing a ``subtasks`` array. When
    found and at least one subtask validates, returns a single
    ``DecompositionProposal`` whose ``parent_step_id`` is ``parent_step_id``.

    Args:
        text: Final assistant text from the Eval step stream.
        parent_step_id: Step id of the Eval step (becomes proposal parent).

    Returns:
        List with 0 or 1 DecompositionProposal. Empty when no valid JSON or
        no valid subtasks are found.
    """
    if not text:
        return []

    raw_json = _extract_balanced_json_object(text)
    if not raw_json:
        return []

    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(payload, dict):
        return []

    raw_subtasks = payload.get("subtasks")
    if not isinstance(raw_subtasks, list) or not raw_subtasks:
        return []

    parsed: list[ProposedSubtask] = []
    for item in raw_subtasks:
        sub = _parse_subtask(item)
        if sub is not None:
            parsed.append(sub)

    if not parsed:
        return []

    logger.info(
        "[eval_recovery] recovered %d subtask(s) from text output for step %s",
        len(parsed),
        parent_step_id,
    )
    return [
        DecompositionProposal(
            parent_step_id=parent_step_id,
            subtasks=parsed,
        )
    ]


__all__ = ["recover_proposals_from_text"]
