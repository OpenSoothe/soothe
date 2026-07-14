# IG-647: Filesystem Artifact Prefix Portability Migration

## Goal

Make filesystem eviction/history artifact paths portable across backends and runtime environments by migrating a configurable prefix strategy into `soothe-deepagents`, while keeping current behavior backward compatible.

## Scope

- Add explicit configuration for filesystem artifact prefixes in `soothe_deepagents.middleware.filesystem.FilesystemMiddleware`.
- Preserve current backend-derived defaults when no override is provided.
- Add a safe fallback for environments where derived roots are unwritable or otherwise invalid.
- Wire `soothe` integration points to pass workspace-local overrides when required by workspace policy.
- Add tests for default behavior, explicit override behavior, and fallback behavior.

## Non-goals

- No change to core eviction algorithm or token-limit thresholds.
- No change to tool APIs (`read_file`, `edit_file`, `delete`, etc.).
- No backend protocol redesign in this change.

## Problem Statement

Current behavior in `soothe-deepagents` computes:

- `large_tool_results` prefix from `artifacts_root`
- `conversation_history` prefix from `artifacts_root`

This is architecturally clean, but can fail in restricted environments when the effective root maps to unwritable locations. `soothe` currently mitigates this by overriding prefixes to workspace-local paths (`.soothe/...`), which is robust but not centrally available as a first-class deepagents option.

## Proposed Design

### API additions in `FilesystemMiddleware`

Add optional constructor args:

- `large_tool_results_prefix: str | None = None`
- `conversation_history_prefix: str | None = None`
- `artifacts_prefix_mode: Literal["backend_default", "workspace_fallback"] = "backend_default"`

Behavior:

1. If explicit prefix arg is provided, use it.
2. Else compute backend default from `artifacts_root` (current behavior).
3. If `artifacts_prefix_mode == "workspace_fallback"` and computed prefix is not safe/writable, fallback to workspace-local defaults:
   - `.soothe/large_tool_results`
   - `.soothe/conversation_history`

Notes:

- Safety/writability check should be deterministic and backend-aware (prefer backend capability/validation where available, avoid shell probes).
- Prefixes remain logical backend paths, not forced OS-native paths.

### `soothe` integration policy

For `SootheFilesystemMiddleware`:

- Continue setting workspace-local prefixes by default to preserve current operational safety.
- Optionally move to constructor pass-through once deepagents API lands, instead of direct post-init field mutation.

### Backward compatibility

- Existing callers that do not pass new args retain existing behavior.
- Existing persisted artifact data remains readable under prior prefixes.
- No user-visible runtime text should include IG identifiers.

## Implementation Plan

1. **Deepagents constructor extension**
   - Add new optional fields and validation.
   - Normalize paths once at init.
2. **Prefix resolution helper**
   - Centralize default/override/fallback resolution in a private helper.
3. **Fallback guard**
   - Add backend-safe path viability checks used only when `workspace_fallback` mode is active.
4. **Soothe adoption**
   - Update `SootheFilesystemMiddleware` to use new constructor-level overrides.
   - Keep exact current default prefixes in soothe.
5. **Docs updates**
   - Update middleware docs and examples to show override and fallback mode usage.

## Testing Plan

### Unit tests (`soothe-deepagents`)

- Default mode with no overrides uses current backend-derived prefixes.
- Explicit `large_tool_results_prefix` override is honored.
- Explicit `conversation_history_prefix` override is honored.
- `workspace_fallback` mode falls back when derived prefix is invalid/unwritable.
- `workspace_fallback` mode does not fallback when derived prefix is valid.

### Integration tests (`soothe`)

- `SootheFilesystemMiddleware` still writes eviction/history artifacts under `.soothe/...`.
- Existing tool-call flow remains unchanged under normal backend and workspace-backend contexts.

### Regression checks

- Run `./scripts/verify_finally.sh`.
- Confirm no changes to tool behavior snapshots unrelated to prefix paths.

## Risks and Mitigations

- **Risk:** False-positive fallback when backend is writable but check is too strict.
  - **Mitigation:** Prefer backend-native validation and keep fallback mode opt-in initially.
- **Risk:** Path normalization mismatch across virtual and non-virtual backends.
  - **Mitigation:** Reuse existing path validation utilities and add cross-backend fixture coverage.
- **Risk:** Drift between soothe and deepagents defaults.
  - **Mitigation:** Centralize soothe defaults in one middleware constructor path and test explicitly.

## Acceptance Criteria

- Deepagents supports explicit artifact prefix overrides without breaking existing callers.
- Optional fallback mode prevents invalid/unwritable-root failures in restricted environments.
- Soothe continues to operate with workspace-local artifact prefixes by default.
- Verification suite passes after implementation.

