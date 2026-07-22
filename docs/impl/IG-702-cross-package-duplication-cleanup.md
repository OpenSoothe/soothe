# IG-702: Cross-Package Duplication Cleanup

**Guide**: IG-702
**Created**: 2026-07-21
**Related**: IG-678 (Nano Host-Coupling Excision), IG-701 (Event Naming &
Package-Boundary Fixes), `AGENTS.md` §3b/§3c/§7b/§10,
`scripts/verify_finally.sh`, `scripts/check_module_import_boundaries.sh`,
`scripts/check_nano_duplicate_symbols.py`
**Status**: COMPLETE for PR-1/PR-3/PR-4 + PR-2 (2 of 3 persistence files).
`postgres_pool_registry.py`, `StepResult`, `ProtocolError`, and the
`config/{settings,models}.py` near-duplicates deferred to a follow-up RFC
(see "Out of scope"). `verify_finally.sh` fully green.

## Context

A cross-package duplication audit (`soothe` host, `soothe-daemon`,
`soothe-nano`, `soothe-sdk` canonical) found that IG-678 + IG-701 already
removed the worst structural leaks (host/daemon concepts in nano, duplicate
event registry, 6 duplicate protocol models). The remaining duplication is a
smaller set of **drifted copies** (near-identical bodies that diverged only in
import paths / docstrings / a few fields) and **orphaned duplicates** (local
copies whose canonical version is already imported elsewhere).

This IG excises the drifted/orphaned copies whose fix is mechanical and
boundary-correct. Items that require a design decision (renaming a class with
48 call sites, merging a genuinely-extended config hierarchy) are **deferred**
to a follow-up RFC and listed under "Out of scope".

## Scope

### IN SCOPE (mechanical, boundary-correct)

- **P1 — Identity data-model split.** Host
  `foundation/identity/models.py` re-declares 8 pydantic classes that are
  canonical in `soothe_sdk.protocols.identity`. The host `identity_service.py`
  already imports all 8 from the SDK, but `tokens.py` imports `TokenClaims`
  from the local copy and *instantiates* it — two distinct class objects in one
  process, `isinstance` across them fails. The local `IdentityStatus` is also
  *stale* (missing 3 fields the SDK has). Fix: delete the local `models.py`,
  point `tokens.py` + `__init__.py` at the SDK.
- **P2 — Persistence Postgres trio drift.** Host
  `foundation/persistence/{shared_metadata_pool,postgres_provisioning}.py` are
  byte-identical to nano's except for `soothe_nano.*` → `soothe.*`
  import paths and "process"/"daemon" docstring wording. Fix: convert the two
  pure-drift files to delegate to nano (`shared_metadata_pool` via a
  `_REGISTRY_CLS`-overriding subclass so the host singleton binding is intact;
  `postgres_provisioning` as a re-export shim). `postgres_pool_registry.py` is
  deferred — see "Out of scope" (singleton coupling blocks a clean subclass).
- **P3 — Constants + paths duplication.**
  - `DEFAULT_EXECUTE_TIMEOUT = 60` hardcoded in both `soothe_sdk/paths.py`
    (canonical) and `soothe_nano/config/constants.py`. Fix: nano imports it
    from the SDK.
  - Host `config/constants.py` duplicates nano's shared execution constants
    (`MAX_EXECUTE_TIMEOUT`, `DEFAULT_TASK_TIMEOUT_SECONDS`,
    `DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS`, `DEFAULT_TOOL_OUTPUT_CHARS`,
    `clamp_execute_timeout`). Fix: host imports the shared set from nano,
    keeps only host-only `DEFAULT_MAX_ITERATIONS` /
    `DEFAULT_MAX_TOOL_CALLS_PER_STEP` / `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS`.
  - 4 host prompt XML fragments (`assistant_identity`, `default_system_body`,
    `medium_system`, `simple_system`) are byte-identical to nano's and never
    read by host code (host imports the constants from nano). Fix: delete the
    4 orphaned host XML copies.
  - `soothe/src/soothe/persistence/sql/soothe_vectors/init.sql` is
    a byte-identical copy of nano's. Host loads it from its own tree; fix:
    remove the host copy and load from nano.
  - `SOOTHE_HOME` literal re-declared in `soothe_nano/config/env.py` and
    inlined in `soothe_daemon/cli.py` + `identity_cli.py`. Fix: nano imports
    `SOOTHE_HOME` from `soothe_sdk.paths`; daemon CLI files import from SDK.
