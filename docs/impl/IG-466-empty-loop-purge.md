# IG-466: Empty-loop purge

**RFC**: [RFC-215](../specs/RFC-215-strangeloop-persistence-backend.md) (schema + reclamation section amended 2026-06-04)
**Lineage**: First implementation of the empty-loop reclamation amendment in RFC-215. The ephemeral-loop GC path (`_periodic_ephemeral_loop_gc`, `list_expired_ephemeral_loops`, `purge_loop_execution_data`) already exists and is reused — this guide extends it with a second pass and renames the entry point.
**Status**: Draft

---

## 1. Motivation

The WebSocket `loop_list` RPC (`packages/soothe-daemon/src/soothe_daemon/protocol/router.py:630`) returns many loops that never carried a real human/AI exchange. Tracing the symptom:

1. `_handle_loop_new` (`router.py:1127`) calls `register_loop(status="created")` then sets `last_message_at = now` (router.py:1243) *before* any user input arrives.
2. `bootstrap_loop_session` (`packages/soothe-sdk/src/soothe_sdk/client/session.py:93`) and desktop `WSManager.open` (`apps/soothe-desktop/src/main/daemon/manager.ts:56`) always call `loop_new` when no `resume_loop_id` is supplied. Every opened tab → permanent row.
3. `_handle_loop_list` (`router.py:644`) and `sqlite_backend._list_loops_sync` (`packages/soothe/src/soothe/core/loop/state/persistence/sqlite_backend.py:266`) return every row ordered by `created_at DESC`. No activity filter.
4. `_periodic_ephemeral_loop_gc` (`packages/soothe-daemon/src/soothe_daemon/server/core.py:739`) only sweeps `is_ephemeral=1` rows. Non-ephemeral empty rows persist forever.

The `agentloop_loops` schema has no signal that distinguishes loops with conversation from those without (`total_goals_completed` undercounts; `thread_ids != []` fires too early). This guide adds two real counters, swaps `loop_new`'s premature `last_message_at` for true activity-driven semantics, renames the periodic GC, and adds a second per-tick pass that reclaims idle empty loops. The change is a clean schema cut — acceptable because no production data exists.

---

## 2. Changes by slice

### Slice A — schema + persistence backend (counters and queries)

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/core/loop/state/persistence/sqlite_backend.py` | Schema DDL (`CREATE TABLE agentloop_loops`): add `human_message_count INTEGER NOT NULL DEFAULT 0`, `ai_message_count INTEGER NOT NULL DEFAULT 0`. Bump `schema_version` default to `'3.2'`. Add new method `increment_loop_message_count(loop_id, human=0, ai=0)` running a single `UPDATE agentloop_loops SET human_message_count = human_message_count + ?, ai_message_count = ai_message_count + ?, last_message_at = ?, updated_at = ? WHERE loop_id = ?` via `_writer_to_thread`. Add new method `list_empty_loops(idle_before, limit=50)` mirroring `list_expired_ephemeral_loops` but with `WHERE human_message_count = 0 AND ai_message_count = 0 AND status != 'running' AND COALESCE(last_message_at, created_at) < ?`. |
| `packages/soothe/src/soothe/core/loop/state/persistence/postgres_backend.py` | Same DDL additions. Same two methods using the existing async pool. Add a partial index in the DDL setup: `CREATE INDEX IF NOT EXISTS idx_agentloop_loops_empty ON agentloop_loops (last_message_at) WHERE human_message_count = 0 AND ai_message_count = 0`. |
| `packages/soothe/src/soothe/core/loop/state/persistence/base_backend.py` | Add abstract methods `increment_loop_message_count(loop_id, human=0, ai=0) -> None` and `list_empty_loops(idle_before, limit=50) -> list[dict]`. |
| `packages/soothe/src/soothe/core/loop/state/persistence/manager.py` | Pass-through methods to the backend (mirrors how `list_expired_ephemeral_loops` is wired at `manager.py:122`). |

### Slice B — counter increment sites

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` | In `_handle_loop_input` (around `router.py:1283`), after the input is successfully enqueued to the loop's isolated queue, call `await d._persistence_manager.increment_loop_message_count(loop_id, human=1)` inside a `try/except Exception` block that logs `WARNING` via `logger.warning("Failed to increment human_message_count for loop %s", loop_id, exc_info=True)` on failure. MUST NOT block the user path. |
| `packages/soothe/src/soothe/core/runner/_runner_strange_loop.py` | At the assistant-output commit site already gated by `loop_message_assistant_output_phase(msg)` (`_runner_strange_loop.py:157` and the second occurrence at `:165`), call `await persistence_manager.increment_loop_message_count(loop_id, ai=1)` once per committed message. Same `try/except` + WARNING pattern. If both `:157` and `:165` are real commit sites (verify before edit), extract a helper `commit_ai_ledger_entry(...)` and call it from both to preserve once-per-message semantics; otherwise inline at the single true site. The runner already has `persistence_manager` and `loop_id` in scope — no new constructor wiring needed. |
| `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` | In `_handle_loop_new`, remove the `"last_message_at": now,` entry from the `meta_updates` dict (currently at `router.py:1241-1245`). Leave the other entries (`is_ephemeral`, `current_workspace`) untouched. Comment one line above: `# last_message_at populated on first counter increment, not at creation.` |

