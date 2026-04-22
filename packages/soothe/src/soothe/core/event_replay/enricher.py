"""Event enrichment with CoreAgent checkpoint details.

Enriches reconstructed event stream with message details from
CoreAgent checkpoints for richer TUI display.

RFC-411: Event Stream Replay
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def enrich_events_with_coreagent_details(
    events: list[dict[str, Any]],
    checkpointer_thread_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Enrich events with CoreAgent checkpoint details.

    For each event with checkpoint_id:
    1. Look up thread_id → checkpointer
    2. Load CoreAgent checkpoint metadata
    3. Add checkpoint_ref metadata (message count, estimated tokens)

    Args:
        events: Reconstructed event stream.
        checkpointer_thread_map: Map thread_id → checkpointer instance.

    Returns:
        Enriched event stream with checkpoint_ref metadata.
    """
    enriched_events = []

    for event in events:
        enriched_event = dict(event)

        # Enrich events with checkpoint references
        if "checkpoint_id" in event and "thread_id" in event:
            thread_id = event["thread_id"]
            checkpoint_id = event["checkpoint_id"]

            # Get checkpointer for this thread
            checkpointer = checkpointer_thread_map.get(thread_id)

            if checkpointer:
                try:
                    # Load checkpoint tuple (lightweight metadata fetch)
                    checkpoint_tuple = await checkpointer.aget_tuple(
                        {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
                    )

                    if checkpoint_tuple and checkpoint_tuple.checkpoint:
                        # Extract message details
                        channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
                        messages = channel_values.get("messages", [])

                        # Estimate token count (rough approximation: 4 chars per token)
                        estimated_tokens = sum(
                            len(str(m.get("content", ""))) // 4
                            for m in messages
                            if isinstance(m, dict)
                        )

                        # Add enrichment metadata
                        enriched_event["checkpoint_ref"] = {
                            "message_count": len(messages),
                            "estimated_tokens": estimated_tokens,
                            "thread_id": thread_id,
                            "checkpoint_id": checkpoint_id,
                        }

                except Exception as e:
                    logger.debug(
                        "Failed to enrich event %s with checkpoint details: %s",
                        event.get("type"),
                        str(e),
                    )

        enriched_events.append(enriched_event)

    logger.info("Enriched %d events with checkpoint details", len(enriched_events))

    return enriched_events


__all__ = ["enrich_events_with_coreagent_details"]
