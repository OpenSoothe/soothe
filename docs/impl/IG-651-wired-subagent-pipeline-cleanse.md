# IG-651 Wired Subagent Pipeline Cleanse

## Goal

Cleanse safe legacy/dead code across the wired-subagent pipeline without changing behavior.

## Scope

- Wired-subagent stream and completion path touched in:
  - `packages/soothe/src/soothe/foundation/sloop/orchestrator/nodes/invoke_wired_subagent.py`
  - `packages/soothe/src/soothe/runner/_runner_strange_loop.py`
  - `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`
  - `packages/soothe-cli/src/soothe_cli/tui/app/_execution.py`
- Verification and cleanup signals from:
  - targeted `vulture` scans
  - wired-subagent unit tests
  - `./scripts/verify_finally.sh`

## Cleanse Targets

1. Remove unused TUI execution pass-through kwargs chain (`message_kwargs`) that is never consumed.
2. Remove dead-code lint noise in typed callback protocol parameter naming.
3. Keep runtime behavior identical for daemon turn execution and wired-subagent rendering.

## Non-Goals

- No wire event schema changes.
- No subagent routing logic changes.
- No UI rendering behavior redesign.

## Verification Plan

1. Run targeted wired-subagent tests.
2. Run full `./scripts/verify_finally.sh`.
3. Confirm no new dead-code findings in the touched pipeline files.

