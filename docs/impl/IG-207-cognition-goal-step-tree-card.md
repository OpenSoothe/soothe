# IG-207: Cognition Goal → steps tree card (TUI)

## Goal

Show agentic Layer 2 as a single cognition-styled card: **Goal** header and indented **steps** that update in place as steps start and finish. Reuse the same visual language as plan/reason cards (`$cognition` border).

## Behavior

- On `soothe.cognition.agent_loop.started`, mount `CognitionGoalTreeMessage` (goal text + optional `≤N iter` when `max_iterations > 1`).
- On `soothe.cognition.agent_loop.step.started` / `step.completed`, update the same widget’s aggregate step block (no per-step cards).
- On `soothe.cognition.agent_loop.completed`, show a compact footer (`status`, progress %, step count, completion summary) and drop the live namespace handle.
- If the tree is absent (legacy paths), keep existing `CognitionStepMessage` / pipeline fallback.
- `finalize_pending_steps_with_error` and user interrupt clear and mark goal trees interrupted.

## Implementation

- Widget: `CognitionGoalTreeMessage` in `soothe_cli/tui/widgets/messages.py` — multiline `Static` for steps, refreshed synchronously.
- Adapter: `TextualUIAdapter._goal_tree_by_namespace`, handlers in `textual_adapter.py` before optional `final_stdout` assistant message.
- Store: `MessageType.COGNITION_GOAL_TREE` + `cognition_goal_snapshot_json` (`snapshot_dict()`).

## Verification

- `./scripts/verify_finally.sh`
