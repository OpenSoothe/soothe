"""Shared UX presentation layer for CLI and TUI (not Typer/Textual).

This package provides:
- Configuration loading and logging setup
- Unified event processing (RFC-0019)
- Unified display policy for event/content filtering
- Abstract renderer protocol for CLI/TUI
- Shared message processing and utilities
"""

from soothe.logging import setup_logging
from soothe.ux.shared.config_loader import load_config
from soothe.ux.shared.display_policy import (
    INTERNAL_EVENT_TYPES,
    INTERNAL_JSON_KEYS,
    SKIP_EVENT_TYPES,
    DisplayPolicy,
    VerbosityLevel,
    create_display_policy,
)
from soothe.ux.shared.essential_events import (
    ESSENTIAL_PROGRESS_EVENT_TYPES,
    GOAL_START_EVENT_TYPES,
    LOOP_REASON_EVENT_TYPE,
    STEP_COMPLETE_EVENT_TYPES,
    STEP_START_EVENT_TYPES,
    is_essential_progress_event_type,
    is_goal_start_event_type,
    is_step_complete_event_type,
    is_step_start_event_type,
)
from soothe.ux.shared.event_processor import EventProcessor
from soothe.ux.shared.message_processing import (
    accumulate_tool_call_chunks,
    coerce_tool_call_args_to_dict,
    extract_tool_brief,
    finalize_pending_tool_call,
    format_tool_call_args,
    normalize_tool_calls_list,
    strip_internal_tags,
    tool_calls_have_any_arg_dict,
    try_parse_pending_tool_call_args,
)
from soothe.ux.shared.processor_state import ProcessorState
from soothe.ux.shared.renderer_protocol import RendererProtocol
from soothe.ux.shared.rendering import update_name_map_from_tool_calls

__all__ = [
    "INTERNAL_EVENT_TYPES",
    "INTERNAL_JSON_KEYS",
    "SKIP_EVENT_TYPES",
    "DisplayPolicy",
    "ESSENTIAL_PROGRESS_EVENT_TYPES",
    "GOAL_START_EVENT_TYPES",
    "LOOP_REASON_EVENT_TYPE",
    # Event processing
    "EventProcessor",
    "ProcessorState",
    # Rendering
    "RendererProtocol",
    # Message processing
    "VerbosityLevel",
    "accumulate_tool_call_chunks",
    "coerce_tool_call_args_to_dict",
    # Display Policy (unified filtering module)
    "create_display_policy",
    "extract_tool_brief",
    "finalize_pending_tool_call",
    "format_tool_call_args",
    "is_essential_progress_event_type",
    "is_goal_start_event_type",
    "is_step_complete_event_type",
    "is_step_start_event_type",
    # Config and logging
    "load_config",
    "normalize_tool_calls_list",
    "setup_logging",
    "STEP_COMPLETE_EVENT_TYPES",
    "STEP_START_EVENT_TYPES",
    "strip_internal_tags",
    "tool_calls_have_any_arg_dict",
    "try_parse_pending_tool_call_args",
    "update_name_map_from_tool_calls",
]
