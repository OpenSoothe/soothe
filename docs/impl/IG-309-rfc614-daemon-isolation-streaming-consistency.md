# IG-309: RFC-614 Daemon Isolation + Streaming Consistency Polish

**Status**: Completed (superseded by follow-up IG-317 doc work)

## Outcome

RFC-614 and related specs were refreshed so they describe the **current** contract:

- Daemon-side suppression for execute-phase assistant prose (IG-304) remains accurate.
- Examples that referenced **`soothe.output.execution.streaming`** and parallel **`soothe.output.goal_completion.*`** assistant paths were removed or rewritten in favor of **`mode="messages"`** + **`phase`** (IG-317).

## References

- `docs/specs/RFC-614-unified-streaming-messaging.md`
- `docs/analysis/daemon-event-forwarding-matrix.md`
- `docs/impl/IG-317-rfc614-loop-message-stream-unification.md`

## Note

No separate open checklist remains in this IG; treat RFC-614 as the living source of truth for streaming semantics.
