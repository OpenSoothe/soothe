"""Persist LoopRail auto-pick diagnostics under ``jobs/{job_id}/`` (IG-728)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

RAIL_SELECTION_FILENAME = "rail_selection.json"

if TYPE_CHECKING:
    from soothe_autopilot.rails.selector import RailPickResult


def write_rail_selection(
    *,
    jobs_root: Path | None,
    job_id: str,
    pick: RailPickResult,
) -> Path | None:
    """Write ``jobs/{job_id}/rail_selection.json`` for forensics.

    Args:
        jobs_root: Job artifact root (typically ``$SOOTHE_DATA_DIR/jobs``).
        job_id: Root goal / job id.
        pick: Resolved ``RailPickResult`` from submit-time selection.

    Returns:
        Path written, or None when ``jobs_root`` is unset or write fails.
    """
    if jobs_root is None:
        return None
    if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
        return None
    path = Path(jobs_root).expanduser().resolve() / job_id / RAIL_SELECTION_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "rail_id": pick.rail_id,
            "source": pick.source,
            "confidence": pick.confidence,
            "reasoning": (pick.reasoning or "")[:1000],
            "candidates_considered": list(pick.candidates_considered),
            "catalog_hash": pick.catalog_hash,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path
    except OSError:
        logger.debug("Failed to write rail_selection for %s", job_id, exc_info=True)
        return None
