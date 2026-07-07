# IG-211: Canonical tool-call resolution for TUI display

## Goal

Single merge path for tool name/args from `message.tool_calls`, content/tool blocks, and optional streaming (`tool_call_chunks` accumulation) so tool cards show consistent arguments without scattered backfill/merge logic.

## Status

Completed. Canonical API:

- `soothe_cli.shared.tool_call_resolution.materialize_ai_blocks_with_resolved_tools`
- `soothe_cli.shared.tool_call_resolution.build_streaming_args_overlay`

Legacy TUI helpers (`_merge_streaming_tool_extra_into_blocks`, `_backfill_tool_block_args_from_message_attr`, `_append_tool_calls_from_message_attr`) were removed.
