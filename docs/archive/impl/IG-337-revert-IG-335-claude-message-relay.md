# IG-337: Revert IG-335 (Claude message relay) only

## Status: Complete

## Goal

Remove IG-335 (`soothe.relay.message`, Claude `message_mapping` / `relay`, CLI `message_relay`, EventProcessor and TUI relay short-circuits, classification override, associated tests, IG-335 doc).

**Preserve** IG-334: task-tool FIFO namespace binding, `task_scope` on renderer callbacks, and subgraph assistant/tool display wiring that does not depend on relay.

## Verification

- `./scripts/verify_finally.sh`

## Implementation note

Applied as patch removing IG-335-only artifacts; Claude subgraph returns the same single terminal `AIMessage` as before IG-335 (`packages/soothe/src/soothe/subagents/claude/implementation.py`).
