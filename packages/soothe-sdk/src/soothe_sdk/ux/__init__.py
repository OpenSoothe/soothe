"""Display and UX concerns for event processing.

This package provides UX types, event classification logic,
internal text processing utilities, loop-tagged assistant output helpers,
and subagent helpers.
"""

from soothe_sdk.ux.classification import classify_event_to_tier
from soothe_sdk.ux.internal import INTERNAL_JSON_KEYS, strip_internal_tags
from soothe_sdk.ux.loop_stream import LOOP_ASSISTANT_OUTPUT_PHASES, assistant_output_phase
from soothe_sdk.ux.subagent_progress import get_subagent_name_from_event
from soothe_sdk.ux.types import ESSENTIAL_EVENT_TYPES

__all__ = [
    # Loop assistant output (``mode="messages"`` + ``phase``; RFC-614 / IG-317)
    "LOOP_ASSISTANT_OUTPUT_PHASES",
    "assistant_output_phase",
    # Classification
    "classify_event_to_tier",
    # Internal filtering
    "strip_internal_tags",
    "INTERNAL_JSON_KEYS",
    # Subagent helpers
    "get_subagent_name_from_event",
    # Essential types
    "ESSENTIAL_EVENT_TYPES",
]
