# IG-595 Foundation Core Module Removal and Layout Polish

## Goal

Remove the legacy `soothe.foundation.core` module and promote shared substrate modules to first-class foundation packages.

## Scope

- Move `foundation/core/filesystem/*` to `foundation/filesystem/*`
- Move `foundation/core/security/*` to `foundation/security/*`
- Remove `foundation/core` package after import cutover
- Update all source/tests/examples imports from `soothe.foundation.filesystem` and `soothe.foundation.security`

## Non-goals

- No behavior changes in filesystem or security logic
- No changes to `foundation/coreagent` runtime abstractions

## Target Layout

- `packages/soothe/src/soothe/foundation/filesystem/*`
- `packages/soothe/src/soothe/foundation/security/*`
- `packages/soothe/src/soothe/foundation/coreagent/*`

## Acceptance Criteria

- No imports remain from `soothe.foundation.core.*`
- `packages/soothe/src/soothe/foundation/core` is removed
- Targeted regressions pass
- `./scripts/verify_finally.sh` passes

