# Implementation Guide: foundation re-export and shim cleanse

## Goal

Cleanse legacy compatibility shims in `packages/soothe/src/soothe/foundation` now that host code imports canonical `soothe.prompts` and `soothe_nano.workspace` APIs directly.

## Scope

- Remove `soothe.foundation.sloop.prompts` shim modules that only wildcard re-export from `soothe.prompts`.
- Replace broad lazy fallback in `soothe.foundation.workspace.__getattr__` with explicit re-exports from `soothe_nano.workspace` modules.
- Preserve currently used workspace APIs by keeping explicit exports for filesystem/runtime helpers and stream/tool resolution types.

## Non-goals

- No behavior changes in StrangeLoop planning/execution.
- No renaming of canonical prompt modules under `soothe.prompts`.
- No persistence or protocol changes.

## Implementation

1. Delete shim-only prompt modules under:
   - `packages/soothe/src/soothe/foundation/sloop/prompts/`
2. Update `packages/soothe/src/soothe/foundation/workspace/__init__.py`:
   - import explicit symbols from `soothe_nano.workspace.workspace_api`
   - import explicit symbols from `soothe_nano.workspace.workspace_filesystem`
   - import explicit symbols from `soothe_nano.workspace.workspace_runtime`
   - keep host loop/daemon resolution exports from foundation modules
   - remove dynamic `__getattr__` fallback
3. Run targeted tests for workspace and import surfaces, then run full verify.

## Verification

- `pytest packages/soothe/tests/unit/core/test_workspace_resolution.py`
- `pytest packages/soothe/tests/unit/core/workspace/test_core_resolution.py`
- `./scripts/verify_finally.sh`
