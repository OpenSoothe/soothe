"""Display and UX concerns for event processing.

This package provides UX types, event classification logic,
internal text processing utilities, output event registry,
and subagent helpers.
"""

from soothe_sdk.ux.classification import classify_event_to_tier
from soothe_sdk.ux.internal import INTERNAL_JSON_KEYS, strip_internal_tags
from soothe_sdk.ux.output_events import (
    extract_output_text,
    is_output_event,
    register_output_event,
)
from soothe_sdk.ux.subagent_progress import get_subagent_name_from_event
from soothe_sdk.ux.types import ESSENTIAL_EVENT_TYPES

__all__ = [
    # Output events
    "register_output_event",
    "is_output_event",
    "extract_output_text",
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
