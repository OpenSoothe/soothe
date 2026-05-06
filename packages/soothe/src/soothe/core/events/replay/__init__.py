"""Event stream reconstruction for loop reattachment.

Reconstructs chronological event stream from checkpoint tree for
TUI history replay when clients reattach to detached loops.

RFC-411: Event Stream Replay
"""

from __future__ import annotations

from .enricher import enrich_events_with_coreagent_details
from .reconstructor import reconstruct_event_stream

__all__ = [
    "reconstruct_event_stream",
    "enrich_events_with_coreagent_details",
]
