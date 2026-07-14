# IG-604: Skillify Daemon Shared Service

**Created**: 2026-07-07  
**Status**: Implemented  
**Related**: [IG-543](IG-543-skill-runtime-discovery.md), [IG-561](IG-561-global-postgres-pool-registry.md)

---

## Summary

Replace the Skillify **subagent** with a daemon-shared `SkillifyService` in `foundation.skillify`. One indexer + retriever per process, started eagerly at daemon boot (after shared PG pool pre-open), shared across all loops/workers for semantic skill search via `search_skills`.

## Changes

| Area | Change |
|------|--------|
| Package | New `packages/soothe/src/soothe/foundation/skillify/` (`SkillifyService`, indexer, retriever, warehouse) |
| Config | Top-level `skillify:` section in config YAML |
| Daemon | `SootheDaemon.start()` starts service after `preopen_shared_postgres_pools`; worker warmup starts per subprocess |
| Removed | `subagents/skillify/` subagent (LangGraph, plugin, wire routing) |
| Consumers | `skills/search.py`, Weaver plugin use `get_skillify_service()` / `start_skillify_service()` |
| PG | Indexer `stop()` skips `vector_store.close()` when pool is registry-owned |
| Perf | Eager indexing at boot; in-flight retrieve dedup for identical queries |

## Config

```yaml
skillify:
  enabled: true
  warehouse_paths: []
  index_collection: soothe_skillify
  index_interval_seconds: 300
  retrieval_top_k: 10
```

## Process model

- **thread_pool**: single daemon `SkillifyService`, shared via module singleton
- **worker_pool**: one service per worker subprocess at warmup (not per loop)
- **CLI / in-proc**: lazy start on first `retrieve()` when daemon has not pre-started

## Worker pool PG budget

When `worker_pool` is enabled, each subprocess owns its own vectors pool. Size `vectors_pool_size` so `N_workers × pool_size + daemon pools ≤ PG max_connections`.

## Verification

- `./scripts/verify_finally.sh`
- `search_skills` semantic fill works with daemon service running
- No `skillify` in resolved subagent list
