# IG-435: Client Event Delivery and `soothe.internal` Namespace

**Status**: In Progress  
**Started**: 2026-05-26

## Summary

Fix client event delivery under load (loop 048f), reduce daemon→client volume, and introduce `soothe.internal.<component>.<action>` types that are never broadcast to WebSocket clients.

## Loop 048f postmortem

| Layer | Finding |
|-------|---------|
| Worker | Normal execution |
| Daemon | Client queue 10k/10k; NORMAL priority drops |
| CLI/TUI | 0 turn events despite active worker |

Root cause: delivery path saturation, not missing worker emission. P0 fixes: background WS reader, handshake busy-loop fix, RPC isolation, sender batch-50.

## Internal naming convention

```
soothe.internal.<component>.<action_or_state>
```

No domain segment after `soothe.internal`. Client-facing types remain `soothe.<domain>.<component>.<action>`.

## Event audit (internal → never on wire)

| Old | New |
|-----|-----|
| `soothe.lifecycle.iteration.*` | `soothe.internal.iteration.*` |
| `soothe.lifecycle.checkpoint.*` | `soothe.internal.checkpoint.*` |
| `soothe.lifecycle.recovery.*` | `soothe.internal.recovery.*` |
| `soothe.lifecycle.loop.*` | `soothe.internal.loop.*` |
| `soothe.protocol.memory.*` | `soothe.internal.memory.*` |
| `soothe.protocol.policy.*` | `soothe.internal.policy.*` |
| `soothe.plugin.*` | `soothe.internal.plugin.*` |
| `soothe.system.daemon.heartbeat` | `soothe.internal.daemon.heartbeat` |
| Autopilot DETAILED internals | `soothe.internal.autopilot.*` |
| `soothe.cognition.plan.dag_snapshot` | `soothe.internal.plan.dag_snapshot` |
| `soothe.cognition.branch.analyzed/pruned` | `soothe.internal.branch.*` |

Removed (IG-435): `soothe.cognition.plan.step.*` — step UX uses `soothe.cognition.agent_loop.step.*` only.

History replay: `replay_complete` control envelope (not catalog event).

## Phased checklist

- [x] P0: WS reader, handshake, RPC, sender batch (pre-IG-435)
- [ ] P1: `event_visibility` helper, daemon filter, constant/catalog migration
- [ ] P1: Drop `updates` mode; replay_complete control frame
- [ ] P2: event_batch, subscribe tiers, SDK backpressure, RFC-411 catch-up slice

## Verification

```bash
./scripts/verify_finally.sh
uv run pytest packages/soothe-sdk/tests/unit/core/test_event_visibility.py -q
uv run pytest packages/soothe-daemon/tests/unit/daemon/test_client_session.py -q
```
