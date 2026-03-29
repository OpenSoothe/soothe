"""UX core module - shared infrastructure for CLI and TUI.

This module provides:
- Configuration loading and logging setup
- Unified event processing (RFC-0019)
- Unified display policy for event/content filtering
- Abstract renderer protocol for CLI/TUI
- Shared message processing and utilities
"""

from soothe.core.verbosity_tier import (
    VerbosityTier,
    classify_event_to_tier,
    should_show,
)
from soothe.ux.core.config_loader import load_config
from soothe.ux.core.display_policy import (
    INTERNAL_EVENT_TYPES,
    INTERNAL_JSON_KEYS,
    SKIP_EVENT_TYPES,
    DisplayPolicy,
    VerbosityLevel,
    create_display_policy,
)
from soothe.ux.core.event_processor import EventProcessor
from soothe.ux.core.logging_setup import setup_logging
from soothe.ux.core.message_processing import (
    SharedState,
    accumulate_tool_call_chunks,
    coerce_tool_call_args_to_dict,
    extract_tool_brief,
    finalize_pending_tool_call,
    format_tool_call_args,
    is_multi_step_plan,
    normalize_tool_calls_list,
    strip_internal_tags,
    tool_calls_have_any_arg_dict,
    try_parse_pending_tool_call_args,
)
from soothe.ux.core.processor_state import ProcessorState
from soothe.ux.core.renderer_protocol import RendererProtocol
from soothe.ux.core.rendering import (
    extract_text_from_ai_message,
    render_plan_tree,
    resolve_namespace_label,
    update_name_map_from_tool_calls,
)

__all__ = [
    "INTERNAL_EVENT_TYPES",
    "INTERNAL_JSON_KEYS",
    "SKIP_EVENT_TYPES",
    "DisplayPolicy",
    # Event processing
    "EventProcessor",
    "ProcessorState",
    # Rendering
    "RendererProtocol",
    # Message processing
    "SharedState",
    "VerbosityLevel",
    # Verbosity tier (RFC-0024)
    "VerbosityTier",
    "accumulate_tool_call_chunks",
    "classify_event_to_tier",
    "coerce_tool_call_args_to_dict",
    # Display Policy (unified filtering module)
    "create_display_policy",
    "extract_text_from_ai_message",
    "extract_tool_brief",
    "finalize_pending_tool_call",
    "format_tool_call_args",
    "is_multi_step_plan",
    # Config and logging
    "load_config",
    "normalize_tool_calls_list",
    "render_plan_tree",
    "resolve_namespace_label",
    "setup_logging",
    "should_show",
    "strip_internal_tags",
    "tool_calls_have_any_arg_dict",
    "try_parse_pending_tool_call_args",
    "update_name_map_from_tool_calls",
]
