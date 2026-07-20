# Implementation Guide: migrate nano-owned tests from soothe to soothe-nano

## Goal

Move tests that validate `soothe_nano` modules out of `packages/soothe/tests` and into
`packages/soothe-nano/tests` so package ownership and CI boundaries are explicit.

## Scope

- Migrate high-confidence tests that:
  - import `soothe_nano.*`
  - do not import `soothe.*` host runtime modules
- Keep mixed host-wiring tests in `packages/soothe/tests` for a follow-up split pass.

## Non-goals

- No behavior changes in tested modules.
- No assertion rewrites beyond path/package organization.
- No migration of host-only runner, autopilot, or daemon integration tests.

## Implementation

1. Move pure nano-owned tests from `packages/soothe/tests/unit/...` to
   `packages/soothe-nano/tests/unit/...`.
2. Preserve file contents; avoid semantic edits unless imports/fixtures break.
3. Run targeted pytest collection/execution for moved files.
4. Keep mixed ownership tests in place and document as follow-up candidates.

## Verification

- `pytest packages/soothe-nano/tests/unit/config/test_expand_path.py`
- `pytest packages/soothe-nano/tests/unit/core/loop/engine/test_ephemeral_execute_stream.py`
- `pytest packages/soothe-nano/tests/unit/core/security`
- `pytest packages/soothe-nano/tests/unit/core/workspace`
- `pytest packages/soothe-nano/tests/unit/middleware`
- `pytest packages/soothe-nano/tests/unit/plugin`
