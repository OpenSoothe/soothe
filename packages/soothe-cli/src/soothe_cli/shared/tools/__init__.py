"""Tool call/result handling utilities."""

from soothe_cli.shared.tools.message_processing import (
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
from soothe_cli.shared.tools.rendering import update_name_map_from_tool_calls
from soothe_cli.shared.tools.tool_call_resolution import (
    build_streaming_args_overlay,
    materialize_ai_blocks_with_resolved_tools,
    tool_args_meaningful,
)
from soothe_cli.shared.tools.tool_card_payload import (
    ToolResultCardPayload,
    extract_tool_result_card_payload,
    infer_tool_output_suggests_error,
)
from soothe_cli.shared.tools.tool_card_visibility import (
    should_elide_completed_tool_call_message,
    should_elide_stream_tool_card_mount,
    should_elide_tool_card_no_info,
)
from soothe_cli.shared.tools.tool_formatters import (
    BaseFormatter,
    ExecutionFormatter,
    FallbackFormatter,
    FileOpsFormatter,
    GoalFormatter,
    MediaFormatter,
    StructuredFormatter,
    SubagentFormatter,
    WebFormatter,
)
from soothe_cli.shared.tools.tool_message_format import (
    format_content_block_for_tool_display,
    format_tool_message_content,
    run_python_envelope_indicates_failure,
    try_parse_run_python_result_envelope,
)
from soothe_cli.shared.tools.tool_output_formatter import ToolBrief, ToolOutputFormatter

__all__ = [
    # Message processing
    "accumulate_tool_call_chunks",
    "coerce_tool_call_args_to_dict",
    "extract_tool_args_dict",
    "extract_tool_brief",
    "finalize_pending_tool_call",
    "format_tool_call_args",
    "normalize_tool_calls_list",
    "strip_internal_tags",
    "tool_calls_have_any_arg_dict",
    "try_parse_pending_tool_call_args",
    # Rendering
    "update_name_map_from_tool_calls",
    # Tool call resolution
    "build_streaming_args_overlay",
    "materialize_ai_blocks_with_resolved_tools",
    "tool_args_meaningful",
    # Tool card payload
    "ToolResultCardPayload",
    "extract_tool_result_card_payload",
    "infer_tool_output_suggests_error",
    # Tool card visibility
    "should_elide_completed_tool_call_message",
    "should_elide_stream_tool_card_mount",
    "should_elide_tool_card_no_info",
    # Tool message format
    "format_content_block_for_tool_display",
    "format_tool_message_content",
    "run_python_envelope_indicates_failure",
    "try_parse_run_python_result_envelope",
    # Formatter
    "ToolBrief",
    "ToolOutputFormatter",
    # Formatters
    "BaseFormatter",
    "ExecutionFormatter",
    "FallbackFormatter",
    "FileOpsFormatter",
    "GoalFormatter",
    "MediaFormatter",
    "SubagentFormatter",
    "StructuredFormatter",
    "WebFormatter",
]
