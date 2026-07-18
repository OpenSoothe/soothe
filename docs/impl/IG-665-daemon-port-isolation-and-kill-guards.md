# IG-665: Daemon port isolation and agent kill guards

## Goal

Prevent integration tests and agent tools from colliding with or killing the live host daemon on `:8765`.

## Scope

1. Integration fixtures refuse / avoid production WebSocket port `8765`; load tests use ephemeral ports.
2. `kill_process` refuses the daemon PID, self/parent, and listeners on the production WS port; `killpg` will not target the agent process group.
3. Operation security blocks shell `pkill`/`killall`/`soothed stop|restart` patterns that target Soothe.
4. Prompt/tool copy steers agents to `kill_process` on `run_background` PIDs only.

## Verification

- `./scripts/verify_finally.sh`

## Status

**Complete.**
