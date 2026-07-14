# IG-216: Tool card always shows arg + output hints

**Status:** Completed  
**Scope:** `soothe_cli.tui.tool_display`, `ToolCallMessage._update_output_display`

## Goal

Avoid bare `ls()` / `glob()` / `tool()` headers when kwargs are `{}`, and avoid blank tool rows when the tool succeeds with empty string output.

## Changes

- **Headers**: `ls` / `list_files` with no path → `ls(.)` / `list_files(.)` (implicit workspace); `glob` with no pattern → `glob("*")`; unknown tools with no kwargs → `name(…)`; `task` / `compact_conversation` → `(…)` when no sub-fields.
- **Output**: On `success` with empty stripped body, show dim `(no tool output)` in the preview/full area; `has_output` / click toggle treat success as having displayable content.

## Verification

- `./scripts/verify_finally.sh`
