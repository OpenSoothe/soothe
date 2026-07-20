# Implementation Guide: move nano examples into soothe-nano package

## Goal

Move `examples/nano_agent/*` into `packages/soothe-nano/examples/nano_agent/*` so nano examples live with their owning package and do not depend on host `soothe` example helpers.

## Scope

- Relocate all nano example scripts and shared helpers.
- Replace host-level helper imports (`examples._config_helper`) with nano-local helper code.
- Ensure examples import `soothe_nano` from local package `src/` so they can run from the monorepo without host package coupling.
- Update lint config paths for numbered example filenames.
- Update handover note to reflect new location.

## Non-goals

- Changing runtime behavior of `create_nano_agent`.
- Rewriting non-nano examples under root `examples/`.

## Implementation

1. Create `packages/soothe-nano/examples/nano_agent/_shared/config.py` that uses:
   - `soothe_nano.config.SOOTHE_HOME`
   - `soothe_nano.config.SootheConfig`
   - repo `config/develop/config.yml` fallback
2. Copy/move example scripts and streaming helper into the new package path.
3. Remove old files under root `examples/nano_agent/`.
4. Update Ruff `per-file-ignores` to the new path in:
   - root `pyproject.toml`
   - `packages/soothe-nano/pyproject.toml`

## Verification

- `./scripts/verify_finally.sh`
- Smoke-run one script:
  - `python packages/soothe-nano/examples/nano_agent/01_pure_nano_example.py`
