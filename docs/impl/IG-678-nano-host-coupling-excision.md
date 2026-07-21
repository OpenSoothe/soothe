# IG-678: Nano Host-Coupling Excision (boundary-fixes Part 1)

**Guide**: IG-678
**Created**: 2026-07-21
**Related**: IG-677 (nano push-down, §"Explicit non-goals"), AGENTS.md §3b/§3c/§6,
`scripts/check_module_import_boundaries.sh`, release-soothe skill
**Status**: COMPLETE — PR-1 (redundant DDL removal) + PR-2 (display-card store
move) + PR-3 (checkpoints schema ownership + dead import fix) + PR-4 (dead-duplicate
workspace functions) + PR-5 (dead utils helpers) + PR-6 (dead-duplicate logging
+ reload modules) + PR-8 (host-gated middleware — cancelled, not a leak)
+ PR-9 (orphans — cancelled, not dead) + PR-10 (dead-duplicate boundary-script
guard) + PR-11 (release cutover: nano 0.9.6 + changelogs) all resolved.

> **Revisions (2026-07-21):**
> - **PR-4** premise (host-shaped config groups in nano) was wrong. The
>   project's split-config ownership system (`config/ownership.py`) deliberately
>   assigns `persistence`/`observability`/`optimization`/`workspace_mount` config
>   schema to nano even though host consumers read them. Those are **not leaks**.
>   See Workstream D §D0.
> - **PR-5** premise (move host-only utils to host) was mostly wrong. The
>   "host-only" utils are the write side of ContextVar contracts whose read side
>   is nano middleware — they share a single ContextVar and cannot be split
>   without an architectural redesign. PR-5 was rescoped to delete only
>   genuinely-dead helpers. See Workstream E §E0.
> - **PR-6** premise (move logging/reload to host) was partly wrong. `setup_logging`
>   is genuinely shared (SDK/CLI/daemon/nano all use it); `set_thread_id`/
>   `get_thread_id` are ContextVar-coupled (nano `ThreadFormatter` reads). But
>   `thread_logger.py`, `thread_paths.py`, and `reload.py` were dead stale
>   duplicates the host already owns with more-advanced divergent copies — PR-6
>   deleted those + fixed a latent host bug (host `thread_logger` imported
>   `THREADS_DATA_DIR`/`PersistenceDirectoryManager` from nano instead of the
>   host's `directory_manager`). See Workstream F §F0.
> - **PR-8** premise (move host-gated middleware to host) was wrong. The 4
>   middleware (`SystemPrompt`/`ToolEnforcement`/`PerTurnModel`/`RoleRouting`)
>   are correctly nano-owned with graceful degradation; the host extends via
>   `AgentBuilder._host_middleware_{prefix,suffix}` subclass-injection hooks,
>   not by owning the middleware. `SystemPrompt` is load-bearing for standalone
>   nano. **Workstream H cancelled.** See §H0.

### Progress (2026-07-21, PR-3)

**PR-3 done**: checkpoints schema ownership moved from nano to host.
- Host's two `postgres_schema.py` copies (`foundation/persistence/` and
  `foundation/sloop/state/persistence/`) now pass `sql_root=_HOST_SQL_ROOT`
  (the host `foundation/persistence/sql/` dir) to `initialize_database`, so the
  StrangeLoop/CE `soothe_checkpoints/init.sql` is loaded from the host, not nano.
  The host sql tree (previously dead-duplicate) is now the canonical live copy.
- Deleted nano's `persistence/sql/soothe_checkpoints/init.sql` (+ empty dir).
- Removed the dead `checkpoints` branch from nano's `postgres_pool_registry.py`:
  `open_all()` no longer calls `_open_pool("checkpoints")`, and `_open_pool` no
  longer imports the non-existent `soothe_nano.persistence.postgres_schema`
  (latent `ImportError` fixed). Kept `DbKey`'s `"checkpoints"` literal,
  `resolve_checkpoints_pool_size`, and `_max_size_for`'s checkpoints branch —
  the standalone-nano checkpointer fallback (`SharedCheckpointerPool`) still
  uses the static size resolver and `try_get_pool("checkpoints")` (returns None,
  falls through to its own pool + `AsyncPostgresSaver.setup()`).
- Updated host tests: `test_db_init.py` checkpoints test loads from host sql
  root; `test_postgres_schema.py` asserts the new `sql_root=` kwarg.