- **P4 — Wire contract drift.**
  - Daemon `protocol/schemas.py:ConnectionInitParams` re-declares the SDK's
    handshake params with all-optional fields. Fix: subclass the SDK model,
    loosen `client_version` to optional (server tolerates clients omitting it).
  - Daemon `protocol/validation.py` hardcodes `VALID_TYPES` /
    `_ENVELOPE_TYPES` as frozensets of 14 string literals that mirror the SDK
    `MessageType` StrEnum. Fix: derive both sets from `MessageType` so adding
    a type updates daemon validation automatically.

### OUT OF SCOPE (need an RFC — deferred)

- **`postgres_pool_registry.py` drift.** The host genuinely extends nano's
  registry with a `"checkpoints"` pool + schema bootstrap. A subclass refactor
  is blocked by singleton coupling: the `_registry` / `_async_lock` state is
  module-global in each package, so a host subclass would need to share nano's
  module-level lock to avoid two independent pool sets. Needs an RFC to
  restructure the singleton as an injectable factory. Deferred.
- **`StepResult` dual definition** (host execution record vs SDK planner
  contract). Host's is a 12-field superset with a richer `to_evidence_string`;
  the SDK's is the 6-field planner-facing contract used in
  `PlanContext.completed_steps`. The host already adapts host→SDK at
  `strange_loop.py:983`. Renaming the host class (`StepExecutionRecord`)
  touches 48 references; merging the two shapes changes the planner contract.
  Deferred — needs an RFC to decide direction.
- **`ProtocolError` name collision** (SDK client-side `code: int` vs daemon
  server-side `code: ErrorCode` + `severity`). Genuinely different roles on
  opposite sides of the wire. Intentional, not drift. Deferred.
- **`config/settings.py` + `config/models.py` large near-duplicates.** Host
  `SootheConfig` is an independent re-declaration (not a subclass of nano's)
  that genuinely extends with StrangeLoop/Autopilot/ComplexityThresholds/
  CronConfig/SkillifyConfig. Shared-base-class refactor is involved and changes
  the config surface. Deferred — needs an RFC.
- **`observability/langfuse/_names.py` parallel impls.** The SDK copy
  (`nanoagent-graph` / `intake-classify`) and host copy
  (`strange-loop-graph` / `intent-classify`) are genuinely different trace-name
  vocabularies for different graphs; the SDK copy has real test callers. Not a
  stale duplicate — left as-is.

## Progress

### PR-1 — Identity data-model split (DONE, 2026-07-21)

- Host `foundation/identity/models.py` is now a re-export shim over
  `soothe_sdk.protocols.identity` (all 8 classes: `User`, `AKSKPair`,
  `TokenClaims`, `ExternalIdentityMapping`, `AuthResult`, `TokenRefreshResult`,
  `TokenInfo`, `IdentityStatus`).
- `tokens.py` repointed to import `TokenClaims` directly from the SDK (matching
  `identity_service.py`). The local-copy `TokenClaims` that broke `isinstance`
  is gone; `TokenClaims` is now a single class object across the process.
- The stale local `IdentityStatus` (missing `active_aksk_count` /
  `active_tokens_count`) is gone; host now uses the SDK's 6-field version.
- 2 tests importing `from soothe.identity.models import TokenClaims`
  still work via the shim. 60 identity tests green.

### PR-2 — Persistence trio drift (PARTIAL — see note)

- **`shared_metadata_pool.py`** — DONE. Nano's `SharedMetadataPool` now
  references the registry via a `_REGISTRY_CLS` class attribute; the host file
  is a thin subclass that overrides `_REGISTRY_CLS` to the host
  `PostgresPoolRegistry`. Single shared logic, host singleton binding intact.
- **`postgres_provisioning.py`** — DONE. Host file is now a re-export shim over
  nano's implementation (the host `config.env._resolve_env` and
  `foundation.persistence.db_init` it referenced are themselves shims over
  nano, so delegating shares the process-wide provision cache). Repointed 3
  test patch targets from the host path to `soothe_nano.persistence.postgres_provisioning`
  (`_initialize_postgres_schemas` ×2, `ensure_postgres_databases` ×1) since
  the private/internal symbols now live only in nano.
