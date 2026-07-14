# IG-403: EventBus event size distribution (streaming)

## Goal

Constant-memory streaming estimate of EventBus JSON wire sizes, logged on an interval while the bus is active; no logs after a configured idle period without publishes.

## Design

- `packages/soothe/src/soothe/daemon/event_size_stats.py`: fixed-bin histogram + Welford mean/variance; one `encode()` per publish when enabled.
- `EventBus.publish` records wire size (same as IPC) before routing.
- `SootheDaemon._periodic_event_size_stats` sleeps `event_size_stats_interval_seconds`, emits if `event_size_stats_idle_pause_seconds` not exceeded since last publish.
- Config: `daemon.event_size_stats_*` in `daemon_config.py` + `config.template.yml` / `config.dev.yml`.

## Verification

`./scripts/verify_finally.sh`
