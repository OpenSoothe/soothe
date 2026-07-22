# IG-521: Same-File Edit Concurrency and Optimization

**IG**: 521
**Title**: Same-File Edit Concurrency and Optimization — 3-Layer Race-Free Edit Pipeline
**Status**: In Progress
**Created**: 2026-06-28
**Dependencies**: RFC-902 (same-file edit optimization), RFC-101 (tool interface), RFC-102 (security filesystem policy), IG-517 (edit coalescing async I/O)

---

## Summary

Implement the three-layer concurrency architecture specified in RFC-902 to eliminate the **lost-update race** that occurs when an LLM emits multiple `edit_file` tool calls targeting the **same file** within a single turn. Without mutual exclusion, parallel read-modify-write cycles silently clobber each other — the last writer wins and earlier edits vanish with no error signal.

The design layers three strategies so that a single layer's failure cannot produce data loss:

- **Layer 1** — Atomic write via temp file + `os.replace` with version-stamp verification (crash safety + external-writer detection)
- **Layer 2** — Per-file `asyncio.Lock` mutex keyed by `os.path.realpath` (in-process race elimination)
- **Layer 3** — Coalescing middleware with a turn-level staging buffer (I/O minimization + intra-turn race elimination)

Each layer is independently correct: Layer 1 provides crash safety even if Layers 2–3 are bypassed; Layer 2 serializes within the process even without coalescing; Layer 3 minimizes I/O and eliminates the intra-turn race.

---

## The Lost-Update Race (Root Cause)

`LocalFilesystem.aedit()` (and siblings: `aedit_lines`, `aedit_batched`, `apply_diff`) followed a read-modify-write cycle with **no mutual exclusion**:

```
t1  Call A: read(path) -> content_v0
t2  Call B: read(path) -> content_v0   (stale!)
t3  Call A: modify -> content_v1; write(path, content_v1)
t4  Call B: modify(content_v0) -> content_v2  (based on stale read)
t5  Call B: write(path, content_v2)           (clobbers A's edit)
```

Call A's edit is **silently lost**. No error is raised. The agent has no signal that its edit failed.

---

## 3-Layer Design (from RFC-902)

```
+---------------------------------------------------------------+
|  Layer 3: Coalescing Middleware + Staging Buffer              |
|  - Detection window (50 ms) groups same-file edits            |
|  - Dispatches as single aedit_batched() call                  |
|  - Eliminates intra-turn race + reduces I/O                   |
|  - In-memory snapshot per file per turn (staging buffer)      |
|  - Result-maps back to original call IDs                      |
+------------------------------+--------------------------------+
                               |
+------------------------------v--------------------------------+
|  Layer 2: Per-File Async Mutex                                |
|  - asyncio.Lock per resolved file path (os.path.realpath)     |
|  - Acquired before aedit_batched(), released after write      |
|  - Eliminates inter-batch and inter-agent race                |
|  - Different files -> different locks -> full parallelism     |
+------------------------------+--------------------------------+
                               |
+------------------------------v--------------------------------+
|  Layer 1: Atomic Write + Version Stamp                        |
|  - Write to temp file, os.replace (atomic on POSIX)           |
|  - Capture old_hash at read; verify before rename             |
|  - Detects external process modification (outside Layer 2)    |
|  - Crash safety: rename is atomic -- no partial writes        |
+---------------------------------------------------------------+
```

### Layer 1 — Atomic Write + Version Stamp

The foundation. Writes go to a temp file (`.soothe.tmp` suffix, in the **same directory** as the target so `os.replace` is atomic — cross-filesystem rename is not atomic). A content hash captured at read time is verified before the rename; a mismatch raises `EditConflictError` (detected concurrent modification). This closes the TOCTOU gap of optimistic concurrency by making the final write a conditional atomic rename. Even if Layers 2 and 3 are bypassed (external process, or a code path that skips the middleware), the write is atomic and the version stamp detects concurrent modification.

