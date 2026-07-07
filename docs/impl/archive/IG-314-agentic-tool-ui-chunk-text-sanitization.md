# IG-314: Agentic Tool-UI Chunk Text Sanitization

## Context

Daemon-side forwarding in `core/runner/_runner_agentic.py` intentionally forwards
AI message chunks that contain tool-call metadata so clients can render tool cards.
Some mixed chunks include both tool metadata and assistant text blocks, which leaks
step/evidence prose to clients unexpectedly.

## Goal

- Keep forwarding tool-related AI chunks for tool UI correctness.
- Strip user-visible text/content blocks from forwarded AI chunks.
- Add debug logs with a preview of stripped text for diagnostics.

## Scope

- `packages/soothe/src/soothe/core/runner/_runner_agentic.py`
- `packages/soothe/tests/unit/core/test_agentic_tool_stream_forward.py`

## Planned changes

- Add chunk sanitization helper for forwarded AI tool-invocation chunks.
- Remove `content` text and text-like `content_blocks`, preserving tool-call metadata.
- Emit debug log with stripped text/content preview when sanitization removes text.
- Add/update unit tests for sanitization and forwarding behavior.

## Verification

- Run targeted unit tests:
  - `packages/soothe/tests/unit/core/test_agentic_tool_stream_forward.py`
