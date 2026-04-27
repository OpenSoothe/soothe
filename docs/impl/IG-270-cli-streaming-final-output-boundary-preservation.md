# IG-270 CLI Streaming Final Output Boundary Preservation

## Context

Headless CLI output can collapse markdown/newline/space boundaries in final responses when content is emitted through `agent_loop.completed` final stdout handling. This creates invalid concatenation in rendered output (for example `##1` or `first10`).

## Goal

Preserve final response text boundaries exactly as produced by the agent during multi-step suppression and final emission paths.

## Scope

- `packages/soothe-cli/src/soothe_cli/shared/suppression_state.py`
- `packages/soothe-cli/src/soothe_cli/cli/renderer.py`
- `packages/soothe-cli/tests/unit/ux/cli/test_cli_renderer_spacing.py`

## Implementation Plan

1. Remove destructive `.strip()` normalization from final stdout extraction and aggregation in `SuppressionState`.
2. Update `CliRenderer._write_stdout_final_report()` to emit exact text payload without trimming internal/boundary whitespace.
3. Add regression coverage for markdown heading and token boundary preservation in headless final stdout output.

## Verification

- Run targeted CLI renderer spacing tests.
- Run touched unit tests for event processor if needed.
