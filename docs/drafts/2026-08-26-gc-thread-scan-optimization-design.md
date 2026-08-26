---
# GC Thread Scan — Optimization Design

> Status: implemented (2026-08-26). Follow-up to IG-764 Change C.

## 1. Problem

After IG-764 Change C replaced the `thread_ids` metadata list with a
checkpointer prefix scan, the GC path (`_collect_loop_thread_ids` in
`loop_gc.py`) has two issues:

### Issue 1: O(all threads) scan
`runner.list_threads()` returns **every** durability-registered thread
across **all** loops. `_collect_loop_thread_ids` then filters in Python
by `startswith(f"{loop_id}__")`. On a daemon with N loops and T total
threads, every GC purge is O(T), not O(this loop's threads).

### Issue 2: Fork threads are not in the durability index
Fork thread ids (`{main}__{hex5}` execute-step, `{parent}__synth_gc__{uuid}`
synthesis, `{loop_id}__intake__{wire}` intake) are created as LangGraph
`RunnableConfig.thread_id` values. They are **never registered** via
`ThreadContextManager.create_thread()` or
`runner.touch_thread_activity_timestamp()`. Therefore:

- `runner.list_threads()` (durability index) does **not** include them.
- `_collect_loop_thread_ids` finds only the bare `loop_id` main thread.
- `_delete_loop_threads` → `runner.delete_persisted_thread()` deletes
  durability metadata + run directory, but **not** LangGraph checkpoint
  rows.
- `purge_loop_execution_data` deletes `agentloop_checkpoints`/`goal_records`
  rows (the StrangeLoop checkpoint table), but **not** the CoreAgent
  LangGraph checkpoint tables (`checkpoints`, `writes`).

**Net: fork thread checkpoints are orphaned on every loop purge.**

This is a **pre-existing** issue — the old `thread_ids`-from-metadata path
had the same blind spot (it only listed fork ids that were explicitly
appended, which in practice was just `[loop_id]`). But Change C makes it
more visible because we explicitly claimed "reachable via the checkpointer."

## 2. Verified facts

- LangGraph savers (`AsyncSqliteSaver`, `AsyncPostgresSaver`) both expose
  `adelete_thread(thread_id)` and `adelete_for_runs(thread_id)`.
- The runner holds `self._checkpointer` (protected; no public property).
- `core_agent.graph.checkpointer` is accessible once materialized.
- `orchestrator/checkpoint.py` has `thread_kind()` which classifies by
  prefix — could be used to scope deletion.
- Durability's `_find_threads_by_prefix(prefix)` exists on
  `DurabilityBase` but is also O(all) internally (loads full index, filters).

## 3. Approaches

### A. Add `adelete_thread` to the GC path (recommended)

The LangGraph checkpointer already has the right API. Wire it into
`_delete_loop_threads`:

1. Add a method on the runner: `delete_checkpoint_thread(thread_id)` that
   calls `self._checkpointer.adelete_thread(thread_id)` when the
   checkpointer is materialized.
2. In `_collect_loop_thread_ids`, scan the **LangGraph checkpointer** (not
   the durability index) for threads matching `{loop_id}__` prefix. The
   checkpointer's `alist` / SQL queries can filter by `thread_id LIKE`.
3. In `_delete_loop_threads`, call both:
   - `runner.delete_persisted_thread(tid)` (durability + run dir)
   - `runner.delete_checkpoint_thread(tid)` (LangGraph checkpoint rows)

**Tradeoff**: Requires a checkpointer-side prefix scan. For Postgres this
is `SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s`.
For SQLite it's a similar query. Both are O(matching) not O(all).

**Risk**: `self._checkpointer` may be `None` if the agent wasn't
materialized (lazy init). The GC path already handles `runner is None`;
needs a guard for `checkpointer is None`.

### B. Register fork threads in the durability index on creation

Make `execute_step_thread_id` / `synthesis_thread_id` callers also call
`runner.touch_thread_activity_timestamp(fork_id)` so they appear in the
durability index. Then `_collect_loop_thread_ids` finds them via
`list_threads()`.

**Tradeoff**: Adds a durability write on every step execution (hot path).
The durability index is meant for user-visible threads, not internal fork
threads. Pollutes the thread list with ephemeral ids. Not recommended.

### C. SQL-level prefix scan on the checkpoint table

Add a method to the persistence backend that queries the LangGraph
checkpoint table directly:

```sql
SELECT DISTINCT thread_id FROM checkpoints
WHERE thread_id = $1 OR thread_id LIKE $2
```

with params `(loop_id, f"{loop_id}__%")`.

**Tradeoff**: Couples the GC layer to the LangGraph schema (table names,
column names). Breaks if LangGraph changes its schema. Better to use the
saver's `adelete_thread` API (Approach A) which abstracts the storage.

## 4. Recommendation

**Approach A.** It uses the LangGraph saver's own `adelete_thread` API,
which is storage-agnostic and already maintained by LangGraph. The prefix
scan can use `adelete_thread` per-id (after collecting ids via a single
SQL query) or a batch delete if the saver exposes one.

### Implementation sketch

1. **Runner**: add `delete_checkpoint_thread(thread_id)` and
   `list_checkpoint_thread_ids(prefix)` methods.
   - `delete_checkpoint_thread`: calls `self._checkpointer.adelete_thread(tid)`.
   - `list_checkpoint_thread_ids`: queries the checkpointer for thread
     ids matching the prefix. Falls back to `[]` if checkpointer is None.
2. **loop_gc.py**: `_collect_loop_thread_ids` calls
   `runner.list_checkpoint_thread_ids(f"{loop_id}__")` and prepends `loop_id`.
   `_delete_loop_threads` calls both `delete_persisted_thread` and
   `delete_checkpoint_thread` for each id.
3. **Fallback**: when checkpointer is None (lazy, unmaterialized), skip
   checkpoint deletion (same as current behavior — the rows get cleaned
   on the next DB-level purge or remain as orphans, which is tolerable
   for SQLite-embedded dev mode).

## 5. Open questions

- Does `adelete_thread` exist on all LangGraph saver versions we support?
  (Verified on current installed version; need to check minimum version.)
- Should the checkpoint prefix scan live on the runner (GC-specific) or
  on the checkpointer pool (general-purpose)?
- For Postgres, is `thread_id LIKE 'loop__%'` indexed? If not, the scan
  is still O(all checkpoint rows). May need an index on
  `checkpoints(thread_id)`.
