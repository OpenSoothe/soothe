"""Loop reattachment handler for history reconstruction.

Handles client reattachment to detached loops by reconstructing
complete event history and replaying to TUI/CLI.

RFC-411: Event Stream Replay
RFC-503: Loop-First User Experience
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.cognition.agent_loop.state.persistence.manager import (
    AgentLoopCheckpointPersistenceManager,
)
from soothe.core.event_constants import HISTORY_REPLAY_COMPLETE, LOOP_REATTACHED
from soothe.core.event_replay import (
    enrich_events_with_coreagent_details,
    reconstruct_event_stream,
)

logger = logging.getLogger(__name__)


async def handle_loop_reattach(
    loop_id: str,
    daemon: Any,
    client_id: Any,
) -> None:
    """Handle loop reattachment: reconstruct history and replay.

    Process:
    1. Load AgentLoop checkpoint data
    2. Reconstruct event stream from checkpoint tree
    3. Enrich with CoreAgent checkpoint details
    4. Send history_replay event to client
    5. Send LOOP_REATTACHED event

    Args:
        loop_id: AgentLoop identifier.
        daemon: Daemon instance (for sending messages).
        client_id: Client connection identifier.
    """
    try:
        logger.info("Handling loop reattachment for %s (client=%s)", loop_id, client_id)

        # Load checkpoint data
        persistence_manager = AgentLoopCheckpointPersistenceManager("sqlite")

        # Reconstruct event stream
        event_stream = await reconstruct_event_stream(loop_id, persistence_manager)

        # Build thread checkpointer map (from daemon's thread registry)
        checkpointer_thread_map = {}
        if hasattr(daemon, "_thread_registry"):
            for thread_id in daemon._thread_registry._threads:
                thread_state = daemon._thread_registry.get(thread_id)
                if thread_state and thread_state.checkpointer:
                    checkpointer_thread_map[thread_id] = thread_state.checkpointer

        # Enrich events with checkpoint details
        enriched_stream = await enrich_events_with_coreagent_details(
            event_stream, checkpointer_thread_map
        )

        # Send history_replay event to client
        await daemon._send_client_message(
            client_id,
            {
                "type": "history_replay",
                "loop_id": loop_id,
                "events": enriched_stream,
                "total_events": len(enriched_stream),
            },
        )

        # Send LOOP_REATTACHED confirmation
        await daemon._send_client_message(
            client_id,
            {
                "type": LOOP_REATTACHED,
                "loop_id": loop_id,
                "timestamp": enriched_stream[-1].get("timestamp") if enriched_stream else None,
            },
        )

        # Send HISTORY_REPLAY_COMPLETE marker
        await daemon._send_client_message(
            client_id,
            {
                "type": HISTORY_REPLAY_COMPLETE,
                "loop_id": loop_id,
            },
        )

        logger.info(
            "Loop reattachment complete: %s (%d events replayed)",
            loop_id,
            len(enriched_stream),
        )

    except Exception as e:
        logger.error(
            "Failed to handle loop reattachment for %s: %s", loop_id, str(e), exc_info=True
        )

        # Send error to client
        await daemon._send_client_message(
            client_id,
            {
                "type": "error",
                "code": "LOOP_REATTACH_FAILED",
                "message": f"Failed to reconstruct loop history: {str(e)}",
                "loop_id": loop_id,
            },
        )


__all__ = ["handle_loop_reattach"]
