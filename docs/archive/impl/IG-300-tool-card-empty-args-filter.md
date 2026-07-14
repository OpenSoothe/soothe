# IG-300: Tool card filtering for empty args and empty results

## Problem

Parallel `glob` (and similar) calls often appeared as `Glob(*)` with no pattern and no useful output. Users saw many tool cards with no information.

## Root cause

1. **Final `AIMessageChunk` with `chunk_position == "last"`**: `_defer_tool_card_for_empty_streaming_args` returns false, so the TUI no longer defers mounting when `args` is still `{}`. The adapter then mounts a card with empty kwargs.

2. **`build_streaming_args_overlay`**: On the terminal chunk, empty parsed ``{}`` was still written into the overlay for every pending tool id. Those entries are non-meaningful noise (IG-300: skip them).

3. **Provider/wire shape**: Some streams expose tool names in blocks but omit kwargs on the last assistant chunk; kwargs never arrive on a later chunk for that `tool_call_id`.

4. **Orphan tool results**: When no card was mounted, `ToolCallMessage(..., {}, ...)` was still created for tool results, repeating the empty-header pattern.

## Solution

- Add `tool_card_visibility` helpers: insubstantial output detection, elide rules (meaningful args OR error OR substantial output OR allowlisted empty-arg tools for stream mount only).
- Skip mounting on a **terminal** assistant message when args are not meaningful and the tool is not `ls` / `list_files`.
- Skip orphan cards when args are empty and formatted output is insubstantial (unless error).
- After success on a matched card, remove the widget if the same elide rule applies.

## Files

- `packages/soothe-cli/src/soothe_cli/shared/tool_card_visibility.py` (new)
- `packages/soothe-cli/src/soothe_cli/shared/tool_call_resolution.py` (`build_streaming_args_overlay`)
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`
- `packages/soothe-cli/tests/unit/ux/test_tool_card_visibility.py` (new)

## Verification

`./scripts/verify_finally.sh`
