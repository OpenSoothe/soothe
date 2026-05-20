"""Daemon event processing and display state for the CLI (source of truth for TUI).

Bridges daemon events/messages to in-memory state. ``soothe_cli.tui`` owns widgets
and layout only.
"""

from soothe_cli.config.loader import load_config
from soothe_cli.config.logging_setup import setup_logging
from soothe_cli.runtime.headless.processor import EventProcessor
from soothe_cli.runtime.headless.processor_state import ProcessorState
from soothe_cli.runtime.parse.message_processing import (
    accumulate_tool_call_chunks,
    coerce_tool_call_args_to_dict,
    extract_tool_args_dict,
    extract_tool_brief,
    finalize_pending_tool_call,
    ingest_tool_call_stream_state,
    normalize_tool_calls_list,
    strip_internal_tags,
    tool_calls_have_any_arg_dict,
    try_parse_pending_tool_call_args,
)
from soothe_cli.runtime.policy.display_policy import (
    INTERNAL_EVENT_TYPES,
    INTERNAL_JSON_KEYS,
    SKIP_EVENT_TYPES,
    DisplayPolicy,
    create_display_policy,
)
from soothe_cli.runtime.policy.essential_events import (
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
from soothe_cli.runtime.presentation.renderer_protocol import RendererProtocol
from soothe_cli.runtime.state.transcript import MessageData, MessageType, ToolStatus
from soothe_cli.runtime.transport.session import TuiDaemonSession
from soothe_cli.runtime.turn.pipeline import TurnEventPipeline, run_turn_pipeline
from soothe_cli.runtime.turn.prepare import PreparedTurnChunk, TurnPrepareState, prepare_turn_chunk

__all__ = [
    "INTERNAL_EVENT_TYPES",
    "INTERNAL_JSON_KEYS",
    "SKIP_EVENT_TYPES",
    "DisplayPolicy",
    "ESSENTIAL_PROGRESS_EVENT_TYPES",
    "GOAL_START_EVENT_TYPES",
    "LOOP_REASON_EVENT_TYPE",
    "EventProcessor",
    "MessageData",
    "MessageType",
    "PreparedTurnChunk",
    "ProcessorState",
    "RendererProtocol",
    "STEP_COMPLETE_EVENT_TYPES",
    "STEP_START_EVENT_TYPES",
    "ToolStatus",
    "TurnEventPipeline",
    "TurnPrepareState",
    "TuiDaemonSession",
    "accumulate_tool_call_chunks",
    "coerce_tool_call_args_to_dict",
    "create_display_policy",
    "extract_tool_args_dict",
    "extract_tool_brief",
    "finalize_pending_tool_call",
    "ingest_tool_call_stream_state",
    "is_essential_progress_event_type",
    "is_goal_start_event_type",
    "is_step_complete_event_type",
    "is_step_start_event_type",
    "load_config",
    "normalize_tool_calls_list",
    "prepare_turn_chunk",
    "run_turn_pipeline",
    "setup_logging",
    "strip_internal_tags",
    "tool_calls_have_any_arg_dict",
    "try_parse_pending_tool_call_args",
]
