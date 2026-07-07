# IG-405: PostgreSQL Connection Pool Exhaustion Fix

## Goal
Fix PoolTimeout errors caused by unclosed PostgreSQL connection pools in AgentLoop state managers.

## Problem
- Each `AgentLoopStateManager` creates a PostgreSQL connection pool that's never closed
- Up to 3-10 concurrent goals in autonomous mode each create separate pools
- Pool exhaustion: `psycopg_pool.PoolTimeout: couldn't get a connection after 30.00 sec`

## Files Changed (Phase 1 - Per-loop cleanup)
- `packages/soothe/src/soothe/core/agent_loop/state/manager.py`: Added `close()` method
- `packages/soothe/src/soothe/core/agent_loop/state/persistence/manager.py`: Added `close()` method
- `packages/soothe/src/soothe/core/agent_loop/branching/anchor_manager.py`: Added `close()` method
- `packages/soothe/src/soothe/core/agent_loop/engine/agent_loop.py`: Call `close()` in finally block

## Status
✅ Completed (2026-05-07)

---

# IG-406: Shared PostgreSQL Pool for High-Concurrency (200+ Threads)

## Goal
Implement shared pool architecture for 200-thread concurrency support.

## Problem
IG-405 fix (per-loop cleanup) works for low concurrency (3-10 threads).
For 200 threads: 200 × 15 connections = 3000 → exceeds PostgreSQL limit.

## Architecture
```
Daemon → SootheRunner → SharedPostgreSQLPool (size=30)
                      ↓
    AgentLoopStateManager (receives pool reference, no per-loop pool)
```

## Files Changed (Phase 2 - Shared pool)
- `packages/soothe/src/soothe/core/agent_loop/state/persistence/shared_pool.py`: New singleton pool manager
- `packages/soothe/src/soothe/core/agent_loop/state/manager.py`: Accept `shared_pool` parameter
- `packages/soothe/src/soothe/core/agent_loop/state/persistence/postgres_backend.py`: Support externally provided pool
- `packages/soothe/src/soothe/core/runner/__init__.py`: Initialize/close shared pool
- `packages/soothe/src/soothe/core/runner/_runner_agentic.py`: Pass shared pool to AgentLoop
- `packages/soothe/src/soothe/core/runner/_runner_autonomous.py`: Pass shared pool to AgentLoop
- `packages/soothe/src/soothe/core/agent_loop/engine/agent_loop.py`: Pass shared pool to state manager

## Pool Size Configuration
- Default: 30 connections (formula: 25-30 for efficient queuing without DB overload)
- Configurable via `config.persistence.agentloop_pool_size`

## Status
✅ Completed (2026-05-07)