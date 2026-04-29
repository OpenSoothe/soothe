# IG-315: CLI Tool Call/Result Single-Line Rendering

## Context

Headless CLI currently prints tool invocation and tool result as separate lines:

- `⚙ Tool(args)`
- `✓ Result`

During high-volume tool usage this doubles visual noise and makes it harder to scan
execution flow quickly.

## Goal

- Render a completed tool invocation as one compact stderr line in headless CLI.
- Preserve existing duration and error indicators.
- Keep fallback behavior when tool-call IDs are unavailable.

## Scope

- `packages/soothe-cli/src/soothe_cli/cli/renderer.py`
- `packages/soothe-cli/tests/unit/ux/cli/test_cli_renderer_spacing.py`

## Planned changes

- Buffer tool-call display text by `tool_call_id` instead of emitting immediately.
- On tool result, merge buffered call text + result status into one line.
- Keep immediate call printing for calls without stable IDs.
- Add unit tests for single-line merge behavior and fallback path.

## Verification

- Run targeted unit tests:
  - `packages/soothe-cli/tests/unit/ux/cli/test_cli_renderer_spacing.py`
