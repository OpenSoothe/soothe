"""Daemon event processing and in-memory presentation state for the TUI.

Bridges daemon events/messages to memory-based state (tool calls, plan steps,
progress lines, presentation policy). This package is the source of truth for
what the TUI should render; ``soothe_cli.tui`` owns widgets and layout only.
"""

from soothe_sdk.utils import setup_logging

from soothe_cli.config.loader import load_config
from soothe_cli.events.core import EventProcessor, ProcessorState, RendererProtocol
from soothe_cli.events.policy import DisplayPolicy
from soothe_cli.events.policy.display_policy import (
    INTERNAL_EVENT_TYPES,
    INTERNAL_JSON_KEYS,
    SKIP_EVENT_TYPES,
    create_display_policy,
)
from soothe_cli.events.policy.essential_events import (
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
from soothe_cli.events.tools.message_processing import (
    accumulate_tool_call_chunks,
    coerce_tool_call_args_to_dict,
    extract_tool_args_dict,
    extract_tool_brief,
    finalize_pending_tool_call,
    format_tool_call_args,
    normalize_tool_calls_list,
    strip_internal_tags,
    tool_calls_have_any_arg_dict,
    try_parse_pending_tool_call_args,
)
from soothe_cli.events.tools.rendering import update_name_map_from_tool_calls

__all__ = [
    "INTERNAL_EVENT_TYPES",
    "INTERNAL_JSON_KEYS",
    "SKIP_EVENT_TYPES",
    "DisplayPolicy",
    "ESSENTIAL_PROGRESS_EVENT_TYPES",
    "GOAL_START_EVENT_TYPES",
    "LOOP_REASON_EVENT_TYPE",
    "EventProcessor",
    "ProcessorState",
    "RendererProtocol",
    "STEP_COMPLETE_EVENT_TYPES",
    "STEP_START_EVENT_TYPES",
    "accumulate_tool_call_chunks",
    "coerce_tool_call_args_to_dict",
    "create_display_policy",
    "extract_tool_args_dict",
    "extract_tool_brief",
    "finalize_pending_tool_call",
    "format_tool_call_args",
    "is_essential_progress_event_type",
    "is_goal_start_event_type",
    "is_step_complete_event_type",
    "is_step_start_event_type",
    "load_config",
    "normalize_tool_calls_list",
    "setup_logging",
    "strip_internal_tags",
    "tool_calls_have_any_arg_dict",
    "try_parse_pending_tool_call_args",
    "update_name_map_from_tool_calls",
]
