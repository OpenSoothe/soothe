# IG-650: Adapt soothe-desktop to `@mirasoth/soothe-client` 0.2.1

**Status**: Done  

**Scope**: `apps/soothe-desktop` (+ monorepo pin of `client/typescript` @ v0.2.1)  
**Related**: RFC-450, RFC-505, IG-525 (client protocol-1 migration)

## Goal

Consume the latest TypeScript client (`@mirasoth/soothe-client@0.2.1`) so the
desktop app correctly speaks the daemon's protocol-1 wire contract.

## Changes

1. **Project inbound frames** — `receiveMessages()` yields raw envelopes.
   Stream events arrive as `next` with `payload.{namespace,mode,data}`.
   Desktop projects these to inner stream frames the renderer already
   understands (same pattern as the CLI session unwrap).
2. **Typed `LoopNewOptions`** for `client_workspace` on `loop_new`.
3. **Refresh lockfile** so the linked package resolves as 0.2.1.

## Cleanse (post-adapt)

- Dropped redundant `waitForDaemonReady` after `connect()` (handshake is in connect).
- Removed dead RFC-411 reattach frames (`history_replay`, `loop_reattached`,
  `replay_complete`) — daemon supersedes them with `card.*` (RFC-413).
- Dropped obsolete `*_response` filters and `root_id` autopilot id fallback.
- Autopilot status/progress keys off `goal_id` (with `job_id` synonym).
- Deduped duplicate `step.completed` renderer registration.

## Non-goals

- Migrating desktop to appkit (`TurnRunner` / `ConnectionPool`) — follow-up.
- Rendering `card.*` ledger replay in the chat list — follow-up.
- Changing renderer event-type vocabulary (`strange_loop` namespaces stay).

## Verification

```bash
cd client/typescript && npm run build
cd apps/soothe-desktop && npm install && npm run typecheck && npm test
```