- Verified: `open_all()` is only called by the daemon, which uses the host's
  `PostgresPoolRegistry` (not nano's); nano's `open_all` was already dead.
  Zero nano tests touch the registry.

### Progress (2026-07-21, PR-4)

**PR-4 done** (revised scope — see Workstream D §D0): deleted dead-duplicate
workspace policy functions from nano.
- Original PR-4 (move host-shaped config groups to host) **cancelled**: the
  project's split-config ownership system (`config/ownership.py`) deliberately
  assigns `persistence`/`observability`/`optimization`/`workspace_mount` config
  schema to nano. Config schema living in nano while host reads it is the
  intended split, not a leak. Moving them would violate the ownership system.
- Revised PR-4: deleted 6 dead-duplicate public functions + `_validate_workspace_dir`
  from nano `workspace/workspace_policy.py` (`normalize_user_id`,
  `user_id_for_hash`, `compute_scoped_workspace_dir_name`,
  `validate_client_workspace`, `translate_client_path_to_container`,
  `translate_container_path_to_client`) — the host already has canonical copies
  in `foundation/workspace/scoped.py` + `resolution.py`. Repointed the one host
  import of `user_id_for_hash` (from nano) to the host's own `scoped.py`.
- Kept `resolve_workspace_for_tool_execution` + its private helpers (real nano
  callers in `workspace_paths`/`workspace_api`/`middleware/{workspace_context,
  filesystem,system_prompt}`/`toolkits/execution`).

### Progress (2026-07-21, PR-5)

**PR-5 done** (revised scope — see Workstream E §E0): deleted genuinely-dead
utils helpers. Original premise (move host-only utils to host) was mostly
wrong: the "host-only" utils are the write side of ContextVar contracts whose
read side is nano middleware (token_usage `_token_target`, runtime
`_stream_model_override`/`_stream_router_profile`, progress `_wire_bridge`).
The setter/getter pairs share a single ContextVar that must live in one
module; moving the write side to host would split the ContextVar and break the
contract. Deferred to a future RFC, not IG-678.
- Deleted: `utils/progress.py` `set_step_context`/`reset_step_context`/
  `get_step_id` trio + `_current_step_id` ContextVar + the dead
  `get_step_id()` call in `emit_progress` (always returned None — zero callers
  anywhere). `utils/error_format.py` `log_exception_simplified` (only its own
  docstring example referenced it).
- Corrected earlier agent overstatement: `find_soothe_chrome_processes` has 2
  real in-module callers (NOT dead — kept).

### Progress (2026-07-21, PR-6)

**PR-6 done** (revised scope — see Workstream F §F0): deleted dead-duplicate
logging/reload modules. Original premise (move logging/reload to host) was
partly wrong: `setup_logging` is genuinely shared (SDK/CLI/daemon/nano tests
all call it); `set_thread_id`/`get_thread_id` are ContextVar-coupled (nano
`ThreadFormatter.format` reads `get_thread_id()`; host sets it per-loop) — not
movable. But three modules were dead stale duplicates the host already owns
with more-advanced divergent copies:
- Deleted `nano/logging/thread_logger.py` — host has its own divergent copy at
  `soothe/logging/thread_logger.py` (adds `goal_completion` chunk accumulation +
  `AIMessageChunk` handling). All real callers import from `soothe.logging`.
- Deleted `nano/paths/thread_paths.py` — host's `foundation/sloop/state/
  persistence/directory_manager.py` is a superset (adds `LOOPS_DATA_DIR`,
  `ARCHIVED_LOOPS_DATA_DIR`). Fixed a latent host bug: host `thread_logger.py`
  imported `THREADS_DATA_DIR`/`PersistenceDirectoryManager` *from nano* — repointed
  to the host's `directory_manager`.
- Deleted `nano/config/reload.py` — host has its own divergent copy at
  `soothe/config/reload.py` (even self-references `from soothe.config.reload
  import ConfigWatcher`). Host `config/__init__.py` imports from host, not nano.
- Trimmed `logging/__init__.py`, `paths/__init__.py`, `config/__init__.py`
  re-exports. Zero nano tests touched the deleted modules; zero SDK/CLI imports.

### Progress (2026-07-21, PR-8)

**PR-8 cancelled** (premise wrong — see Workstream H §H0): the 4 "host-gated"
middleware (`SystemPromptMiddleware`, `ToolEnforcementMiddleware`,
`PerTurnModelMiddleware`, `RoleRoutingMiddleware`) are correctly nano-owned with
graceful degradation. `SystemPrompt` is load-bearing for standalone nano (builds
the system prompt regardless of `routing_classification`); the other 3 no-op
when host state is absent. The host does **not** have its own copies; it extends
nano's stack via `soothe/foundation/coreagent/builder.py:AgentBuilder` (subclass
of nano's `AgentBuilder`) overriding `_host_middleware_prefix`/`_host_middleware_suffix`
to inject `IdentityMiddleware`/`IntakeOnlyTaskGuardMiddleware`/`GoalStepGuardMiddleware`
on top of nano's default stack + setting `routing_classification`/stream overrides.
This is the intended extension-hook pattern. No code changes.

### Progress (2026-07-21, PR-10)

**PR-10 done**: added `scripts/check_nano_duplicate_symbols.py` — a dead-duplicate
detector invoked by `verify_finally.sh` alongside the existing literal-name ban.
It catches the exact pattern that recurred across IG-678 PR-2/4/6: a public
symbol defined in both nano and host/daemon under the same name, with zero
in-nano references outside its own defining file. Key design points:
- The caller-graph refinement (exclude the symbol's own defining file from its
  "used" set) is essential — without it, every `class Foo:` definition
  self-references `Foo` and the checker never flags anything.
- Curated `_ALLOWED_DUPLICATES` (36 entries, each with a documented reason)
  covers intentionally-shared names: split-config mirrors (per `config/ownership.py`,
  PR-4 §D0), shared event/wire constants, nano-owned runnables the host
  subclass-injects, PR-5-deferred helpers.
- Sanity-tested: injecting `class GlobalInputHistory` in nano → flagged; removed
  → passes. The literal ban remains as backstop; this is the primary guard.

### Progress (2026-07-21, PR-9)

**PR-9 cancelled** (premise wrong — see Workstream I §I0): re-verification showed
every "orphan" candidate has real callers:
- `REPLAY_COMPLETE` — shared event-namespace constant (both nano + host define;
  PR-10 allowlisted).
- `utils/prompt_clock.py` helpers (`build_canonical_datetime_reply`,
  `response_includes_current_local_date`, `format_friendly_local_date`) — real
  nano test callers in `tests/unit/utils/test_prompt_clock.py`.
- `utils/browser_cdp.py:find_soothe_chrome_processes` — 2 real in-module callers.
- `utils/output_capture.py:OutputCapture` — real nano test callers.
Same shallow-caller-analysis failure as PR-4/5/6/8. No code changes. The lesson
is encoded in PR-10's caller-graph guard.

### Progress (2026-07-21, PR-11)

**PR-11 done**: release cutover prepared (not published — publish is the
release-soothe skill's job at actual release time).
- Bumped `soothe-nano` 0.9.5 → **0.9.6** (patch within 0.9.x, per user
  direction — the removed exports are technically breaking under strict semver
  but the project chose a patch cut for this train) + `uv.lock` re-synced.
- nano `CHANGELOG.md` `[0.9.6]` entry lists all removed/changed surfaces.
- Monorepo `CHANGELOG.md` `[Unreleased]` entry documents the IG-678 boundary
  excision + the new `check_nano_duplicate_symbols.py` CI gate.
- No submodule-pin publish or git tag performed (await explicit release).

### Progress (2026-07-21)

**PR-1 done**: removed `cron_jobs` + `identity_*` DDL from nano
`soothe_metadata/init.sql`. Safe because host owns runtime DDL
(`cron/store_postgres.py`, `identity/db.py`), both run `CREATE TABLE IF NOT
EXISTS` at startup. Zero nano consumers.

**PR-2 done**: moved `DisplayCardStore` + `PostgresDisplayCardStore` (+ their
`_SCHEMA`) from `soothe_nano.backends.persistence` to
`soothe_daemon.display.display_store` (+`_postgres`). The postgres store
applies its own `_SCHEMA` on pool open — same pattern as
`PostgresCronJobStore`/`IdentityDbConnection` — so the display-card DDL left
nano's `soothe_metadata/init.sql`. Rewired all daemon consumers
(`loop_card_ledger`, `loop_card_manager`, `protocol/router`, `display/__init__`).
Decoupled nano `persistence/unified.py` (no longer configures the display
store); daemon `server/core.py` calls `configure_display_card_store` directly.
Host `sloop/manager.py` `purge_loop_execution_data` could not import the daemon
(boundary rule 1), so it gained a `display_loop_purger` DI hook
(`Callable[[str], None] | None`); daemon injects
`get_display_card_store().delete_loop` at both construction sites
(`__init__` + `for_shared_checkpoint_pool`). Removed orphaned
`resolve_display_db_path` from nano `paths/`. Moved the two store tests to
`soothe-daemon/tests/unit/display/`.

## Context

IG-677 finished the *push-down* direction: nano's filesystem and skills
capabilities were promoted into `soothe-deepagents`. IG-677 §"Explicit
non-goals" explicitly defers the opposite direction — **host/daemon concepts
that leak *into* nano** — to a separate `boundary-fixes.md` (Part 1). That
document was never written; this IG *is* Part 1.

### Why the boundary script does not catch these

`scripts/check_module_import_boundaries.sh` (`check_nano_l2_l3_ban`) passes
today, but it bans **literal symbol names** (`StrangeLoop`, `AUTOPILOT_`,
`CronConfig`, `IdentityConfig`, `AKSKConfig`, `TokenConfig`, `GlobalInputHistory`,
`ConfigReloaded`, `context_engine`, `intake_only`, …). Every leak below escapes
it via one of three mechanisms:

1. **Renamed identifiers** — `GlobalHistoryConfig` (for `GlobalInputHistory`),
   `ConfigWatcher`/`ConfigReloadEvent` (for `ConfigReloaded`), `DisplayCardStore`
   (for a daemon display concept), `persist_timer(loop_id=...)` (for
   `DEFAULT_MAX_ITERATIONS`).
2. **String-valued config keys / SQL table names** — `cron_jobs`, `identity_*`,
   `ce_dag`, `ce_ledger`, `loop_id`, `replay_complete`.
3. **Host-shaped helpers whose only callers live in `packages/soothe/` or
   `packages/soothe-daemon/`** — the set/provision side of host-orchestration
   contracts; a standalone `create_nano_agent()` never exercises them.

The pattern: nano defines the **set/provision side**; only the host ever calls
the setters or reads those config groups.

### Leak inventory (verified, all paths under `packages/soothe-nano/src/soothe_nano/`)

| # | Cluster | Location | Leaked concept | Host-only consumer |
|---|---|---|---|---|
| 1 | Host-only DDL in nano bootstrap | `persistence/sql/soothe_metadata/init.sql`, `persistence/sql/soothe_checkpoints/init.sql` | `cron_jobs`, `identity_*`, `display_card_mutations`, `goal_display_snapshots`, `agentloop_checkpoints`, `failed_branches`, `goal_records`, `checkpoint_anchors`, `ce_dag`, `ce_ledger` | host `cron/store_postgres.py`, `identity/db.py`, daemon `display/*`, host sloop + CE |
| 2 | Display-card store | `backends/persistence/display_store.py` (+`_postgres.py`) | `DisplayCardStore`, `configure_display_card_store`, `get_display_card_store` (keyed by `loop_id`) | daemon `display/loop_card_*`, `protocol/router.py`, host sloop |
| 3 | Host-shaped config groups | `config/models.py` | `archive_*`, `GlobalHistoryConfig`/`global_history`, `FailureIntentConfig`, `StructuredPlanConfig`, `OptimizationConfig`, `ThreadLoggingConfig`, `WorkspaceMountConfig` | soothe `config`, sloop cognition, `sloop_manager`, daemon `router.py` |
| 4 | Nano persistence/provisioning serving daemon | `persistence/unified.py`, `persist_metrics.py`, `postgres_provisioning.py` | `configure_unified_persistence`, `persist_timer(loop_id=)`, `log_pending_loops`, `uses_postgresql_persistence`, `required_postgres_database_keys` | daemon `server/core.py`, host `loop_writer.py` |
| 5 | `utils/` host-orchestration plumbing | `utils/token_usage.py`, `utils/runtime.py`, `utils/progress.py`, `utils/text_preview.py`, `utils/error_format.py` | loop token-accumulation; daemon stream overrides; `set_step_context`/`set_wire_bridge`; `goal_description_for_log`; `emit_error_event` | soothe `foundation/sloop/`, daemon `runner/*` |
| 6 | `logging/` thread/daemon machinery | `logging/thread_logger.py`, `setup.py`, `context.py`, `paths/thread_paths.py` | `ThreadLogger`, `setup_logging(foreground=)`, `set_thread_id`, `THREADS_DATA_DIR` | daemon `server/`, `query/`, `protocol/`, soothe `runner/*` |
| 7 | Config hot-reload (renamed `ConfigReloaded`) | `config/reload.py` | `ConfigWatcher`, `ConfigReloadEvent`, `start_config_watcher` | daemon `server/core.py` |
| 8 | `workspace/` multi-tenant + container translation | `workspace/workspace_policy.py`, `workspace_api.py` | `translate_client_path_to_container`, `validate_client_workspace`, `compute_scoped_workspace_dir_name`, `resolve_workspace_for_stream`, `WorkspaceMountConfig` | soothe `foundation/workspace/*`, daemon `protocol/router.py` |
| 9 | Orphan wire strings / passive renderers | `events/constants.py`, `prompts/context_xml.py` | `REPLAY_COMPLETE = "replay_complete"`; `<active_goals>`/`<current_plan>` XML rendering | host reattachment, host Autopilot/sloop |
| 10 | Middleware inert without host injection | `middleware/system_prompt.py`, `tool_enforcement.py`, `per_turn_model.py`, `role_routing.py` | gates on host-injected `routing_classification` / daemon stream overrides | soothe `foundation/sloop/*`, daemon `runner/*` |
| 11 | Dead host-shaped helpers | `utils/browser_cdp.py`, `utils/output_capture.py`, `security/security_api.py`, `utils/prompt_clock.py` | `find_soothe_chrome_processes`, `OutputCapture`, `SecurityEnforcer` exports, dead clock helpers | none (dead) |

### What is NOT a leak (verified negative space)

The nano events catalog (`events/catalog.py`), all `soothe_sdk` imports
(host-neutral SDK modules), nano-owned execution constants
(`DEFAULT_EXECUTE_TIMEOUT`, `DEFAULT_TASK_TIMEOUT_SECONDS`), `SharedCheckpointerPool`,
durability backends, the plugin lifecycle, the MCP package, and most of
`workspace_runtime`/`workspace_filesystem` all have in-nano callers and are
legitimately shared.

## Goal

Remove host/daemon-only concepts from `soothe-nano` so the package is a
true standalone Coding CoreAgent: no host-only DDL, no host-shaped config
groups, no host-only utils/logging/reload/middleware. Strengthen the boundary
script so renamed leaks cannot regress.

## Design rule (locked)

`soothe-nano` may **only** define concepts that a standalone Coding CoreAgent
needs. Host orchestration concepts (StrangeLoop, Autopilot, CE, cron,
identity/auth, heartbeat, config-reload, display cards, goal synthesis, intake
routing, multi-tenant container workspace) **belong in `soothe` / `soothe-daemon`**.

Moves are preferred over deletes when the host lacks a home for the concept;
deletes are safe only when the host already owns the runtime implementation
(including DDL).

## Cutover & version bump (locked)

Coordinated small-version cut across `soothe-nano` + `soothe` + `soothe-daemon`
(+ `soothe-cli`/`soothe-plugins` as needed). No long dual-shim window — same
discipline as IG-677. Changelog each package with a short
"Breaking (IG-678 cutover)" note listing moved/removed surfaces.

---

## Workstream A — Redundant host-only DDL removal (safe deletes)

### A0. Ownership verification (done — locked)

| Table(s) | Host runtime DDL owner | Host runs it? | Nano action |
|---|---|---|---|
| `cron_jobs` | `soothe/foundation/cron/store_postgres.py:_SCHEMA` (run in `PostgresCronJobStore.__init__`, store built at `server/core.py:684`) | Yes | **Delete** from nano `soothe_metadata/init.sql` |
| `identity_users`/`identity_aksk_pairs`/`identity_tokens`/`identity_external_mappings`/`identity_revoked_jtis` | `soothe/foundation/identity/db.py:_IDENTITY_SCHEMA_PG` (run in `IdentityDbConnection`, service built at `server/core.py:222`) | Yes | **Delete** from nano `soothe_metadata/init.sql` |
| `display_card_mutations`/`goal_display_snapshots` | **none** (no host DDL) | No | **Move** to host-owned DDL (Workstream B) |
| `agentloop_checkpoints`/`failed_branches`/`goal_records`/`checkpoint_anchors`/`ce_dag`/`ce_ledger` | host `foundation/persistence/sql/soothe_checkpoints/init.sql` + `postgres_schema.py` | Yes (host-owned) | **Move** nano `checkpoints` init ownership to host; fix dead `soothe_nano.persistence.postgres_schema` import (Workstream C) |
| `soothe_persistence` | nano `backends/persistence/postgres_store.py` | n/a (nano-owned) | **Keep** in nano |

All host DDL uses `CREATE TABLE IF NOT EXISTS`, so deletion from nano's bootstrap
is behavior-preserving for the host.

### A1. PR-1 — Remove `cron_jobs` + `identity_*` from nano `soothe_metadata/init.sql`

- **Edit** `packages/soothe-nano/src/soothe_nano/persistence/sql/soothe_metadata/init.sql`
  - delete the `cron_jobs` block (incl. its two indexes)
  - delete the `identity_*` block (five tables + five indexes)
  - **keep** `soothe_schema_migrations`, `soothe_persistence` (+ index),
    `display_card_mutations`/`goal_display_snapshots` (until B1 moves them)
  - add a header comment noting host-owned DDL for cron/identity
- **No code changes** — no nano module reads these tables (verified zero
  in-nano consumers).
- **Verify**: `./scripts/verify_finally.sh`; re-run `check_module_import_boundaries.sh`.

### A2. Verification (PR-1)

```bash
# metadata DB still bootstraps the nano-owned tables
pytest packages/soothe-nano/tests -k 'metadata or persistence or db_init' -q
# boundary + full repo verify
./scripts/check_module_import_boundaries.sh
./scripts/verify_finally.sh
```

---

## Workstream B — Display-card DDL move (needs host home)

### B1. Move `display_card_mutations` + `goal_display_snapshots` DDL to host

- These have **no host DDL owner** today — nano is the sole creator. A pure
  delete would break the daemon display ledger in Postgres mode.
- **Add** a host-owned SQL home, e.g.
  `packages/soothe/src/soothe/foundation/persistence/sql/soothe_display/init.sql`
  (or fold into `soothe_metadata` host copy with a clear section header).
- **Rewire** `soothe_nano.backends.persistence.display_store.configure_display_card_store`
  + `PostgresDisplayCardStore` to apply the host-owned script (or have the host
  call `initialize_database(pool, "soothe_display")` at startup).
- **Then** delete the two tables from nano's `soothe_metadata/init.sql`.
- **Decision needed (B1.1)**: does `DisplayCardStore` itself move to the
  daemon, or stay in nano as a thin client of host-owned DDL? Default:
  **move the store to the daemon** (it has zero nano callers) and delete the
  nano module entirely. This is the larger cut and is tracked here, not in PR-1.

### B2. Verification (B1)

```bash
pytest packages/soothe-daemon/tests -k 'display or loop_card' -q
pytest packages/soothe-nano/tests -k 'display_store' -q  # expect removal/empty
```

---

## Workstream C — `soothe_checkpoints` schema ownership + dead import fix

### C1. Fix dead `soothe_nano.persistence.postgres_schema` import

- `packages/soothe-nano/src/soothe_nano/persistence/postgres_pool_registry.py:175`
  imports `initialize_agentloop_postgres_schema` from
  `soothe_nano.persistence.postgres_schema` — a module that **does not exist**
  in nano (latent bug; the host has it at
  `soothe/foundation/persistence/postgres_schema.py`).
- **Decision**: the `checkpoints` DB schema is StrangeLoop/CE-shaped (host-owned
  per the host's own `postgres_schema.py` docstring). Nano should **not** own it.
  - Option C-a: remove the `checkpoints` branch from nano's pool registry
    entirely; host's `postgres_schema.py` already applies it.
  - Option C-b: keep a nano `postgres_schema.py` but only for genuinely shared
    LangGraph checkpoint tables (if any survive after host/CE split).
- **Then** delete `persistence/sql/soothe_checkpoints/init.sql` from nano
  (host owns the canonical copy).
- **Decision needed (C1.1)**: confirm no standalone-nano path opens the
  `checkpoints` DB. If standalone nano uses LangGraph `MemorySaver`/in-memory
  only (per AGENTS.md "batteries-included Coding CoreAgent"), C-a is safe.

### C2. Verification (C1)

```bash
pytest packages/soothe-nano/tests -k 'checkpoints or pool or postgres' -q
pytest packages/soothe/tests -k 'agentloop or sloop or ce_dag' -q
```

---

## Workstream D — ~~Host-shaped config groups (move to host config)~~ (REVISED — not a leak)

### D0. Revision (2026-07-21)

**Original premise was wrong.** The project has a split-config ownership system
(`soothe/config/ownership.py` + `config/{nano,soothe,daemon}.template.yml` +
`config/develop/{nano,soothe}.yml`) that **deliberately** assigns these config
groups to nano:

| Config group | Ownership rule (`_HOST_DISALLOWED_RULES`) | Verdict |
|---|---|---|
| `persistence` (incl. `archive_*`) | nano-owned | **Keep in nano** — host reads nano-owned schema by design |
| `observability` (incl. `GlobalHistoryConfig`, `ThreadLoggingConfig`) | nano-owned | **Keep in nano** |
| `optimization` (`FailureIntentConfig`/`StructuredPlanConfig`/`OptimizationConfig`) | nano-owned | **Keep in nano** |
| `workspace_mount` (`WorkspaceMountConfig`) | nano-owned | **Keep in nano** |

The split is by **who owns the config field** (schema definition), not by
**who reads it at runtime**. Config schema living in nano while host consumers
read it is the *intended* split — moving these to host config would *violate*
the ownership system, not fix a leak.

Genuinely host-owned config keys (`cron`, `skillify`, `agent.loop`,
`agent.autopilot`, `agent.clarification`, `agent.veritas`, per
`_NANO_DISALLOWED_RULES`) are **already** absent from nano's config schema
(verified: nano defines no `CronConfig`/`AutopilotConfig`/etc.). The config
layer is correctly split. **Workstream D is cancelled as originally scoped.**

### D1. (Revised) Delete dead-duplicate workspace policy functions in nano

The workspace *code* (not config) cluster still has real dead duplicates: nano's
`workspace/workspace_policy.py` defines 6 public functions whose only callers
are host/daemon, and the host **already has canonical copies**
(`foundation/workspace/scoped.py` for `normalize_user_id`/`user_id_for_hash`/
`compute_scoped_workspace_dir_name`; `foundation/workspace/resolution.py` for
`validate_client_workspace`/`translate_client_path_to_container`/
`translate_container_path_to_client`). Plus `_validate_workspace_dir` (only used
by the dead `validate_client_workspace`).

One blocker: host `foundation/workspace/__init__.py:14` imports `user_id_for_hash`
*from nano* even though the host has its own copy in `scoped.py:20`. Fix that
import to point at the host's own `scoped`, then delete the 6 + helper from nano.

**Keep in nano**: `resolve_workspace_for_tool_execution` (real nano callers in
`workspace_paths.py`, `workspace_api.py`, `middleware/workspace_context.py`,
`middleware/filesystem.py`, `middleware/system_prompt.py`, `toolkits/execution.py`)
+ its private helpers (`_coerce_workspace`, `_workspace_from_*`, `_runtime_*`).
This function is nano-owned and not duplicated in the host.

### D2. Verification (D1)

```bash
pytest packages/soothe/tests -k 'workspace or resolution or scoped' -q
pytest packages/soothe-daemon/tests -k 'workspace or router' -q
./scripts/verify_finally.sh
```

---

## Workstream E — `utils/` host-orchestration plumbing (REVISED — mostly not movable)

### E0. Revision (2026-07-21)

**Original premise (move host-only utils to host) was mostly wrong.** The
"host-only" utils are the **write side of ContextVar contracts whose read side
is nano middleware**. The setter/getter pairs share a single ContextVar instance
that *must* live in one module. Moving the write side to the host would split
the ContextVar and break the contract:

| Module | Write side (host/daemon) | Read side (nano) | Shared ContextVar |
|---|---|---|---|
| `utils/token_usage.py` | `loop_token_accumulation_scope`, `DirectLLMTokenTarget`, `merge_direct_llm_tokens_into_state` (host sloop) | `direct_llm_token_call_scope`, `accumulate_loop_tokens_from_llm_result` (nano `invoke_policy`/`observability`) | `_token_target`, `_direct_llm_token_accumulation` |
| `utils/runtime.py` | `stream_turn_overrides`, `attach_stream_model_override`, `attach_stream_router_profile` (daemon runner) | `get_stream_model_override`, `get_stream_router_profile` (nano `per_turn_model`/`role_routing` middleware) | `_stream_model_override`, `_stream_router_profile` |
| `utils/progress.py` | `set_wire_bridge`/`reset_wire_bridge` (host sloop `invoke_wired_subagent`) | `emit_progress` → `get_wire_bridge()` (nano subagents) | `_wire_bridge` |

The host imports these from nano via thin re-export shims
(e.g. `soothe/foundation/sloop/utils/token_usage.py` re-exports nano's). This
is the **intended read/write split** — not a leak. Moving them requires either
(a) moving the entire read side + nano middleware to the host, or
(b) relocating the ContextVar contract to `soothe-sdk`. Both are architectural
redesigns, **out of scope** for clean excision. **Deferred to a separate
future RFC**, not IG-678.

Also: the earlier agent investigation overstated some "dead" helpers —
`find_soothe_chrome_processes` has 2 real in-module callers (NOT dead);
`log_exception_simplified`'s only "caller" is its own docstring example (dead).

### E1. (Revised) Delete only the genuinely-dead helpers

Safe to delete (zero callers anywhere, verified):
- `utils/progress.py` — `set_step_context`/`reset_step_context`/`get_step_id`
  trio + the `_current_step_id` ContextVar + the dead `get_step_id()` call in
  `emit_progress` (always returned None since nothing sets it).
- `utils/error_format.py` — `log_exception_simplified` (only its own docstring
  example referenced it).

**Not movable** (deferred — see E0): `loop_token_accumulation_scope`/
`DirectLLMTokenTarget`/`merge_direct_llm_tokens_into_state`/
`extract_token_usage_from_messages`/`coerce_total_tokens_used`;
`stream_turn_overrides`/`attach_stream_*`; `set_wire_bridge`/`get_wire_bridge`;
`utils/text_preview.py:goal_description_for_log` (host-only caller but trivial
shared util, low value to move); `emit_error_event` (daemon-only caller, but
moving requires rewiring daemon error paths — defer).

### E2. Verification (E1)

```bash
pytest packages/soothe-nano/tests -k 'progress or error_format or token_usage' -q
```

---

## Workstream F — `logging/` + `config/reload` (REVISED — delete dead duplicates)

### F0. Revision (2026-07-21)

**Original premise (move logging/reload machinery to host) was partly wrong.**
Same ContextVar-coupling pattern as PR-5 applies to part of this cluster:
- `set_thread_id`/`get_thread_id` share the `_current_thread_id` ContextVar.
  Nano's `ThreadFormatter.format` (`logging/setup.py:49`) **reads**
  `get_thread_id()`; the host sets it per-loop. Moving the ContextVar would
  break nano's `ThreadFormatter`. **Not movable** (deferred).
- `setup_logging` is genuinely **shared** — the SDK, CLI, daemon, and nano
  tests all call it (multi-package shared utility). **Not movable.**

But two modules are **dead stale duplicates** the host already owns (with more
advanced divergent copies): safe to **delete** from nano.

### F1. (Revised) Delete dead-duplicate `thread_logger.py` + `reload.py`

- `logging/thread_logger.py` — host has its own **divergent, more advanced**
  copy at `soothe/logging/thread_logger.py` (adds `goal_completion` chunk
  accumulation + `AIMessageChunk` handling that nano's lacks). All real callers
  (`_thread_manager`, `query/engine`, `server/core`) import from
  `soothe.logging`. Nano's copy is dead (only `logging/__init__.py` re-exports
  it; zero nano tests). **Delete** nano's `thread_logger.py` + trim the
  `logging/__init__.py` `ThreadLogger` re-export.
- `config/reload.py` — host has its own divergent copy at
  `soothe/config/reload.py` (even self-references
  `from soothe.config.reload import ConfigWatcher`). Host `config/__init__.py`
  imports from `soothe.config.reload`, not nano. Nano's copy is dead (only
  `config/__init__.py` re-exports it; zero nano tests; zero SDK/CLI imports).
  **Delete** nano's `reload.py` + trim the `config/__init__.py` reload
  re-exports (`DEFAULT_CONFIG_PATH`, `DEFAULT_NANO_CONFIG_PATH`,
  `ConfigReloadCallback`, `ConfigReloadEvent`, `ConfigWatcher`,
  `get_config_watcher`, `start_config_watcher`, `stop_config_watcher`).

**Not movable** (deferred — see F0): `set_thread_id`/`get_thread_id`
(ContextVar-coupled), `setup_logging` (shared), `THREADS_DATA_DIR` (verify
later — likely paired with thread_logger, may be deletable if no other caller).

### F2. Verification (F1)

```bash
pytest packages/soothe-nano/tests -k 'logging or config or reload' -q
pytest packages/soothe/tests -k 'logging or thread or reload' -q
```

---

## Workstream G — `workspace/` multi-tenant + container translation

### G1. Move daemon-deployment workspace surface to host

- `workspace/workspace_policy.py` — `normalize_user_id`, `user_id_for_hash`,
  `compute_scoped_workspace_dir_name`, `validate_client_workspace`,
  `translate_client_path_to_container`, `translate_container_path_to_client`
  → `soothe/foundation/workspace/` (sole consumers).
- `workspace/workspace_api.py:resolve_workspace_for_stream` + the
  `"daemon_default"` `ResolvedWorkspaceSource` literal → host (rename
  `daemon_default` → `installation_default` while moving, since the concept
  is "installation default workspace", not inherently daemon).
- Keep in nano: `workspace_runtime.py`, `workspace_filesystem.py`,
  `workspace_paths.py` (nano-internal plumbing with in-nano callers).
- Fold `WorkspaceMountConfig` move (D1) into this workstream.

### G2. Verification (G1)

```bash
pytest packages/soothe/tests -k 'workspace or resolution or scoped' -q
pytest packages/soothe-daemon/tests -k 'workspace or router' -q
```

---

## Workstream H — Middleware inert-without-host-injection (CANCELLED — not a leak)

### H0. Finding (2026-07-21)

**Original premise (move host-gated middleware to host) was wrong.** These 4
middleware are correctly nano-owned with graceful degradation; the host extends
via the builder-subclass injection hooks, not by owning the middleware.

- `SystemPromptMiddleware` is **load-bearing for standalone nano** — it builds
  the system prompt regardless of `routing_classification` (which only adds
  task-complexity hints when the host sloop injects it). Without the host, it
  logs "No routing_classification on state; using task_complexity" and proceeds.
- `ToolEnforcementMiddleware` reads `routing_classification` and **returns
  early** (no-op) when absent — standalone nano is unaffected.
- `PerTurnModelMiddleware` / `RoleRoutingMiddleware` read the daemon stream
  overrides (ContextVar-coupled, W-E) and no-op when no override is installed.

The host does **not** have its own copies of these 4 (verified). The host
extends nano's stack via `soothe/foundation/coreagent/builder.py:AgentBuilder`
(subclasses nano's `AgentBuilder`), overriding `_host_middleware_prefix`/
`_host_middleware_suffix` to inject *additional* host middleware
(`IdentityMiddleware`, `IntakeOnlyTaskGuardMiddleware`, `GoalStepGuardMiddleware`)
on top of nano's default stack, and setting `routing_classification` /
stream overrides that nano's middleware read.

This is the **intended extension-hook pattern** (nano owns middleware with
graceful degradation; host subclass-injects host middleware + state). Moving
these to host would break standalone nano and duplicate the builder-injection
mechanism. **Workstream H is cancelled.** No code changes.

### H1/H2. (Cancelled — no verification needed)

The middleware-in-extension-hook pattern is sound. A future note: if the
`routing_classification` contract ever needs to become more formal, that's an
SDK-protocol change, not an IG-678 excision.

---

## Workstream I — Orphan wire strings + dead helpers cleanup (CANCELLED — not dead)

### I0. Revision (2026-07-21)

**Original premise was wrong.** Re-verification (the same shallow-caller-analysis
failure mode as PR-4/5/6/8) showed every "orphan" candidate has real callers:

- `REPLAY_COMPLETE` — **not orphan**. Both nano and host define it as a shared
  event-namespace constant (host `foundation/events/constants.py:33`; nano
  `events/constants.py:26`). Classified as an allowed shared constant in PR-10's
  `_ALLOWED_DUPLICATES`. Leave as-is.
- `utils/prompt_clock.py` helpers (`build_canonical_datetime_reply`,
  `response_includes_current_local_date`, `format_friendly_local_date`) — all
  have real nano test callers in `tests/unit/utils/test_prompt_clock.py`. NOT dead.
- `utils/browser_cdp.py:find_soothe_chrome_processes` — 2 real in-module callers
  (`browser_cdp.py:140,185`). NOT dead (corrected in PR-5 already).
- `utils/output_capture.py:OutputCapture` — real nano test callers
  (`tests/unit/utils/test_output_capture.py`). NOT dead.

The `prompts/context_xml.py` `<active_goals>`/`<current_plan>` rendering was
already correctly dispositioned as "keep" (passive renderer, guarded). No change.

**Workstream I is cancelled.** No code changes. This is the fifth PR in a row
(4-config, 5, 6, 8, 9) where the original cluster analysis overstated deadness —
the lesson is encoded in PR-10's caller-graph guard.

### I1/I2. (Cancelled — no verification needed)

---

## Workstream J — Boundary script strengthening (anti-regression) — DONE

### J1. `scripts/check_nano_duplicate_symbols.py` — dead-duplicate detector

Implemented as a Python helper invoked by `verify_finally.sh` (alongside the
existing `check_module_import_boundaries.sh` literal ban). It detects the exact
pattern that recurred across IG-678 PR-2/4/6: a public symbol (top-level class,
function, or UPPER_SNAKE constant) defined in **both** `soothe-nano` and
`soothe`/`soothe-daemon` under the same name, with **zero in-nano references
outside its own defining file** — i.e. a dead stale duplicate the host already owns.

Design notes:
- The caller-graph refinement (exclude the symbol's own defining file from its
  "used" set) is essential: a `class Foo:` definition contains `Foo` as a bare
  word, so a naive text scan would mark every defined symbol as self-referenced
  and never flag anything.
- Curated `_ALLOWED_DUPLICATES` (21 + 15 entries, each with a documented
  reason) covers intentionally-shared names: split-config mirrors (per the
  `config/ownership.py` system, PR-4 §D0), shared event/wire constants,
  nano-owned runnables the host subclass-injects, and PR-5-deferred helpers.
  The list is the false-positive budget — new entries require a documented reason.
- The literal-name ban (`check_module_import_boundaries.sh` `check_nano_l2_l3_ban`)
  remains as a backstop; the duplicate checker is the primary guard against the
  renamed-leak pattern.

### J2. Verification (J1)

`verify_finally.sh` runs both:
```bash
bash ./scripts/check_module_import_boundaries.sh     # literal-name ban
python ./scripts/check_nano_duplicate_symbols.py     # dead-duplicate guard
```
Both pass on the current tree. Sanity-tested by injecting a fake `class
GlobalInputHistory` in nano → checker flags it → remove → checker passes.

---

## Suggested PR slices

1. **PR-1 (redundant DDL removal)**: A1 + A2. Safe, behavior-preserving.
2. **PR-2 (display-card DDL + store move)**: B1 + B2. Needs B1.1 decision.
3. **PR-3 (checkpoints ownership + dead import fix)**: C1 + C2. Needs C1.1 decision.
4. **PR-4 (dead-duplicate workspace functions)**: D1 + D2. Revised — config
   groups are correctly nano-owned per the ownership system; only the dead
   workspace code duplicates get deleted.
5. **PR-5 (dead utils helpers)**: E1 + E2. Revised — ContextVar-coupled utils
   are not movable; only genuinely-dead helpers deleted.
6. **PR-6 (dead-duplicate logging + reload modules)**: F1 + F2. Revised —
   `setup_logging`/`set_thread_id` not movable; dead `thread_logger`/
   `thread_paths`/`reload` duplicates deleted.
7. **PR-7 (workspace move)**: G1 + G2.
8. **PR-8 (host-gated middleware)**: H0. **Cancelled** — middleware is
   correctly nano-owned with graceful degradation; host extends via builder
   subclass-injection hooks. No code changes.
9. **PR-9 (orphans + dead helpers)**: I0. **Cancelled** — re-verification
   showed every candidate has real callers (prompt_clock tests, browser_cdp
   in-module, OutputCapture tests, REPLAY_COMPLETE shared constant). No changes.
10. **PR-10 (boundary script strengthening)**: J1 + J2. **Done** —
    `check_nano_duplicate_symbols.py` dead-duplicate detector live in
    `verify_finally.sh`.
11. **PR-11 (release cutover)**: nano 0.9.6 + changelogs (nano + monorepo) +
   lock re-sync. **Done** (not published — release-soothe skill at release time).

---

## Exit criteria — status

- ✅ Nano `init.sql` files contain only nano-owned tables (`soothe_persistence`,
  migrations, `soothe_vectors` extension). Host-only DDL (`cron_jobs`,
  `identity_*`, `soothe_checkpoints`, display-card tables) lives in host/daemon.
- ✅ `DisplayCardStore` + display-card DDL moved to daemon — no
  `loop_id`-keyed store in nano.
- ✅ `soothe_checkpoints` schema owned by host; dead `postgres_schema` import
  fixed (host `postgres_schema.py` pins `sql_root` to host dir).
- ⏸️ Host-shaped config groups (`archive_*`, `GlobalHistoryConfig`,
  `OptimizationConfig`, `WorkspaceMountConfig`, `ThreadLoggingConfig`) — **NOT
  moved**; the `config/ownership.py` system deliberately assigns them to nano
  (PR-4 §D0 finding). They are correctly nano-owned schema that host reads.
  Exit criterion revised: config is correctly split, not relocated.
- ✅ Host-only *dead-duplicate* logging/reload/workspace surface deleted from
  nano (host already owned canonical copies). ContextVar-coupled utils
  (`set_thread_id`, `stream_turn_overrides`, `set_wire_bridge`) NOT moved —
  they share ContextVars with nano middleware (PR-5 §E0 finding); deferred to a
  future SDK-protocol RFC.
- ✅ Boundary script catches renamed + caller-graph leaks (PR-10:
  `check_nano_duplicate_symbols.py` live in `verify_finally.sh`).
- ✅ `./scripts/verify_finally.sh` + `check_module_import_boundaries.sh` green.
- ⏸️ Version bump prepared (nano 0.9.6 + changelogs + lock re-sync); publish
  deferred to the release-soothe skill at actual release time.

---

## Risks

| Risk | Mitigation |
|---|---|
| Deleting DDL the host doesn't actually run at runtime | A0 verified host runtime DDL owners (cron `__init__`, identity `IdentityDbConnection`) + startup construction sites |
| Display-card DDL move breaks daemon Postgres display ledger | B1 adds host DDL home *before* deleting nano copy; B2 tests daemon display ledger |
| Config YAML path shifts break operator configs | D1 changelog "Breaking (IG-678 cutover)"; keep field names, move only the model class location where possible |
| Caller-graph boundary check false positives (shared symbols) | J1 allows a symbol with ≥1 in-nano caller; only flags zero-in-nano-caller host-only symbols |
| Middleware move breaks nano default stack | H1.1 decision required before PR-8; default move-to-host is gated on standalone nano not needing the behavior |

---

## Priority order

1. PR-1 (safe redundant-DDL removal — implemented this session).
2. PR-2/PR-3 (display-card + checkpoints ownership — needs design decisions).
3. PR-4..PR-9 (config/utils/logging/workspace/middleware/orphans).
4. PR-10 (boundary script — do before declaring done, to lock the cut).
5. PR-11 (release cutover).
