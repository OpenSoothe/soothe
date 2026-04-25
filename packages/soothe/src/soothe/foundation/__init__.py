"""Framework-wide base primitives for Soothe.

Includes former `core.foundation` types, assistant text helpers (daemon/UX),
and slash-command dispatch (daemon/TUI).

Note: Event types, verbosity, and internal helpers are now imported from soothe_sdk (v0.4.0).
"""

from soothe_sdk.client import VerbosityLevel
from soothe_sdk.core.events import (
    ErrorEvent,
    LifecycleEvent,
    OutputEvent,
    ProtocolEvent,
    SootheEvent,
    SubagentEvent,
)
from soothe_sdk.core.verbosity import (
    VerbosityTier,
    should_show,
)
from soothe_sdk.utils import INVALID_WORKSPACE_DIRS
from soothe_sdk.ux import (
    INTERNAL_JSON_KEYS,
    classify_event_to_tier,
    strip_internal_tags,
)

from soothe.foundation.ai_message import extract_text_from_ai_message

__all__ = [
    "INTERNAL_JSON_KEYS",
    "INVALID_WORKSPACE_DIRS",
    "ErrorEvent",
    "LifecycleEvent",
    "OutputEvent",
    "ProtocolEvent",
    "SootheEvent",
    "SubagentEvent",
    "VerbosityLevel",
    "VerbosityTier",
    "classify_event_to_tier",
    "extract_text_from_ai_message",
    "should_show",
    "strip_internal_tags",
]
