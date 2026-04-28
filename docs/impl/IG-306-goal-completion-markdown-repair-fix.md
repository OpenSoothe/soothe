# IG-306: Goal Completion Markdown Repair Fix

## Context

Real CLI run (`soothe --no-tui -p "count all readmes of each package"`) exposed
goal-completion formatting artifacts such as:

- `# ... Report## Summary...` (missing section break)
- `###1.` (missing space after heading markers)

The shared renderer repair path is intended to fix concatenation artifacts but
currently has regex edge cases that can split heading markers incorrectly.

## Goal

Make markdown repair deterministic for heading artifacts in final goal-completion
output without changing daemon-side suppression contracts.

## Scope

- Update shared renderer repair utility:
  - `packages/soothe-cli/src/soothe_cli/shared/renderer_base.py`
- Add focused regression test in CLI renderer tests:
  - `packages/soothe-cli/tests/unit/ux/cli/test_cli_renderer_spacing.py`

## Non-goals

- No daemon event contract changes.
- No changes to tool/progress rendering.

## Verification

- Targeted pytest for CLI renderer spacing tests.
- Re-run real no-TUI query to confirm formatted output is no longer concatenated.
