"""Daemon-owned wire event type string constants.

Channel, output, and skillify events were previously declared inline in their
respective modules. They are centralized here so daemon-owned wire types have
a single declaration site, matching the host's ``foundation/events/constants``.

Wire-visible constants shared across packages (strange-loop, stream-end,
memory, policy) remain in ``soothe_sdk.core.events`` (the protocol-contracts
layer); this module owns only daemon-defined types.
"""

from __future__ import annotations

# ============================================================================
# Channel (soothe.channel.*) — inbound user input
# ============================================================================

CHANNEL_MESSAGE_RECEIVED = "soothe.channel.message.received"

# ============================================================================
# Output (soothe.output.*) — agent output for user display
# ============================================================================

OUTPUT_TEXT_COMPLETE = "soothe.output.text.complete"
OUTPUT_TEXT_DELTA = "soothe.output.text.delta"
OUTPUT_TEXT_END = "soothe.output.text.end"
OUTPUT_UI_RENDER = "soothe.output.ui.render"
OUTPUT_PROGRESS = "soothe.output.progress"
OUTPUT_REASONING = "soothe.output.reasoning"

# ============================================================================
# Skillify (soothe.skillify.*) — skill retrieval/indexing lifecycle
# ============================================================================

SKILLIFY_RETRIEVE_COMPLETED = "soothe.skillify.retrieve_completed"
SKILLIFY_INDEX_STARTED = "soothe.skillify.index_started"
SKILLIFY_INDEX_UPDATED = "soothe.skillify.index_updated"
SKILLIFY_INDEX_UNCHANGED = "soothe.skillify.index_unchanged"
SKILLIFY_INDEX_FAILED = "soothe.skillify.index_failed"

__all__ = [
    "CHANNEL_MESSAGE_RECEIVED",
    "OUTPUT_PROGRESS",
    "OUTPUT_REASONING",
    "OUTPUT_TEXT_COMPLETE",
    "OUTPUT_TEXT_DELTA",
    "OUTPUT_TEXT_END",
    "OUTPUT_UI_RENDER",
    "SKILLIFY_INDEX_FAILED",
    "SKILLIFY_INDEX_STARTED",
    "SKILLIFY_INDEX_UNCHANGED",
    "SKILLIFY_INDEX_UPDATED",
    "SKILLIFY_RETRIEVE_COMPLETED",
]
