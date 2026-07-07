# IG-214: Tool display name (`tool` → real tool) and ls/glob argument lines

**Status:** Completed  
**Scope:** `soothe_cli.shared.tool_call_resolution`, `soothe_cli.tui.tool_display`

## Problem

- Resolved tool name sometimes becomes the literal string `tool` (provider/LC quirk); TUI shows `tool()` instead of `ls()`, `glob()`, etc.
- `ls` / `glob` headers showed empty `()` when path was `.` or when only non-displayed keys were present.

## Changes

- Infer display name from `functions.<tool>:<idx>` ids when name is missing or `tool`.
- Skip empty tool-call ids when merging.
- `format_tool_display`: show `ls(.)` for cwd; broaden `glob` / `ls` arg detection.

## Verification

- `./scripts/verify_finally.sh`
