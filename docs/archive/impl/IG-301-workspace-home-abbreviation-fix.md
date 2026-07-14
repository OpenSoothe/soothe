# IG-301 Workspace Home Abbreviation Fix

## Context

Agent output occasionally displayed paths like `~Workspace/...` instead of the valid
home-relative form `~/Workspace/...`. This malformed display value was then reused in
follow-up instructions and produced workspace resolution failures.

## Root Cause

`soothe_sdk.utils.formatting.convert_and_abbreviate_path()` builds home-relative
display paths using:

- `~` + `str(path.relative_to(home))`

For paths such as `/Users/xiamingchen/Workspace/mirasurf/soothe`, this produces
`~Workspace/mirasurf/soothe` (missing slash after `~`).

## Implementation Plan

1. Update home-relative formatting logic to emit:
   - `~` for home root
   - `~/...` for descendants under home
2. Add unit tests in `packages/soothe-sdk/tests/unit/utils/` to prevent regression.
3. Run targeted tests for the new formatting behavior.

## Expected Outcome

- Displayed home-relative paths are always syntactically valid (`~/...`).
- Workspace values copied from agent output resolve correctly.
