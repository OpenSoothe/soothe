# IG-561: Global PostgreSQL Connection Pool Registry

**Created**: 2026-07-07  
**Status**: Implemented  
**Related**: [IG-549](IG-549-loop-worker-goal-boundary-hardening.md), [IG-553](IG-553-soothe-log-stability-fixes.md)

---

## Summary

Consolidate daemon PostgreSQL access behind `PostgresPoolRegistry`: one `AsyncConnectionPool` per database (`checkpoints`, `metadata`, `vectors`). Eliminate per-loop and per-component owned pools that exceeded PG `max_connections=200`.

## Changes

| Phase | Change |
|-------|--------|
| P0 | `CheckpointAnchorManager.create()` uses shared checkpoint pool |
| P0 | Daemon `_persistence_manager` + autopilot stores inject shared pools |
| P1 | `PostgresPoolRegistry` module + daemon lifecycle via `pools.py` |
| P1 | Unified `checkpoints_pool_size`; removed legacy `checkpointer_pool_size` / `sloop_pool_size` |
| P2 | `PGVectorStore` registry-backed + pool timing config |
| P2 | Skillify search semaphore + remove `list_records(10000)` per retrieve |
| P2 | Dev config budget: 32+16+16 = 64 total pool max |

## Config (dev)

```yaml
persistence:
  checkpoints_pool_size: 32
  metadata_pool_size: 16
  vectors_pool_size: 16
  postgres_pool_min_size: 4
```

## Verification

- `./scripts/verify_finally.sh`
- No `pool=32 owned` log lines from anchor manager under concurrent loops
- Pool stats logged every 5 min from daemon maintenance
