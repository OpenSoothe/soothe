"""Framework-wide base primitives for Soothe.

Includes former ``core.foundation`` types, assistant text helpers (daemon/UX),
and slash-command dispatch (daemon/TUI).
"""

from soothe.foundation.ai_message import extract_text_from_ai_message
from soothe.foundation.base_events import (
    ErrorEvent,
    LifecycleEvent,
    OutputEvent,
    ProtocolEvent,
    SootheEvent,
    SubagentEvent,
)
from soothe.foundation.internal_assistant import INTERNAL_JSON_KEYS, strip_internal_tags
from soothe.foundation.slash_commands import (
    KEYBOARD_SHORTCUTS,
    SLASH_COMMANDS,
    handle_slash_command,
    parse_autonomous_command,
)
from soothe.foundation.types import INVALID_WORKSPACE_DIRS
from soothe.foundation.verbosity_tier import (
    ProgressCategory,
    VerbosityLevel,
    VerbosityTier,
    classify_custom_event,
    classify_event_to_tier,
    should_show,
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
    "classify_custom_event",
    "classify_event_to_tier",
    "extract_text_from_ai_message",
    "handle_slash_command",
    "parse_autonomous_command",
    "should_show",
    "strip_internal_tags",
]
