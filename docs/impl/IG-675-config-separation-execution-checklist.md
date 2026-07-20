# IG-675: Config Separation Execution Checklist (nano vs soothe)

**Guide**: IG-675  
**Created**: 2026-07-20  
**Related**: IG-674, IG-668, AGENTS.md §1/§9  
**Status**: Draft execution plan

---

## Goal

Execute IG-674 with a low-risk, reviewable sequence that removes host concept leakage
from `soothe_nano.config` and establishes `soothe.config` as the composition/overlay
layer.

---

## Workstream A — establish ownership modules in host

### A1. Create host ownership map module

- **Add** `packages/soothe/src/soothe/config/ownership.py`
- **Responsibilities**:
  - canonical key ownership rules (`nano` vs `host`)
  - key-path matching helpers
  - validation error builders with relocation hints
- **Output API** (example names):
  - `validate_nano_file_ownership(data: dict[str, Any]) -> None`
  - `validate_host_file_ownership(data: dict[str, Any]) -> None`
  - `OwnershipViolationError`

### A2. Create host composition module

- **Add** `packages/soothe/src/soothe/config/composition.py`
- **Responsibilities**:
  - deterministic merge of validated `nano.yml` + `soothe.yml`
  - conflict detection on cross-ownership writes
  - optional trace payload for startup logs
- **Output API**:
  - `compose_host_agent_config(nano_data, soothe_data) -> dict[str, Any]`

### A3. Create host compat module

- **Add** `packages/soothe/src/soothe/config/compat.py`
- **Responsibilities**:
  - temporary monolithic `config.yml` adaptation
  - legacy key relocation (`strange_loop` -> `agent.loop`, etc.) in host only
  - deprecation warning emission

---

## Workstream B — remove leakage from nano config package

### B1. Tighten nano settings validators

- **Edit** `packages/soothe-nano/src/soothe_nano/config/settings.py`
- **Remove/move out**:
  - host-key stripping (`cron`, `skillify`, `strange_loop`)
  - any host overlay folding behavior
- **Keep**:
  - pure nano schema validation
  - core defaults and provider/router/bootstrap logic

### B2. Remove host fallback access path

- **Edit** `packages/soothe-nano/src/soothe_nano/config/middleware_access.py`
- **Target**:
  - stop reading `agent.loop` as fallback to `agent.middleware`
- **Replacement**:
  - host adapter in `soothe/config/composition.py` or `soothe/config/compat.py`
  - nano middleware only accepts `agent.middleware`

### B3. Normalize terminology in nano models docs

- **Edit** `packages/soothe-nano/src/soothe_nano/config/models.py`
- **Adjust comments/docstrings only**:
  - replace host-loop wording where semantics are CoreAgent middleware
  - avoid implying `agent.loop` is a nano runtime concept

---

## Workstream C — host settings becomes composition entrypoint

### C1. Refactor host settings load path

- **Edit** `packages/soothe/src/soothe/config/settings.py`
- **Flow**:
  1. load `nano.yml` as base (nano schema)
  2. load `soothe.yml` as host overlay (host schema)
  3. run ownership validators
  4. compose merged dict
  5. apply env precedence
  6. instantiate host `SootheConfig`

### C2. Isolate host-only model sections

- **Edit** `packages/soothe/src/soothe/config/models.py`
- **Ensure host-only ownership** for:
  - `agent.loop`, `agent.autopilot`, `agent.clarification`, `agent.veritas`
  - top-level `cron`, `skillify`
- **Avoid duplicated shared primitives** where nano already provides canonical forms.

### C3. Stabilize host exports

- **Edit** `packages/soothe/src/soothe/config/__init__.py`
- **Actions**:
  - export composition APIs intentionally
  - avoid re-exporting nano internals that are not part of host contract

---

## Workstream D — shared utilities dedupe

### D1. Reload utility de-duplication

- **Current state**: `soothe/config/reload.py` and `soothe_nano/config/reload.py` are near-identical.
- **Target**:
  - keep canonical implementation in `soothe_nano.config.reload`
  - make host wrapper import/re-export with minimal glue

### D2. Models catalog de-duplication

- **Current state**: `soothe/config/models_catalog.py` and `soothe_nano/config/models_catalog.py` are near-identical.
- **Target**:
  - canonical implementation in nano/shared utility
  - host wrapper only binds host `SootheConfig` type contract if needed

### D3. Env utility ownership

- `env.py` is currently identical in both packages.
- **Decision gate**:
  - either keep mirrored copies intentionally, or
  - make host import from nano and stop duplicate maintenance.

---

## File-by-file checklist

### Add

- `packages/soothe/src/soothe/config/ownership.py`
- `packages/soothe/src/soothe/config/composition.py`
- `packages/soothe/src/soothe/config/compat.py`

### Edit (nano)

- `packages/soothe-nano/src/soothe_nano/config/settings.py`
- `packages/soothe-nano/src/soothe_nano/config/middleware_access.py`
- `packages/soothe-nano/src/soothe_nano/config/models.py`
- `packages/soothe-nano/src/soothe_nano/config/__init__.py` (if exports change)

### Edit (host)

- `packages/soothe/src/soothe/config/settings.py`
- `packages/soothe/src/soothe/config/models.py`
- `packages/soothe/src/soothe/config/__init__.py`
- `packages/soothe/src/soothe/config/reload.py`
- `packages/soothe/src/soothe/config/models_catalog.py`

### Config templates / docs

- `config/config.template.yml`
- `config/develop/config.yml`
- docs/wiki and examples that reference monolithic `config.yml`

