"""Display and UX concerns for event processing.

This package provides UX types, event classification logic,
and internal text processing utilities.
"""

from soothe_sdk.ux.classification import classify_event_to_tier
from soothe_sdk.ux.internal import INTERNAL_JSON_KEYS, strip_internal_tags
from soothe_sdk.ux.types import ESSENTIAL_EVENT_TYPES

__all__ = [
    "ESSENTIAL_EVENT_TYPES",
    "strip_internal_tags",
    "INTERNAL_JSON_KEYS",
    "classify_event_to_tier",
]
