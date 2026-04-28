# IG-302 Goal Output Hard Cutover

## Objective

Perform a hard cutover for goal-loop final answer delivery so both CLI and TUI consume the same output-domain events in batch and streaming modes, with no backward compatibility paths.

## Scope

- Remove `goal_completion_message` from cognition completion payloads.
- Keep cognition completion events as control/progress only.
- Emit final goal answer via output-domain event:
  - `soothe.output.goal_completion.responded` (full final body)
- Continue optional chunk streaming via:
  - `soothe.output.goal_completion.streaming`
- Update CLI/TUI consumers to rely only on output-domain events for final answer text.

## Non-Goals

- No compatibility shims for old payload fields.
- No dual-write/dual-read migration path.

## Implementation Plan

1. Update event models/constants/registry:
   - Add `GOAL_COMPLETION_RESPONDED` constant.
   - Remove `goal_completion_message` from `AgenticLoopCompletedEvent`.
   - Register `soothe.output.goal_completion.responded` in output event registry.
   - Remove output extraction registration for `soothe.cognition.agent_loop.completed`.
2. Update runner emission:
   - Emit `soothe.output.goal_completion.responded` with final full text.
   - Emit `soothe.cognition.agent_loop.completed` without final body payload.
3. Update CLI processors/renderers:
   - Remove completed-event payload mutation logic tied to `goal_completion_message`.
   - Update suppression finalization to emit buffered output on loop completion without requiring payload text.
   - Add exactly-once final output handling for responded events.
4. Update TUI adapters:
   - Replace completed-event text handling with responded-event handling.
   - Keep completed events for progress state only.
5. Update tests to enforce hard cutover behavior.

## Validation

- Targeted CLI/TUI unit tests for:
  - batch mode final answer rendering from responded events
  - streaming mode chunk rendering + no duplicate final replay
  - no final answer extraction from cognition completed events

## Risks

- Streaming-mode duplicate/empty final behavior if suppression and responded finalization diverge.
- Background consumers that relied on completed-event payloads may need strict updates.

## Completion Criteria

- No references to `goal_completion_message` in CLI/TUI runtime paths.
- Final answer rendering sourced only from `soothe.output.*` events.
- Tests pass for both streaming and batch behaviors after hard cutover.
