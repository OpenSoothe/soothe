# IG-597: Edit Coalescing Workspace Backend Optimization

## Goal

Reduce overhead and improve correctness in edit coalescing by using cached workspace backends, removing redundant file reads, and eliminating fragile backend-construction compatibility paths.

## Scope

- Refactor `soothe.middleware.edit_coalescing.EditCoalescingMiddleware` to resolve filesystem backends through `get_workspace_backend(...)` with workspace context.
- Remove repeated ad-hoc `NormalizedPathBackend(...)` construction in coalescing hot paths.
- Remove duplicate pre-lock + in-lock reads in string-replacement batches.
- Keep direct file I/O fallback only when no workspace context is available.
- Add unit tests for backend-context integration behavior.

## Non-goals

- No changes to detection-window semantics or edit conflict policy.
- No changes to external tool contracts (`edit_file`, `edit_lines`, `insert_lines`, `delete_lines`).
- No changes to `NormalizedPathBackend` public API.

## Problem Statement

The coalescing middleware contained three optimization/correctness issues:

1. **Repeated backend construction** in hot paths (`_read_file_for_batch`, `_atomic_write`, `_dispatch_batched_edits`) instead of cached backend reuse.
2. **Constructor mismatch risk** from ad-hoc backend instantiation callsites using stale argument names.
3. **Redundant read pass** in string-replacement dispatch (read once before lock, then read again under lock), causing avoidable I/O and work.

## Proposed Design

### 1) Central backend resolver in middleware

Add private `_get_context_backend()`:

- Reads workspace + virtual mode from unified workspace context.
- Uses `soothe.workspace.normalized_backend.get_workspace_backend(...)`.
- Returns `None` when no workspace context exists.

### 2) Single in-lock read for string replacements

In `_dispatch_string_replacements(...)`:

- Acquire file lock first.
- Read authoritative content once.
- Perform overlap detection and replacement using the same in-lock content.
- Write once if any replacement succeeded.

### 3) Deterministic fallback policy

- If workspace backend exists: use backend and propagate backend read/write errors.
- If no workspace backend exists: use existing direct I/O fallback path.

## Cleanse Plan

- Remove legacy ad-hoc backend creation branches in edit-coalescing internals.
- Remove duplicate-read code path that became superseded by in-lock authoritative read.
- Keep only fallback branches that are still functionally required (no workspace context).

## Testing Plan

- Add unit test validating `_read_file_for_batch(...)` extracts content from backend `file_data`.
- Add unit test validating `_get_context_backend()` resolves through cached `get_workspace_backend(...)` with context virtual mode.
- Run full repository verification script.

## Risks and Mitigations

- **Risk:** Behavior change in error handling when backend exists.
  - **Mitigation:** Keep direct fallback for no-context only; preserve user-facing error ToolMessages for batch failures.
- **Risk:** Context/virtual mode drift.
  - **Mitigation:** Source both from unified workspace context and test virtual-mode propagation.

## Acceptance Criteria

- Coalescing middleware no longer constructs workspace backends ad hoc in hot paths.
- String-replacement batch path performs a single authoritative read under lock.
- New tests covering backend-context integration pass.
- `./scripts/verify_finally.sh` completes successfully after fixes.
