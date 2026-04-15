"""Framework-wide base primitives for Soothe.

Includes former ``core.foundation`` types, assistant text helpers (daemon/UX),
and slash-command dispatch (daemon/TUI).

Note: Event types, verbosity, and internal helpers are now imported from soothe_sdk (v0.2.0).
"""

from soothe_sdk import (
    INTERNAL_JSON_KEYS,
    INVALID_WORKSPACE_DIRS,
    ErrorEvent,
    LifecycleEvent,
    OutputEvent,
    ProgressCategory,
    ProtocolEvent,
    SootheEvent,
    SubagentEvent,
    VerbosityLevel,
    VerbosityTier,
    classify_event_to_tier,
    should_show,
    strip_internal_tags,
)

from soothe.foundation.ai_message import extract_text_from_ai_message
from soothe.foundation.slash_commands import (
    KEYBOARD_SHORTCUTS,
    SLASH_COMMANDS,
    handle_slash_command,
    parse_autonomous_command,
)

__all__ = [
    "INTERNAL_JSON_KEYS",
    "INVALID_WORKSPACE_DIRS",
    "KEYBOARD_SHORTCUTS",
    "SLASH_COMMANDS",
    "ErrorEvent",
    "LifecycleEvent",
    "OutputEvent",
    "ProgressCategory",
    "ProtocolEvent",
    "SootheEvent",
    "SubagentEvent",
    "VerbosityLevel",
    "VerbosityTier",
    "classify_event_to_tier",
    "extract_text_from_ai_message",
    "handle_slash_command",
    "parse_autonomous_command",
    "should_show",
    "strip_internal_tags",
]