### Slice C — GC unification

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/server/core.py` | Rename `_periodic_ephemeral_loop_gc` to `_periodic_loop_gc` (definition at `server/core.py:739`, plus the task-spawn site that references it). Inside the loop body, after the existing `list_expired_ephemeral_loops` block, add a second block: `expired_empty = await self._persistence_manager.list_empty_loops(idle_before_empty, limit=gc_cfg.batch_size)`. De-duplicate by `loop_id` against the ephemeral batch before iterating. Wrap each `purge_loop_execution_data` call in the existing per-row try/except. Use `idle_before_ephemeral = now - timedelta(hours=gc_cfg.ephemeral_idle_hours)` and `idle_before_empty = now - timedelta(hours=gc_cfg.empty_idle_hours)`. Update the summary log to report both purge counts (e.g. `"Loop GC purged %d ephemeral, %d empty (idle thresholds: %dh / %dh)"`). |
| `packages/soothe-daemon/src/soothe_daemon/server/core.py` | Update any reference to the prior `_periodic_ephemeral_loop_gc` name elsewhere in the file (task spawn, comments). |

### Slice D — configuration

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/config.py` | Rename Pydantic config block `EphemeralLoopGcConfig` → `LoopGcConfig`. Rename field `idle_hours` → `ephemeral_idle_hours` (no alias — clean cut). Add field `empty_idle_hours: int = 24`. Rename the parent attribute on the daemon-config block from `ephemeral_loop_gc` → `loop_gc`. |
| `config/config.template.yml` | Rename the `daemon.ephemeral_loop_gc:` block to `daemon.loop_gc:`. Inside it, rename `idle_hours` to `ephemeral_idle_hours` and add `empty_idle_hours: 24`. Update the inline comment to describe both passes. |
| `config/config.dev.yml` | Mirror the template (CLAUDE.md config-sync rule). Same key renames; `empty_idle_hours` MAY be lower (e.g. `1`) for fast local iteration — decide during PR review. |

### Slice E — tests