### Layer 2 — Per-File Async Mutex

An `asyncio.Lock` per resolved file path ensures that even if two coalescing windows or two agents edit the same file, their `aedit_batched()` calls are serialized. Different files use different locks, so unrelated edits remain fully parallel. Lock keys are canonicalized via `os.path.realpath` so that `./config.py` and `./symlink_to_config.py` map to the same lock. The registry also provides a sync (`threading.RLock`) pool for the sync edit methods. A meta-lock guards lazy lock creation so concurrent tasks requesting a lock for the same path do not create duplicate entries.

### Layer 3 — Coalescing Middleware + Staging Buffer

The coalescing middleware groups same-file edits within a 50 ms detection window into a single `aedit_batched()` call. This eliminates redundant reads (1 read per file per window, not 1 per edit), eliminates the intra-turn race (edits in the same window apply to the same in-memory snapshot), and reduces middleware traversal (1 batched call vs N individual calls). The staging buffer extends coalescing across the full turn: an in-memory snapshot per file is held, edits apply to the buffer, and it is flushed once at turn end (or invalidated/flushed before any non-edit tool call such as `run_command`). Results are mapped back to the original tool-call IDs.

---

## System Invariants

After this implementation, the following must always hold:

1. **INV-1 (No silent loss)** — If two edits to the same file are issued concurrently, either (a) both are applied, or (b) the conflicting edit returns an error to the caller. Silent loss is impossible.
2. **INV-2 (Single read per file per batch)** — Edits to the same file within a coalescing window result in exactly one file read and one file write.
3. **INV-3 (No event-loop block)** — File I/O and lock acquisition are async; no synchronous blocking call on the event loop's hot path.
4. **INV-4 (Crash safety)** — A crash during edit leaves either the original file or the fully written new file — never a partially written file (via atomic rename).

---

## Files Changed

### Core implementation

| File | Action | Purpose |
|------|--------|---------|
| `packages/soothe/src/soothe/core/filesystem/local.py` | **Modify** (+614 / −291) | Layer 1: `_write_atomic()` (temp + fsync + `os.replace`), `_compute_version_stamp()`, `_check_file_size()`. Layer 2: `self._edit_locks = FileEditLockRegistry()` and lock acquisition wrapping `aedit`/`aedit_lines`/`aedit_batched` critical sections. Atomic-write + version-stamp verification on the write path. |
| `packages/soothe/src/soothe/core/filesystem/_lock_registry.py` | **Create** (new) | Layer 2: `FileEditLockRegistry` — per-resolved-path async (`asyncio.Lock`) and sync (`threading.RLock`) lock pools, meta-lock-guarded lazy creation, `os.path.realpath` key canonicalization. |
| `packages/soothe/src/soothe/middleware/edit_coalescing.py` | **Modify** (+461 / −13) | Layer 3: staging buffer (`StagingEntry`, in-memory snapshot per file per turn), `StringReplacement` dataclass, `EditCoalescingConfig` (detection window, staging buffer limits, eviction policy), detection-window grouping, batch dispatch to `aedit_batched()`, result-to-call-ID mapping, buffer invalidation/flush before non-edit tools. |

### Wiring / configuration

