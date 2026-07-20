# IG-553: soothe.log Stability Fixes (Checkpoint, Pool, Tool Friction)

**Created**: 2026-07-06  
**Status**: Implemented  
**Logs**: `~/.soothe/logs/soothe.log` (session 2026-07-06T15:16–19:57)  
**Related**: [IG-549](IG-549-loop-worker-goal-boundary-hardening.md), [IG-550](IG-550-high-performance-persistence.md)

---

## Executive Summary

Analysis of `soothe.log` (18k lines, 5 concurrent loops) surfaced 38 ERRORs and 115 WARNs. Goals completed but loop checkpoint integrity, skill retrieval, and agent tool friction degraded throughput. This IG tracks fixes from P0 (critical) through P3 (low).

| Priority | Issue | Count | Fix |
|----------|-------|-------|-----|
| P0 | `Cannot find goal … in goal_history` | 29 | Stop `load()` clobbering in-memory history; FULL persist on goal start; heal on record |
| P1 | Skillify `PoolTimeout` on pgvector | 9 | Raise default pool_size; retriever retry/backoff |
| P2 | Planner empty `execute_steps` | 4 | Retry prompt hint on validation failure |
| P2 | `insert_lines` missing `line` | 14+ | Default `line=1`; clearer schema description |
| P2 | `read_file` offset past EOF | several | Actionable error (0-indexed hint) |
| P2 | `read_command` invalid tool hallucination | 1+ | Progressive promote guard; invalid-tool hints; `<TOOL_SELECTION>` prompt |
| P3 | `Unknown subagent 'browser_use'` | many | Register factory in built-in map |

---

## P0: goal_history Desync

### Root cause

1. Goal start appends to in-memory `goal_history` and calls `save()` → **INDEX_ONLY** hot write (no `goal_history` in hot index).
2. `ContextEngineGoalContextAdapter.get_execute_briefing()` calls `state_manager.load()` on every execute step.
3. `load()` replaces `_checkpoint` with DB row where `goal_history` is still `[]`.
4. `record_iteration` / `finalize_goal` cannot find `goal_0`.

### Changes

- `StrangeLoopStateManager.get_checkpoint()` — return cached checkpoint without DB round-trip.
- `load()` — merge: never replace in-memory `goal_history` with a shorter DB copy.
- `save(..., include_goal_history=True)` — FULL write when goal boundary changes.
- `strange_loop.py` — goal-start saves use `include_goal_history=True`.
- `record_iteration` / `_apply_goal_finalize_memory` — append missing goal_id as repair.

---

## P1: Vector Pool Exhaustion

- Default `VectorStoreProviderConfig.pool_size`: 5 → 15.
- `config/develop/config.yml`: `pool_size: 20` on `pgvector_dev`.
- `SkillRetriever.retrieve()` — retry search up to 3× with backoff on pool timeout.

---

## P2: Agent Tool Friction

- `InsertLinesSchema.line` default `1` with description noting frontmatter use.
- `normalized_backend` read offset error includes 0-indexed guidance.
- Planner validation retry injects hint when `execute_steps` has empty steps.

### Invalid tool hallucination (`read_command`, path-in-name)

- `ProgressiveToolMiddleware._should_promote_after_invoke()` — promote only catalog tools without invalid-name errors.
- `InvalidToolHintsMiddleware` + `tool_name_hints.py` — append targeted recovery hints on LangGraph invalid-tool errors.
- `SystemPromptMiddleware._build_tool_selection_guidance_section()` — static `<TOOL_SELECTION>` block on every hop.
- `AVAILABLE_TOOLS_PREAMBLE` — clarifies `read_command` does not exist.

---

## P3: browser_use Resolution

- Add `browser_use` to `_get_subagent_factories()` so resolver finds it before plugin registry warms up.

---

## Verification

- Unit tests: checkpoint merge, context adapter `get_checkpoint`, retriever retry, insert_lines default.
- `./scripts/verify_finally.sh`

---

## Production Pool Sizing (50–100 concurrent loops)

Thread-pool mode uses **process-wide singleton pools** (not per-loop):

| Pool | Default | Role |
|------|---------|------|
| `thread_pool.max_pool_size` | 96 | Concurrent synthesis threads |
| `checkpointer_pool_size` | 64 | LangGraph checkpoint writes |
| `sloop_pool_size` | 64 | StrangeLoop checkpoint/index |
| `metadata_pool_size` | 32 | Durability/metadata (shared singleton) |
| `vector_stores[].pool_size` | 48 | Skillify pgvector search |

**Approximate PG connections per daemon process** ≈ 64 + 64 + 32 + 48 = **208** server-side (PgBouncer multiplexes). Do not multiply by loop count.

Worker-pool mode multiplies checkpointer + sloop per process — use smaller pool sizes (4–8) per worker.
