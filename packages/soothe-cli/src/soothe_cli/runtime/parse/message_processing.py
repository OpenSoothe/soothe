"""Re-export shim for ``soothe_sdk.display.message_processing`` (RFC-413).

These helpers live in the SDK so the daemon-resident ``CardBinder`` can
reuse them. This module preserves the original CLI import path used
across the runtime, TUI, and tests.
"""

from __future__ import annotations

# Underscore-prefixed names below are re-exported intentionally — they are
# imported by other CLI modules (tool_call_resolution, widgets/messages, etc.)
# and CLI tests. Keep them in __all__ to keep `ruff` from stripping them.
from soothe_sdk.display.message_processing import (
    _normalize_tool_name_for_arg_map,
    _pending_or_overlay_id_matches_lookup,
    _resolve_pending_lookup_tool_name,
    accumulate_tool_call_chunks,
    coerce_tool_call_args_to_dict,
    extract_tool_args_dict,
    extract_tool_brief,
    finalize_pending_tool_call,
    ingest_tool_call_stream_state,
    normalize_tool_calls_list,
    richest_pending_args_for_lookup,
    tool_calls_have_any_arg_dict,
    tool_ids_touched_by_stream_message,
    try_parse_pending_tool_call_args,
)

__all__ = [
    "_normalize_tool_name_for_arg_map",
    "_pending_or_overlay_id_matches_lookup",
    "_resolve_pending_lookup_tool_name",
    "accumulate_tool_call_chunks",
    "coerce_tool_call_args_to_dict",
    "extract_tool_args_dict",
    "extract_tool_brief",
    "finalize_pending_tool_call",
    "ingest_tool_call_stream_state",
    "normalize_tool_calls_list",
    "richest_pending_args_for_lookup",
    "tool_calls_have_any_arg_dict",
    "tool_ids_touched_by_stream_message",
    "try_parse_pending_tool_call_args",
]