| File | Change |
|------|--------|
| `packages/soothe/tests/unit/core/loop/state/persistence/test_increment_loop_message_count.py` | New file. Cases: (1) single human increment updates the row's `human_message_count` and `last_message_at`; (2) single AI increment updates `ai_message_count` and `last_message_at`; (3) concurrent increments via `asyncio.gather` both land — final counter equals the sum; (4) increment on a non-existent `loop_id` is a no-op (no exception); (5) increment with `human=0, ai=0` still refreshes `updated_at`/`last_message_at` (or document that it skips — pick a behavior and assert it). |
| `packages/soothe/tests/unit/core/loop/state/persistence/test_list_empty_loops.py` | New file. Cases: (1) excludes rows with `status='running'`; (2) excludes rows with `human_message_count > 0`; (3) excludes rows with `ai_message_count > 0`; (4) respects the `idle_before` threshold using `COALESCE(last_message_at, created_at)` (insert a row with `last_message_at=NULL` and `created_at` past the threshold → returned; insert one with `last_message_at` after the threshold → excluded); (5) honors `limit`. |
| `packages/soothe-daemon/tests/integration/daemon/test_empty_loop_gc.py` | New file. Cases: (1) call `loop_new` (no input), advance the GC `idle_before` synthetically (e.g. via injected clock or by writing `created_at` in the past), trigger one `_periodic_loop_gc` tick → row deleted, on-disk loop directory removed (assert via `PersistenceDirectoryManager.get_loop_directory(loop_id).exists() is False`); (2) `loop_new` + one `loop_input` + same tick → row survives with `human_message_count == 1`; (3) a row that is both `is_ephemeral=1` and empty is reclaimed by whichever pass fires first — set `ephemeral_idle_hours=1`, `empty_idle_hours=24`, age the row 2 hours → ephemeral pass claims it, no double-purge errors. |

### Slice F — verification

| File | Change |
|------|--------|
| n/a | Run `./scripts/verify_finally.sh` per `CLAUDE.md` mandatory rule (format check, lint, unit tests). All 900+ unit tests MUST pass before commit. |

---

## 3. Non-goals

- **Surfacing counters in `loop_list_response`.** The TUI loop picker and desktop client still receive the same response shape. Adding `human_message_count` / `ai_message_count` to the wire payload is a separate task.
- **On-disconnect immediate purge.** Trigger remains periodic GC only.
- **Migration scripts, dry-run mode, manual purge command.** Clean schema cut; existing tables are recreated by the schema-version bump.
- **Deferring `register_loop` until first `loop_input`.** Bootstrap order (`loop_new` → `loop_subscribe` → first `loop_input`) is preserved.
- **Renaming `last_message_at` → `last_activity_at`.** Flagged for a future RFC pass; out of scope here to keep the diff focused.

---

## 4. Risks and mitigations

- **AI-counter double-count if `_runner_strange_loop.py:157` and `:165` are both real commit sites.** Mitigation: verify with a single targeted read before editing; if both are commit sites, extract a helper that fires exactly once per committed message.
- **Counter UPDATE failures during high concurrency.** Mitigation: single-statement UPDATE is atomic; failure is logged at WARNING and dropped. The idle window absorbs single misses — the next successful increment moves the loop out of the empty set.
- **Race: GC purge concurrent with first `loop_input`.** Mitigation: bounded by the idle window (hours). If observed in practice, add `WHERE human_message_count = 0 AND ai_message_count = 0` to the purge SQL.
- **Schema cut data loss.** Mitigation: per project decision, no production data exists. Sanity-check locally that the recreate path runs cleanly when the daemon starts against an old DB.

---

## 5. Definition of done

1. Schema columns added to both SQLite and PostgreSQL backends; `schema_version` bumped to `'3.2'`.
2. `increment_loop_message_count` and `list_empty_loops` implemented on base, SQLite, PostgreSQL, manager.
3. Human counter increments on accepted `loop_input`; AI counter increments on assistant-output commit; both wrapped in try/except + WARNING.
4. `_handle_loop_new` no longer sets `last_message_at`.
5. `_periodic_loop_gc` runs both passes per tick with de-duplication and per-row error isolation.
6. Config block renamed (`loop_gc` with `ephemeral_idle_hours` + `empty_idle_hours: int = 24`). `config.template.yml` and `config.dev.yml` updated together.
7. Unit + integration tests in Slice E pass.
8. `./scripts/verify_finally.sh` is clean.
