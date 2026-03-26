# IG-015: RFC Gap Closure and Compatibility Hard-Cut

## Objective

Polish Soothe by removing backward-compatibility code paths, fixing shutdown resource leaks, and closing implementation gaps against RFC-0001 through RFC-0006.

## Scope

1. Hard-cut backward compatibility paths and legacy re-export modules.
2. Fix `bug1.md` TUI shutdown issue (`AsyncConnectionPool` workers pending on exit).
3. Close RFC-0006 gaps, including:
   - rename config value `memory_backend: store` to `memory_backend: keyword`
   - ingest recalled memories into context ledger during pre-stream
4. Close RFC-0001 through RFC-0005 gaps (critical/high/medium), including:
   - middleware-based policy checks for tool/subagent actions
   - subagent context projection injection
   - configurable durability backend with LangGraph checkpointer targets (SQLite/Postgres)
   - plan step lifecycle event emission
   - Skillify indexing event stream + hash-cache bootstrap
   - Weaver `validate_package` node with hard-fail behavior

## Confirmed Decisions

- Compatibility policy: hard-cut removal of legacy APIs.
- RFC priority: implement all severities.
- Policy enforcement: middleware interception.
- Durability strategy: LangGraph checkpointer with configurable SQLite/Postgres targets.
- Subagent projection strategy: task delegation hook.
- Memory backend rename: replace-only (`store` removed, `keyword` required).
- Recalled memory behavior: ingest into context ledger.
- Plan step model: hybrid correlation.
- Skillify index events: callback to stream forwarding.
- Weaver validation failure: hard fail.

## Implementation Plan

### Phase 1: Compatibility Hard-Cut

- Remove legacy packages and duplicate implementation modules under:
  - `src/soothe/context/`
  - `src/soothe/memory_store/`
  - `src/soothe/vector_store/`
  - `src/soothe/persistence/`
  - `src/soothe/planning/`
  - `src/soothe/policy/`
  - `src/soothe/durability/`
  - `src/soothe/remote/`
  - `src/soothe/cli/runner.py`
  - `src/soothe/utils/_progress.py`
  - `src/soothe/utils/_streaming.py`
- Update all imports in source/tests/examples/docs to canonical backends/core paths.

### Phase 2: `bug1.md` Shutdown Fix

- Extend `SootheRunner.cleanup()` to close:
  - context vector store resources
  - memory vector store resources
  - Skillify background indexer and store
  - Weaver reuse index/store resources
- Ensure `cleanup()` runs before loop shutdown in Rich TUI and daemon stop paths.
- Add explicit closers where required (e.g., Weaver `ReuseIndex.close()`).

### Phase 3: RFC-0006 Closure

- Rename `memory_backend` enum/config/docs/tests from `store` to `keyword`.
- Update resolver fallback messaging and semantics.
- In pre-stream flow, ingest recalled memories into context before projection/enrichment.
- Correct user docs for memory persistence path and keyword semantics.

### Phase 4: RFC-0001..0005 Closure

- Add policy middleware that checks tool calls and delegation actions.
- Add subagent projection middleware/hook for `task` delegations.
- Add configurable durability backend and checkpointer builder for SQLite/Postgres.
- Emit `soothe.plan.step_started` and `soothe.plan.step_completed` events.
- Add Skillify index lifecycle event callback plumbing.
- Add Weaver `validate_package` step and enforce hard-fail on violations.

### Phase 5: Sync and Verification

- Update impacted RFC/impl docs/config examples.
- Update examples/tests for latest APIs.
- Run lint and targeted tests, then broader test pass.

## Acceptance Criteria

1. No legacy import paths remain in source/tests/examples.
2. Exiting TUI does not emit pending-task/event-loop-closed errors from vector pools.
3. `memory_backend: keyword` is the only supported keyword-memory config value.
4. Recalled memories are ingested into context ledger pre-stream.
5. Policy checks run on tool calls and subagent delegation points.
6. Durability backend target is configurable (SQLite/Postgres checkpointer mode).
7. Plan step events are emitted during execution.
8. Skillify indexing emits stream-visible lifecycle events.
9. Weaver validates generated package and hard-fails on validation/policy failure.