---

## Verification gates per workstream

### Gate A (ownership/composition modules compile)

- `uv run ruff check packages/soothe/src/soothe/config`
- `uv run pytest packages/soothe/tests/unit/config -q`

### Gate B (nano no leakage)

- `uv run ruff check packages/soothe-nano/src/soothe_nano/config`
- targeted tests for nano config validation and middleware config resolution

### Gate C (host composition path)

- host config loading tests with:
  - split files valid
  - wrong-file keys rejected
  - legacy monolithic path warning behavior

### Gate D (dedupe and regression)

- run existing reload/models-catalog tests in both packages
- `./scripts/verify_finally.sh`

---

## Rollout plan

1. **PR-1**: Add host ownership/composition/compat modules + tests (no behavior flip).
2. **PR-2**: Switch host settings to composition path behind feature flag.
3. **PR-3**: Remove nano host-key stripping and host fallback; keep temporary host adapters.
4. **PR-4**: Dedupe shared utility modules (`reload.py`, `models_catalog.py`, optionally `env.py`).
5. **PR-5**: Enable split-by-default templates/docs.
6. **PR-6**: Remove compatibility adapters and enforce strict ownership.

---

## Exit criteria

- Nano config package contains no host ownership knowledge.
- Host config package is the only place where cross-file composition/compat occurs.
- Split-file config is default and documented.
- Full verification passes with zero lint/test regressions.

---

## Task matrix

| ID | Workstream | Scope | Primary owner | Dependencies | Risk | Test impact | Done criteria |
|----|------------|-------|---------------|--------------|------|-------------|---------------|
| T1 | Host ownership rules | Add `soothe/config/ownership.py` with allow/deny key-path validators | Config core | none | Medium | New unit tests in `packages/soothe/tests/unit/config` | Misplaced keys produce actionable relocation errors |
| T2 | Host composition engine | Add `soothe/config/composition.py` merge logic | Config core | T1 | High | New composition tests + conflict tests | `nano.yml + soothe.yml` merge is deterministic and conflict-safe |
| T3 | Host compat layer | Add `soothe/config/compat.py` for legacy monolith adaptation | Config core | T1,T2 | Medium | Legacy config tests | Monolithic config still loads with deprecation warnings |
| T4 | Host settings entrypoint | Refactor `soothe/config/settings.py` to call ownership/composition/compat | Runner/host config | T2,T3 | High | Existing config-loading tests + new split-file tests | Host config load path uses split composition end-to-end |
| T5 | Nano validator cleanup | Remove host-key stripping from `soothe_nano/config/settings.py` | Nano config | T4 (or feature-flag) | High | Nano config validation tests | Nano loader rejects/ignores only nano schema concerns |
| T6 | Middleware fallback cleanup | Remove `agent.loop` fallback in `soothe_nano/config/middleware_access.py` | Nano config | T4,T5 | High | Middleware tests in nano/soothe | Nano middleware reads only `agent.middleware` |
| T7 | Host adapter for old loop fields | Keep old `agent.loop` compatibility in host-only adapters | Runner/host config | T6 | Medium | Host compat tests | Legacy host configs continue working during migration window |
| T8 | Models ownership split | Ensure host-only models remain in `soothe/config/models.py`, shared stay nano | Config core | T4 | Medium | Model validation tests both packages | No duplicated ownership ambiguity for major sections |
| T9 | Public API cleanup | Normalize exports in both `config/__init__.py` files | Config core | T8 | Low | Import-surface tests | Imports are stable and non-leaky |
| T10 | Reload dedupe | Host `reload.py` becomes thin wrapper over nano/shared implementation | Infra config | T4 | Medium | Reload watcher tests in soothe + nano | No behavior drift; duplicate logic removed |
| T11 | Models catalog dedupe | Host `models_catalog.py` wraps/shared implementation | Infra config | T4 | Low | `models_list` payload tests | Payload unchanged; less duplicate code |
| T12 | Env dedupe decision | Keep mirrored `env.py` or centralize to nano | Config core | T9 | Low | Minimal | Decision documented + implemented consistently |
| T13 | Template split | Update `config/config.template.yml` and `config/develop/config.yml` for split layout | Docs/config DX | T4 | Medium | Config bootstrap smoke tests | Templates emit `nano.yml` + `soothe.yml` correctly |
| T14 | Daemon linkage | Ensure `daemon.yml` points to split files and logs load order | Daemon | T13 | Medium | Daemon startup/integration tests | Startup logs show composition source order |
| T15 | Docs migration | Update docs/wiki/examples to split config references | Docs | T13 | Low | Doc lint/checks | No monolithic-first guidance remains |
| T16 | Strict mode flip | Remove compat adapters after migration window | Config core + daemon | T3,T7,T15 | High | Full regression suite | Wrong-file keys hard-fail; no hidden folding paths |

---

## Suggested PR slices

1. **PR-1 (Foundation):** T1, T2, tests.
2. **PR-2 (Host integration):** T3, T4, tests.
3. **PR-3 (Nano purity):** T5, T6, T7.
4. **PR-4 (Dedupes):** T10, T11, optional T12.
5. **PR-5 (Config UX):** T13, T14, T15.
6. **PR-6 (Enforcement):** T16 + cleanup.

---

## Priority order

1. First: T1–T4 (enables safe migration path).
2. Then purity: T5–T7 (remove host-loop leakage from nano).
3. Then debt paydown: T10–T12.
4. Last: T16 strict enforcement.
