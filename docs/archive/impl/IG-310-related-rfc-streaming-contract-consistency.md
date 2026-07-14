# IG-310: Related RFC Streaming Contract Consistency

## Context

`RFC-614` was polished to match current daemon-side suppression and streaming
behavior. Related RFCs still contain stale examples and interface snippets.

## Goal

Refine related RFCs so event contracts and processor state examples remain
consistent with current implementation.

## Scope

- `docs/specs/RFC-401-event-processing.md`
- `docs/specs/RFC-201-agentloop-plan-execute-loop.md`
- `docs/specs/RFC-500-cli-tui-architecture.md`
- `docs/specs/RFC-450-daemon-communication-protocol.md`

## Planned refinements

- Align EventProcessor/ProcessorState snippets with current fields.
- Clarify boundary-safe streaming accumulation behavior in EventProcessor path.
- Update AgentLoop stream-event table to current event names and contract wording.

## Non-goals

- No runtime code changes.
- No event taxonomy redesign.

## Verification

- Manual grep/read pass confirms no stale execute-streaming event names in
  updated RFC sections.
