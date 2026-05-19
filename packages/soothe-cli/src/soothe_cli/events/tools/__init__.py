"""Tool stream state utilities (args resolution, result extraction)."""

from soothe_cli.events.tools.message_processing import (
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
from soothe_cli.events.tools.tool_call_resolution import (
    build_streaming_args_overlay,
    materialize_ai_blocks_with_resolved_tools,
    merge_tool_display_args,
    resolve_stream_tool_name,
    tool_args_meaningful,
)
from soothe_cli.events.tools.tool_message_format import (
    format_tool_message_content,
    run_python_envelope_indicates_failure,
    try_parse_run_python_result_envelope,
)
from soothe_cli.events.tools.tool_result import (
    ToolResultPayload,
    extract_tool_result_payload,
    infer_tool_output_suggests_error,
)

__all__ = [
    "ToolResultPayload",
    "accumulate_tool_call_chunks",
    "build_streaming_args_overlay",
    "coerce_tool_call_args_to_dict",
    "extract_tool_args_dict",
    "extract_tool_brief",
    "extract_tool_result_payload",
    "finalize_pending_tool_call",
    "format_tool_message_content",
    "infer_tool_output_suggests_error",
    "ingest_tool_call_stream_state",
    "materialize_ai_blocks_with_resolved_tools",
    "merge_tool_display_args",
    "normalize_tool_calls_list",
    "resolve_stream_tool_name",
    "run_python_envelope_indicates_failure",
    "strip_internal_tags",
    "tool_args_meaningful",
    "tool_calls_have_any_arg_dict",
    "try_parse_pending_tool_call_args",
    "try_parse_run_python_result_envelope",
]