| File | Action | Purpose |
|------|--------|---------|
| `packages/soothe/src/soothe/middleware/_builder.py` | **Modify** | `EditCoalescingMiddleware` already mounted in the stack (position ~1d); log messages cleaned of internal identifiers. |
| `packages/soothe/src/soothe/config/models.py` | **Modify** | Config field descriptions cleaned of internal identifiers (no behavioral change). |
| `packages/soothe/src/soothe/context/models.py` | **Modify** | Minor cleanup. |
| `packages/soothe/src/soothe/sloop/state/execution_checkpoint.py` | **Modify** | Minor cleanup. |
| `packages/soothe/src/soothe/sloop/state/schemas.py` | **Modify** | Minor cleanup. |
| `packages/soothe/src/soothe/runner/__init__.py` | **Modify** | Minor cleanup. |
| `packages/soothe-daemon/src/soothe_daemon/config/models.py` | **Modify** | Daemon config description cleanup (mirrors soothe config). |
| `packages/soothe-daemon/src/soothe_daemon/health/checks/observability_check.py` | **Modify** | Minor cleanup. |
| `packages/soothe-daemon/src/soothe_daemon/runner/_worker_runner.py` | **Modify** | Minor cleanup. |
| `packages/soothe-daemon/src/soothe_daemon/runner/factory.py` | **Modify** | Minor cleanup. |
| `packages/soothe-daemon/src/soothe_daemon/server/core.py` | **Modify** | Minor cleanup. |

### Specification & design

| File | Action | Purpose |
|------|--------|---------|
| `docs/specs/RFC-902-same-file-edit-optimization.md` | **Create** (+1020) | The RFC: motivation, 9-strategy catalog, 3-layer component design, interfaces, error handling, migration plan, edge cases, testing strategy. |
| `docs/archive/drafts/2026-06-28-same-file-edit-optimization-design.md` | **Create** (+909) | Working design draft that fed into RFC-902. |
| `docs/impl/IG-521-same-file-edit-optimization.md` | **Create** | This document. |

### Tests

| File | Action | Test Count | Verifies |
|------|--------|------------|----------|
| `packages/soothe/tests/core/filesystem/test_edit_locks.py` | **Create** (new) | **12 new** | Layer 2: lock creation, per-path isolation, realpath canonicalization, async + sync pools, meta-lock-guarded lazy creation, reentrant sync locks. |
| `packages/soothe/tests/unit/middleware/test_edit_coalescing_staging.py` | **Create** (new) | **34 new** | Layer 3: staging buffer lifecycle, in-memory snapshot apply, dirty tracking, flush, invalidation on non-edit tool, eviction policies (`reject_newest` / `evict_oldest`), max-entries limit, `StringReplacement` merge ordering, conflict detection. |
| `packages/soothe/tests/unit/middleware/test_edit_coalescing.py` | **Modify** (+2) | (regression) | Adds `edit_file` assertions to `_is_edit_tool` and `EDIT_TOOL_NAMES` membership tests (edit_file now routes through coalescing). |
| `packages/soothe/tests/core/filesystem/test_unified.py` | (existing) | (part of 176 base) | Filesystem read/write/edit primitives (regression coverage for Layer 1+2 on the `aedit`/`aedit_batched` path). |
| `packages/soothe/tests/core/filesystem/test_grep_search.py`, `test_deepagents_compat.py`, `test_langchain_adapter.py`, `test_workspace.py` | (existing) | (part of 176 base) | Broader filesystem regression base. |

### Test-count summary

| Bucket | Count | Source |
|--------|-------|--------|
| Pre-existing regression base (filesystem + coalescing suites) | **176** | test functions across `tests/core/filesystem/test_*.py` + `tests/unit/middleware/test_edit_coalescing.py` minus the new lock/staging files |
| New: per-file lock registry | **12** | `tests/core/filesystem/test_edit_locks.py` |
| New: staging buffer coalescing | **34** | `tests/unit/middleware/test_edit_coalescing_staging.py` |
| **Total** | **222** | 176 + 12 + 34 |

---

## Implementation Sequence

