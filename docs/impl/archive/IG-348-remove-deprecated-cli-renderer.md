# IG-348: Remove deprecated CliRenderer (rich headless stderr path)

## Context

Non-TUI mode emits RFC-614 loop-tagged main-graph assistant text only via `HeadlessCliRenderer` and `EventProcessor(headless_output=True)` (`cli/execution/daemon.py`). The former `CliRenderer` (`cli/renderer.py`) implemented stdout bullets, stderr tools/progress via `StreamDisplayPipeline`, and Task subgraph formatting—it is no longer wired into production.

## Work

- Delete `packages/soothe-cli/src/soothe_cli/cli/renderer.py`.
- Remove tests that only exercised `CliRenderer`; add minimal `HeadlessCliRenderer` tests for suppression rules.
- Update docstrings/comments that referenced `CliRenderer` to describe TUI / `StreamDisplayPipeline` / headless facts accurately.

## Verification

Run `./scripts/verify_finally.sh`.
