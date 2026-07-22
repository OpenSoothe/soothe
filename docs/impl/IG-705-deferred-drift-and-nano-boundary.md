# IG-705: Deferred Drift + Nano Boundary Cleanup

**Guide**: IG-705
**Created**: 2026-07-22
**Related**: IG-702, IG-703, IG-704 (foundation lift — do not reuse that number),
`AGENTS.md` §3b/§3c/§7b, `scripts/check_nano_duplicate_symbols.py`
**Status**: COMPLETE — `verify_finally.sh` fully green (2026-07-22).

Injectable process-wide registry factory: **closed by PR-B** (host
`PostgresPoolRegistry` subclasses nano; singleton state lives in the nano
module via inherited classmethods). No further factory work needed. Optional
follow-on (not this IG): consolidate `SharedPostgreSQLPool` vs
`SharedCheckpointerPool`.

## Context

Post–IG-703 / IG-704, remaining duplication was drifted near-copies in the
pool/resolver layer, plus nano tests/docs that still imported host `soothe`
(partially rewritten during IG-704 from `soothe.foundation.*` → `soothe.*`
instead of `soothe_nano.*`).

Host layout is flattened (`soothe.foundation` is gone). Paths use
`soothe.persistence.*`, `soothe.sloop.*`, `soothe.coreagent.*`.

## Progress

### Nano boundary (DONE)

- `filesystem/README.md` examples → `soothe_nano.*`
- Moved 3 Executor / `_is_rate_limit_error` tests to
  `packages/soothe/tests/unit/sloop/test_executor_rate_limit_classification.py`
- Prompt guide tests → `soothe_nano.prompts` / `system_templates`
- Veritas structured-output test → inline schema + normalize (no host import)
- Dropped spurious `importorskip("soothe")` on nano resolver tests
- Stale `soothe.*` comments in nano src swept

### PR-A — SharedCheckpointerPool (DONE)

- Nano: `_REGISTRY_CLS` injection
- Host: thin subclass bound to host `PostgresPoolRegistry`
- Tests reset singleton state on `soothe_nano.resolve.shared_checkpointer_pool`

### PR-B — PostgresPoolRegistry (DONE)

- Nano: `_databases_to_open` / `_initialize_pool_schema` hooks
- Host: subclass opens `checkpoints` + host loop schema bootstrap
- Singleton state lives in nano module (host subclass inherits)

### PR-C — `_resolver_infra` (DONE)

- Nano: optional `metadata_pool_cls` / `checkpointer_pool_cls` kwargs
- Host: thin wrappers injecting host pool shims; SQLite path uses nano SDK path

### PR-D — StepExecutionRecord (DONE)

- Host `StepResult` → `StepExecutionRecord` (~49 files)
- SDK `StepResult` kept; StrangeLoop adapter uses `SdkStepResult` alias

### PR-E — Config parity (DONE)

- `tests/unit/config/test_split_config_mirror_parity.py` for allowlisted mirrors

## Out of scope (unchanged)

- Full `SootheConfig` shared-base inheritance
- `ProtocolError` public rename
- Injectable process-wide registry factory

## Verification

`./scripts/verify_finally.sh` **fully green** (2026-07-22).