1. Create RFC-902 specification and design draft.
2. Layer 2: create `_lock_registry.py` (`FileEditLockRegistry` with async + sync pools, realpath keying, meta-lock-guarded lazy creation).
3. Layer 1: add `_write_atomic()`, `_compute_version_stamp()`, `_check_file_size()` to `local.py`; wire atomic write + version stamp into `aedit`/`aedit_lines`/`aedit_batched`.
4. Layer 2 integration: instantiate `self._edit_locks = FileEditLockRegistry()` in `LocalFilesystem`; wrap edit critical sections with `async with self._edit_locks.acquire(path)`.
5. Layer 3: extend `edit_coalescing.py` with staging buffer (`StagingEntry`, `StringReplacement`, `EditCoalescingConfig`), detection-window grouping, batch dispatch, result mapping, invalidation/flush.
6. Add tests: `test_edit_locks.py` (12), `test_edit_coalescing_staging.py` (34), extend `test_edit_coalescing.py` with `edit_file` assertions.
7. Clean internal identifiers from config descriptions and log messages.
8. Create this IG document.
9. Stage and commit.

---

## Migration Notes

### Compatibility

- **Fully backward-compatible.** Existing callers of `aedit()` / `aedit_batched()` get race protection transparently — no API changes. The atomic write and lock acquisition are internal to the methods.
- **Layer 1+2 are always on.** No feature flag; they are internal correctness guarantees on the write path.
- **Layer 3 (coalescing) is opt-in via config** (`edit_coalescing.enabled`, default `true` for new deployments). Existing deployments can set it to `false` during migration; edits then go directly to `aedit()` / `aedit_batched()` which still have Layer 1+2 protection.
- The staging buffer is governed by `edit_coalescing.enable_staging_buffer` (default `true`) and limits via `staging_buffer_max_entries` / `staging_buffer_eviction_policy`.

### Phased Rollout (per RFC-902)

| Phase | Layer | Risk | Rollout | Feature Flag |
|-------|-------|------|---------|--------------|
| 1 | Layer 1 + Layer 2 | Low (internal, transparent) | Immediate | None (always on) |
| 2 | Layer 3 (coalescing) | Medium (new middleware) | Opt-in, then default | `edit_coalescing.enabled` |
| 3 | Cross-process (autopilot) | Low (autopilot only) | Autopilot deployments | `autopilot.file_lock.enabled` |
| 4 | Turn-level staging buffer | Medium (turn-level state) | Opt-in | `edit_coalescing.enable_staging_buffer` |

### Rollback

- **Layer 1+2**: Revert the lock acquisition and `_write_atomic()` calls. The original `aiofiles.open(path, "w")` path remains as fallback.
- **Layer 3**: Set `edit_coalescing.enabled: false` in config. Middleware is skipped; edits go directly to `aedit()` / `aedit_batched()` (which still have Layer 1+2 protection).

### Relationship to Existing `FileLockMiddleware`

The existing `FileLockMiddleware` is a **cross-loop** lock for autopilot mode (different StrangeLoops editing the same file). It is **complementary** to this design:

- **This design's Layer 2** (`asyncio.Lock` per file) guards the read-modify-write cycle **within a single process**.
- **`FileLockMiddleware`** guards **across StrangeLoops** (different goals/loops that may run in separate worker processes).

They operate at different granularities and do not conflict.

### Edge Cases Handled

- **Concurrent edits to different files** — fully parallel (different locks).
- **Very large files** — `max_file_size_bytes` enforced on read; staging buffer reads once, writes once.
- **Network filesystems (NFS/SMB)** — version stamps (hash) are the primary defense; `backend_type: "network"` enables stricter checking and disables `fsync`.
- **Crash recovery** — `os.replace` is atomic; orphaned `.soothe.tmp` files are cleaned up on the next edit.
- **External process modifies file mid-turn** — staging buffer is invalidated/flushed before any non-edit tool call; version stamp on flush catches residual staleness (`EditConflictError`).
- **Symbolic links / path aliasing** — lock registry uses `os.path.realpath()` as the key.
- **Empty files / new file creation** — `awrite_atomic` handles creation via temp + `os.replace`.

---

## Status

Implementation complete; all changes staged and committed (RFC-902 spec, Layer 1 atomic writes, Layer 2 per-file lock registry, Layer 3 coalescing staging buffer, tests, and this IG). Not pushed; no PR created.
