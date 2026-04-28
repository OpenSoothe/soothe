# IG-309: RFC-614 Daemon Isolation + Streaming Consistency Polish

## Context

Current implementation enforces daemon-side suppression for AgentLoop execute-phase
assistant prose (IG-304) and relies on explicit goal-completion output events for
user-visible answer text.

`RFC-614` still contains stale references to universal execution streaming and
`soothe.output.execution.streaming` examples that no longer match runtime behavior.

## Goal

Polish `docs/specs/RFC-614-unified-streaming-messaging.md` so it is fully
consistent with the current daemon-side isolation contract and client streaming
accumulator behavior.

## Scope

- Update stale examples and statements in RFC-614:
  - Replace `soothe.output.execution.streaming` examples with current
    goal-completion output events.
  - Clarify `execution_streaming` as backward-compatibility field with no effect
    on agentic execute-phase prose forwarding.
  - Align event-flow and success criteria language with daemon-side suppression.
  - Add explicit note on boundary-safe streaming concatenation behavior.

## Non-goals

- No runtime code changes.
- No event-name migration in code.

## Verification

- Manual pass over RFC-614 to ensure all output-event examples match actual
  current event contract.
