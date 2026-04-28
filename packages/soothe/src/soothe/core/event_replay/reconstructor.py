"""Event stream reconstruction from checkpoint tree.

Reconstructs chronological event stream from AgentLoop checkpoint data
for TUI history replay on loop reattachment.

RFC-411: Event Stream Replay
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from soothe.cognition.agent_loop.state.persistence.manager import (
    AgentLoopCheckpointPersistenceManager,
)
from soothe.core.event_constants import (
    BRANCH_ANALYZED,
    BRANCH_CREATED,
    BRANCH_RETRY_STARTED,
    ITERATION_COMPLETED,
    ITERATION_STARTED,
    THREAD_SWITCHED,
)

logger = logging.getLogger(__name__)


async def reconstruct_event_stream(
    loop_id: str,
    persistence_manager: AgentLoopCheckpointPersistenceManager,
) -> list[dict[str, Any]]:
    """Reconstruct event stream from checkpoint tree for loop reattachment.

    Process:
    1. Load checkpoint anchors → emit ITERATION_STARTED/COMPLETED events
    2. Load failed branches → emit BRANCH_CREATED/ANALYZED events
    3. Build chronological stream sorted by timestamp

    Args:
        loop_id: AgentLoop identifier.
        persistence_manager: Persistence manager for checkpoint data.

    Returns:
        Chronological event stream (sorted by timestamp).
    """
    # Use timezone-aware minimum for UTC timestamps
    # datetime.min is timezone-naive and cannot be compared with timezone-aware datetimes
    min_timestamp = datetime.min.replace(tzinfo=UTC)

    events = []

    # Load checkpoint anchors (main execution line)
    anchors = await persistence_manager.get_checkpoint_anchors_for_range(loop_id, 0, 10000)

    # Group anchors by iteration
    iterations: dict[int, dict[str, Any]] = {}
    for anchor in anchors:
        iter_num = anchor["iteration"]
        if iter_num not in iterations:
            iterations[iter_num] = {}
        iterations[iter_num][anchor["anchor_type"]] = anchor

    # Emit iteration events
    previous_thread_id = None
    for iter_num in sorted(iterations.keys()):
        iter_data = iterations[iter_num]
        start_anchor = iter_data.get("iteration_start", {})
        end_anchor = iter_data.get("iteration_end", {})

        thread_id = start_anchor.get("thread_id", "unknown")

        # Emit ITERATION_STARTED
        events.append(
            {
                "type": ITERATION_STARTED,
                "timestamp": start_anchor.get("created_at", min_timestamp),
                "iteration": iter_num,
                "thread_id": thread_id,
                "checkpoint_id": start_anchor.get("checkpoint_id"),
                "goal_description": start_anchor.get("goal_description", "Unknown goal"),
            }
        )

        # Check for thread switch
        if previous_thread_id and previous_thread_id != thread_id:
            events.append(
                {
                    "type": THREAD_SWITCHED,
                    "timestamp": start_anchor.get("created_at", min_timestamp),
                    "iteration": iter_num,
                    "from_thread_id": previous_thread_id,
                    "to_thread_id": thread_id,
                }
            )

        previous_thread_id = thread_id

        # Emit ITERATION_COMPLETED
        if end_anchor:
            events.append(
                {
                    "type": ITERATION_COMPLETED,
                    "timestamp": end_anchor.get("created_at", min_timestamp),
                    "iteration": iter_num,
                    "thread_id": thread_id,
                    "checkpoint_id": end_anchor.get("checkpoint_id"),
                    "outcome": end_anchor.get("iteration_status", "unknown"),
                    "duration_ms": end_anchor.get("duration_ms", 0),
                    "tools_executed": end_anchor.get("tools_executed", []),
                }
            )

    # Load failed branches
    branches = await persistence_manager.get_failed_branches_for_loop(loop_id)

    # Emit branch events
    for branch in branches:
        # Emit BRANCH_CREATED (failure detection)
        events.append(
            {
                "type": BRANCH_CREATED,
                "timestamp": branch.get("created_at", min_timestamp),
                "branch_id": branch["branch_id"],
                "iteration": branch["iteration"],
                "thread_id": branch["thread_id"],
                "failure_reason": branch["failure_reason"],
                "root_checkpoint_id": branch["root_checkpoint_id"],
                "failure_checkpoint_id": branch["failure_checkpoint_id"],
            }
        )

        # Emit BRANCH_ANALYZED (LLM analysis complete)
        if branch.get("analyzed_at"):
            events.append(
                {
                    "type": BRANCH_ANALYZED,
                    "timestamp": branch["analyzed_at"],
                    "branch_id": branch["branch_id"],
                    "failure_insights": branch.get("failure_insights", {}),
                    "avoid_patterns": branch.get("avoid_patterns", []),
                    "suggested_adjustments": branch.get("suggested_adjustments", []),
                }
            )

        # Emit BRANCH_RETRY_STARTED (smart retry initiated)
        if branch.get("retry_initiated_at"):
            events.append(
                {
                    "type": BRANCH_RETRY_STARTED,
                    "timestamp": branch["retry_initiated_at"],
                    "branch_id": branch["branch_id"],
                    "retry_iteration": branch.get("retry_iteration"),
                    "learning_applied": branch.get("suggested_adjustments", []),
                }
            )

    # Sort by timestamp (use timezone-aware minimum for UTC timestamps)
    events.sort(key=lambda e: e.get("timestamp", min_timestamp))

    logger.info(
        "Reconstructed %d events for loop %s (%d iterations, %d branches)",
        len(events),
        loop_id,
        len(iterations),
        len(branches),
    )

    return events


__all__ = ["reconstruct_event_stream"]