- **`postgres_pool_registry.py`** — DEFERRED. The host genuinely extends
  nano's registry with a `"checkpoints"` pool + `initialize_agentloop_postgres_schema`
  bootstrap. A subclass refactor is blocked by singleton coupling: the
  `_registry` / `_async_lock` state is module-global in each package, so a
  host subclass would need to share nano's module-level lock to avoid two
  independent pool sets. Non-mechanical — moved to "Out of scope" (needs an
  RFC to restructure the singleton as an injectable factory).

### PR-3 — Constants + paths duplication (DONE, 2026-07-21)

- Nano `config/constants.py` imports `DEFAULT_EXECUTE_TIMEOUT` from
  `soothe_sdk.paths` (was a hardcoded `60`).
- Host `config/constants.py` imports the 6 shared execution constants +
  `clamp_execute_timeout` from `soothe_nano.config.constants`; keeps host-only
  `DEFAULT_MAX_ITERATIONS` / `DEFAULT_MAX_TOOL_CALLS_PER_STEP` /
  `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS` local.
- Deleted 4 orphaned host prompt XML fragments (`assistant_identity`,
  `default_system_body`, `medium_system`, `simple_system`) — host imports the
  constants from nano; the local copies were never read.
- Deleted 2 orphaned host SQL copies (`sql/soothe_metadata/init.sql`,
  `sql/soothe_vectors/init.sql`) — host `db_init` resolves to nano's SQL tree;
  the host copies were never loaded. (The display/cron/identity DDL that lived
  only in the host `soothe_metadata` copy is applied at runtime by the daemon
  stores' own `_SCHEMA`, so removing the file changes nothing.)
- `SOOTHE_HOME` unified: nano `config/env.py` imports it from
  `soothe_sdk.paths`; daemon `cli.py` + `identity_cli.py` import from the SDK
  instead of inlining `Path(os.environ.get("SOOTHE_HOME", "~/.soothe"))`.
  Repointed 4 daemon `test_cli.py` monkeypatch targets from `_SOOTHE_HOME` to
  `SOOTHE_HOME`.

### PR-4 — Wire contract drift (DONE, 2026-07-21)

- Daemon `protocol/validation.py`: `VALID_TYPES` and `_ENVELOPE_TYPES` now
  derived from `soothe_sdk.wire.codec.MessageType` (`VALID_TYPES = {m.value for
  m in MessageType}`; `_ENVELOPE_TYPES = VALID_TYPES - {ping, pong}`). Adding
  a message class to the enum updates daemon validation automatically.
- Daemon `protocol/schemas.py:ConnectionInitParams` now subclasses the SDK
  `soothe_sdk.wire.codec.ConnectionInitParams` and overrides all 4 fields to
  optional (server tolerates clients omitting them). Field names/types stay in
  sync with the SDK via inheritance; only optionality differs.
- 432 daemon protocol/wire tests green.

### Verification (DONE, 2026-07-21)

`./scripts/verify_finally.sh` **fully green** — all 6 packages (soothe-sdk,
soothe-nano, soothe-client-python, soothe-cli, soothe, soothe-daemon): tests +
lint + format + vulture + boundary checks (cli↛daemon, sdk independence,
nano↛host, nano dead-duplicate symbols, nano/sdk docstring refs) + AsyncAPI
spec drift. Exit 0.

## Status

**COMPLETE** for PR-1, PR-3, PR-4 + the 2 of 3 persistence files in PR-2.
`postgres_pool_registry.py`, `StepResult`, `ProtocolError`, and the
`config/{settings,models}.py` near-duplicates are deferred to a follow-up RFC
(see "Out of scope"). `verify_finally.sh` fully green (2026-07-21).
