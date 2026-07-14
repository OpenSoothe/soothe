# IG-205: Step `step_id` + cognition step cards (TUI)

## Purpose

Correlate agent-loop act step start and completion with `step_id` on wire events, and render a single TUI card per step with running animation then completion (mirroring tool-call lifecycle).

## Changes

- **`packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`**: `step_started` payload includes `step_id` (from `step.id`).
- **`packages/soothe/src/soothe/core/event_catalog.py`**: `AgenticStepStartedEvent.step_id`, `AgenticStepCompletedEvent.step_id`.
- **`packages/soothe/src/soothe/core/runner/_runner_agentic.py`**: Pass `step_id` through to both events.
- **`packages/soothe-cli/src/soothe_cli/tui/theme.py`**: `$cognition` / `$cognition-hover` theme colors.
- **`packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py`**: `CognitionStepMessage` widget.
- **`packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`**: Intercept `agent_loop.step.started` / `.completed` before pipeline; `finalize_pending_steps_with_error`; interrupt cleanup clears step cards.
- **`packages/soothe-cli/src/soothe_cli/tui/widgets/message_store.py`**: `MessageType.STEP_PROGRESS` and hydration fields.
- **`packages/soothe-cli/src/soothe_cli/tui/app.py`**: Mount union + error-path finalization.

## Verification

Run `./scripts/verify_finally.sh`.
