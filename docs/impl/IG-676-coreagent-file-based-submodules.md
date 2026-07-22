## Goal

Polish `soothe.coreagent` by promoting canonical runtime modules to
file-based submodules at the package root while keeping backward-compatible
legacy import paths.

## Scope

- Add canonical root modules:
  - `soothe.coreagent.builder`
  - `soothe.coreagent.core_agent`
  - `soothe.coreagent.lazy`
  - `soothe.coreagent.factory`
- Convert legacy `soothe.coreagent.coding.*` modules into
  compatibility shims.
- Repoint internal runtime and tests to canonical root module paths.

## Why

The prior structure kept the active runtime under `coreagent.coding`, which
made ownership and navigation less clear and retained duplicate implementation
paths. Root file-based modules provide a single source of truth and reduce
future drift.

## Non-Goals

- No behavior changes to CoreAgent construction, lazy materialization, planner
  injection, or intake-only subagent binding.
- No removal of external compatibility import paths in this step.

## Validation

- Unit tests that exercise CoreAgent creation and lazy materialization.
- Runner warmup tests covering `LazyCoreAgent` type checks.
- Full verification via `./scripts/verify_finally.sh`.
