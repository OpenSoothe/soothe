# IG-333: Step completion line — parity with goal completion

## Goal

`format_step_done` should match `format_goal_done` structure: flat level-1 line with leading `●`, status symbol + description in content, parenthetical metadata, and trailing duration from `DisplayLine`.

Example (goal): `● 🏆 I'll read… (complete, 1 steps) (27.6s)`

Example (step): `● ✓ Read README header (done, 4 tools) (14.0s)`

## Implementation

- `formatter.format_step_done`: `level=1`, `icon="●"`, `indent` flat; content `✓ {step} (done{, N tools})` / failure `✗ … (failed{, N tools})`; error detail on a second flat line without tree icon.
- `pipeline._on_step_completed`: snapshot `step_description` from context / `step_descriptions` before clearing; pass into `format_step_done`.
- Tests: unit + TUI indent expectations; fix `plan.step_started` typo → `plan.step.started` where needed.

## Verification

- `./scripts/verify_finally.sh`
