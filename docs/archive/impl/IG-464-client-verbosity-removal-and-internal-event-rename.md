# IG-464: Client verbosity removal & internal event rename

## Goal

Clients always operate at NORMAL verbosity. Verbosity is a daemon-side concern
(`observability.verbosity`); it does not travel over the wire and is not exposed
through the SDK or CLI. Move four internal-only events under the existing
`soothe.internal.*` cap.

## Changes

**Client-side verbosity removed:**
- `bootstrap_loop_session` (soothe-sdk) no longer accepts `verbosity=`; payload
  no longer carries `verbosity` in `loop_subscribe`.
- `WebSocketClient.send_loop_subscribe` (soothe-sdk) loses `verbosity=`.
- CLI callers (`cli/execution/daemon.py`, `runtime/transport/session.py`) drop
  the hard-coded `verbosity="normal"` kwarg.

**Daemon-side cleanup:**
- `protocol/router.py` stops reading `msg.get("verbosity")`; `loop_subscribe`
  no longer echoes it in `subscription_confirmed`.
- `ClientSession.verbosity` field deleted (logged-but-unused dead state). Real
  filter remains `decide_client_wire_visibility` + catalog `VerbosityTier`.
- `config.observability.verbosity` retained — daemon's own knob, surfaced via
  `daemon_status_response`.

**Internal event renames:**
- `soothe.cognition.plan.batch.started` → `soothe.internal.plan.batch.started`
- `soothe.skill.body.loaded` → `soothe.internal.skill.body.loaded`
- `soothe.mcp.list_changed` → `soothe.internal.mcp.list_changed`
- `soothe.mcp.tool.timeout` → `soothe.internal.mcp.tool.timeout`

All four had no TUI or client-logic consumer (verified by grep). They now flow
through the existing `is_client_broadcast_event_type` prefix gate.

**Bug fix + dead code:**
- `display_policy.is_internal_event` switched from `"internal" in event_type`
  (substring) to `event_type.startswith("soothe.internal.")` (prefix), avoiding
  false positives.
- Deleted `packages/soothe/src/soothe/verbosity_tier.py` — a verbatim
  duplicate of `soothe_sdk.core.verbosity` that nothing imported (the foundation
  `__init__` already re-exports from the SDK).

**VerbosityTier kept.** It's the per-event classification used by 50+
`register_event(..., verbosity=...)` calls; the `soothe.internal.*` prefix is
binary and cannot replace its granularity.

## Files touched

- `packages/soothe-sdk/src/soothe_sdk/client/session.py`
- `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
- `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py`
- `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py`
- `packages/soothe-cli/src/soothe_cli/runtime/policy/display_policy.py`
- `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`
- `packages/soothe-daemon/src/soothe_daemon/server/session.py`
- `packages/soothe/src/soothe/core/events/constants.py`
- `packages/soothe/src/soothe/core/events/catalog.py`
- `packages/soothe/src/soothe/mcp/events.py`
- `packages/soothe/src/soothe/skills/events.py`
- `packages/soothe/src/soothe/verbosity_tier.py` (deleted)
- Tests: `test_session_bootstrap.py`, `test_session_bootstrap_reconnect.py`,
  daemon `test_session.py`, integration `daemon_fixtures.py`,
  `test_daemon_multi_client.py`, `test_daemon_loop_isolation.py`

## Verification

`./scripts/verify_finally.sh` equivalent: ruff format + ruff check + unit tests
across all four packages.

- soothe-sdk: 219/219 passed
- soothe-cli: 355/355 passed
- soothe: 2459 passed, 1 skipped
- soothe-daemon: 473/473 passed
- Lint + format: clean
