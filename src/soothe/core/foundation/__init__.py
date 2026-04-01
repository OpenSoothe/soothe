"""Framework-wide base primitives for Soothe.

Contains the foundational types used across all soothe layers:
- ``base_events`` — ``SootheEvent`` and its domain sub-classes
- ``types`` — workspace security constants (``INVALID_WORKSPACE_DIRS``)
- ``verbosity_tier`` — ``VerbosityTier`` enum and event classification helpers
"""

from soothe.core.foundation.base_events import (
    ErrorEvent,
    LifecycleEvent,
    OutputEvent,
    ProtocolEvent,
    SootheEvent,
    SubagentEvent,
)
from soothe.core.foundation.types import INVALID_WORKSPACE_DIRS
from soothe.core.foundation.verbosity_tier import (
    ProgressCategory,
    VerbosityLevel,
    VerbosityTier,
    classify_custom_event,
    classify_event_to_tier,
    should_show,
)

__all__ = [
    "INVALID_WORKSPACE_DIRS",
    "ErrorEvent",
    "LifecycleEvent",
    "OutputEvent",
    "ProgressCategory",
    "ProtocolEvent",
    "SootheEvent",
    "SubagentEvent",
    "VerbosityLevel",
    "VerbosityTier",
    "classify_custom_event",
    "classify_event_to_tier",
    "should_show",
]
