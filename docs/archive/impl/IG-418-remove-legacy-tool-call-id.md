# IG-418: Remove Legacy Tool Call ID Handling

## Summary
Remove backward compatibility code for legacy provider tool_call_id formats (e.g., `functions.ls:0`) since IG-416 unified format (`{step_id}:s:{tool}.{idx}`) is now the canonical standard.

## Background
IG-416 introduced unified tool_call_id format for consistent TUI rendering. The daemon executor (`_rewrite_tool_call_ids_to_unified`) should emit all IDs in unified format. Legacy handling was kept for backward compatibility during migration.

Verification script (`scripts/verify_daemon_events.py`) confirms:
- Some IDs still arrive as legacy format (`functions.ls:0`)
- Subsequent steps correctly use unified format (`IZH-02:s:task.5`)
- This is a bug in executor rewrite logic, not client handling

## Root Cause
Executor `_rewrite_tool_call_ids_to_unified` is not called consistently for all streaming messages. First step tool calls retain provider format while later steps use unified format.

## Scope

### Files to Modify

**soothe-sdk (cleanup of backward compat):**
- `packages/soothe-sdk/src/soothe_sdk/ux/task_namespace.py`:
  - Remove `alternate_subgraph_row_keys()` (legacy colon/dot variants)
  - Simplify `_shorten_tool_call_id()` (only handle unified fragments)
  - Remove legacy handling in `scoped_subgraph_tool_key()`

**soothe-cli (cleanup of fallback):**
- `packages/soothe-cli/src/soothe_cli/tui/step_task_routing.py`:
  - Remove `tool_call_to_step_id` mapping
  - Remove `bind_tool_to_step()` method
  - Simplify `step_id_for_tool()` to parse unified format only

- `packages/soothe-cli/src/soothe_cli/shared/tools/tool_call_resolution.py`:
  - Remove `infer_tool_name_from_call_id()` (recover name from `functions.X`)

- `packages/soothe-cli/src/soothe_cli/shared/tools/message_processing.py`:
  - Simplify `_pending_or_overlay_id_matches_lookup()`
  - Simplify `richest_pending_args_for_lookup()`

- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter/_stream_formatting.py`:
  - Remove `_resolve_existing_subgraph_row_key()` legacy fallback
  - Simplify `alias_subgraph_pending_and_overlay()`

**soothe (fix the rewrite):**
- `packages/soothe/src/soothe/core/loop/engine/executor.py`:
  - Ensure `_rewrite_tool_call_ids_to_unified` is called for ALL streaming messages
  - Fix the first-step issue where IDs aren't rewritten

## Implementation Steps

1. Fix executor to consistently emit unified IDs
2. Remove backward compat in SDK `alternate_subgraph_row_keys`
3. Remove CLI fallback methods
4. Update tests to use unified format
5. Run verification to confirm fix

## Testing
- Run `scripts/verify_daemon_events.py` to confirm all IDs are unified
- Run existing tests (update test data to unified format)
- Run `./scripts/verify_finally.sh`

## Success Criteria
- All tool_call_ids emitted by daemon use unified format
- No legacy format IDs in client processing
- Verification script shows 0 legacy IDs