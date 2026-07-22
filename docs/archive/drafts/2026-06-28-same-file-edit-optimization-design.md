# Same-File Edit Optimization Design

> Eliminating the lost-update race in parallel `edit_file` calls through a layered concurrency strategy

**RFC**: (draft — to be assigned upon promotion to `docs/specs/`)
**Title**: Same-File Edit Concurrency and Optimization
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-28
**Dependencies**: RFC-101 (tool interface), RFC-102 (security filesystem policy), RFC-222 (autopilot goal engine)

---

## Overview

When an LLM emits multiple `edit_file` tool calls in a single response, the agent runtime dispatches them in parallel. Several of those calls may target the **same file**. Each call independently performs a read-modify-write cycle on disk. Because no lock is held between the read and the write, the second write clobbers the first — a classic **lost-update race**. This design catalogs all candidate concurrency strategies, analyzes their tradeoffs in a decision matrix, and recommends a layered combination that is race-free, low-latency, and minimal in new code.

---

## Motivation

### Symptom

An agent editing the same file via two parallel `edit_file` calls produces incorrect results:

```
Call A: edit_file(path="config.py", old="VERSION = 1", new="VERSION = 2")
Call B: edit_file(path="config.py", old="DEBUG = False", new="DEBUG = True")
```

**Expected**: both changes present.
**Actual**: only one change survives — the last writer wins.

### Root Cause

The `LocalFilesystem.aedit()` method (and every sibling: `aedit_lines`, `aedit_batched`, `apply_diff`) follows this sequence with **no mutual exclusion**:

```python
async def aedit(self, path, old_string, new_string, ...):
    async with aiofiles.open(resolved) as f:   # ← READ
        content = await f.read()
    # ... validate, replace ...
    new_content = content.replace(old_string, new_string, 1)
    async with aiofiles.open(resolved, "w") as f:  # ← WRITE
        await f.write(new_content)
```

Two concurrent invocations interleave:

```
Time  Call A                              Call B
────  ───────                              ───────
t1    read(path) → content_v0
t2                                         read(path) → content_v0   ← stale!
t3    modify(content_v0) → content_v1
t4    write(path, content_v1)
t5                                         modify(content_v0) → content_v2  ← based on stale read
t6                                         write(path, content_v2)          ← clobbers A's edit
```

Call A's edit is **silently lost**. No error is raised. The agent has no signal that its edit failed.

### Impact

| Scenario | Frequency | Consequence |
|----------|-----------|-------------|
| LLM emits 2+ `edit_file` calls to same file in one turn | Common in refactoring tasks | Silent data loss |
| Subagent + parent edit same file concurrently | Occasional in autopilot mode | One agent's work vanishes |
| Multiple StrangeLoops edit shared file | Rare (mitigated by `FileLockMiddleware`) | Cross-loop clobber |

### Current State of the Codebase

| Component | Status | Gap |
|-----------|--------|-----|
| `LocalFilesystem.aedit()` | Async via aiofiles, but read-modify-write is **not atomic** | No lock between read and write |
| `LocalFilesystem.aedit_batched()` | Batch primitive exists; applies N ops in one read-modify-write | No concurrency guard — two batches to same file still race |
| `FileLockMiddleware` | Implemented, tested, **not installed** | Cross-loop lock for autopilot only; not a within-loop concurrency guard |
| `EditCoalescingMiddleware` (prior draft 2026-06-27) | Proposed, not implemented | Groups edits within a 50 ms window into one `aedit_batched()` call — but two windows for the same file still race |
| `apply_diff()` | Shells out to `patch` command | No locking; `patch` itself is not atomic |

---

## Guiding Principles

1. **Correctness first** — A race-free guarantee is non-negotiable. Performance optimizations that sacrifice correctness are rejected.
2. **Minimal new code** — Prefer composing existing primitives (`aedit_batched`, `FileLockRegistry`) over building new subsystems.
3. **Layered defense** — Use multiple strategies at different layers so a single layer's failure does not produce data loss.
4. **Fail loud, not silent** — If a conflict is unavoidable, raise an error the agent can act on. Never silently drop an edit.
5. **No blocking the event loop** — Locks must be async-aware (`asyncio.Lock`, not `threading.Lock` on the hot path).

---

## Terminology

| Term | Definition |
|------|------------|
| **Lost-update race** | Concurrent read-modify-write cycles where the last writer silently overwrites earlier writers' changes |
| **Read-modify-write cycle** | The pattern: read file → transform content in memory → write file back to disk |
| **Critical section** | The window between read and write where the file's on-disk state must not change |
| **Coalescing** | Grouping multiple edit operations targeting the same file into a single batched call |
| **Version stamp** | A hash or mtime captured at read time, checked before write to detect concurrent modification |
| **Optimistic concurrency** | Proceed without locking; detect conflicts at write time via version stamp; retry on mismatch |
| **Pessimistic concurrency** | Acquire an exclusive lock before reading; hold until write completes; block other writers |
| **Batched edit** | A single `aedit_batched()` call applying multiple operations (delete, insert, replace) in one read-modify-write |

---

## System Invariants

After this design is implemented, the following must always hold:

1. **INV-1 (No silent loss)**: If two edits to the same file are issued concurrently, either (a) both are applied, or (b) the conflicting edit returns an error to the caller. Silent loss is impossible.
2. **INV-2 (Single read per file per batch)**: Edits to the same file within a coalescing window result in exactly one file read and one file write.
3. **INV-3 (No event-loop block)**: File I/O and lock acquisition are async; no synchronous blocking call on the event loop's hot path.
4. **INV-4 (Crash safety)**: A crash during edit leaves either the original file or the fully written new file — never a partially written file (via atomic rename).

---

## Problem Statement: Lost-Update Race Mechanism

### The Race Window

Every edit method in `LocalFilesystem` follows the same unsynchronized pattern:

```
┌──────────────────────────────────────────────────────────────────────┐
│                     aedit() / aedit_lines() / aedit_batched()        │
│                                                                      │
│   ┌─────────┐         ┌──────────────┐         ┌─────────┐          │
│   │  READ   │────────▶│  TRANSFORM   │────────▶│  WRITE  │          │
│   │ (aiofiles│         │ (in-memory   │         │(aiofiles│          │
│   │  open r) │         │  replace)    │         │  open w)│          │
│   └─────────┘         └──────────────┘         └─────────┘          │
│         ▲                                               ▲            │
│         │           ╔═══════════════════╗               │            │
│         │           ║  CRITICAL SECTION  ║               │            │
│         │           ║  (no lock held!)   ║               │            │
│         │           ╚═══════════════════╝               │            │
│         │                                               │            │
│         └───────────── GAP ──────────────────────────────┘            │
│           Another coroutine can read/write the file                   │
│           during this gap, causing a lost update.                     │
└──────────────────────────────────────────────────────────────────────┘
```

### Interleaving Diagram

Two parallel `edit_file` calls to the same file, dispatched concurrently by the agent runtime:

```
                    ┌─────────────────── File on Disk ───────────────────┐
                    │              content_v0 (base)                      │
                    └─────────────────────────────────────────────────────┘
                                      │
     ──────────────────────────────── │ ──────────────────────────────────
     Time                             │
     ──────────────────────────────── │ ──────────────────────────────────

     Call A (edit: "foo"→"bar")       │   Call B (edit: "baz"→"qux")
     ─────────────────────────        │   ─────────────────────────
     t1: READ → content_v0            │
                                      │   t2: READ → content_v0   ← STALE
     t3: TRANSFORM → v0+bar = v1      │
     t4: WRITE → disk = v1            │   t5: TRANSFORM → v0+qux = v2
                                      │   t6: WRITE → disk = v2   ← CLOBBERS v1

                    ┌─────────────────────────────────────────────────────┐
                    │  Final disk state: content_v2 (has "qux", LOST "bar")│
                    └─────────────────────────────────────────────────────┘
```

**Result**: Call A's edit (`"foo"→"bar"`) is silently lost. Call A returns success. The agent believes both edits applied.

### Why the Prior Coalescing Draft Does Not Fully Solve This

The `EditCoalescingMiddleware` (draft 2026-06-27) groups edits within a 50 ms detection window into a single `aedit_batched()` call. This eliminates the race **within a single window**. But:

- Two detection windows for the same file can overlap (window 1 dispatches while window 2 is collecting).
- Edits arriving from different agents/subagents bypass the same middleware instance.
- The `aedit_batched()` call itself still has the read-write gap.

Coalescing is a **performance** optimization that reduces the race surface; it does not **eliminate** it.

---

## Strategy Catalog

Nine strategies are enumerated below. Each is analyzed independently before the recommended combination is presented.

---

### Strategy 1: Serialize-Per-File (Async Mutex)

**Mechanism**: Maintain a `dict[str, asyncio.Lock]` keyed by resolved file path. Every edit method acquires the per-file lock before reading and releases it after writing. The critical section (read → transform → write) is fully serialized per file.

```
edit_file(path, ...):
    lock = _get_lock(path)        # asyncio.Lock, created lazily per path
    async with lock:
        content = await aread(path)
        new_content = transform(content)
        await awrite(path, new_content)
```

**Strengths**: Simple, correct, minimal conceptual change. Different files are fully parallel (different locks).

**Weaknesses**: Serializes all edits to the same file even when they target non-overlapping regions. Adds a lock lookup on every edit.

---

### Strategy 2: Single-Write Python Script

**Mechanism**: Instead of calling `edit_file` N times, emit a single `run_command` or `write_file` call that runs a Python script applying all edits in one process. The script reads the file once, applies all transformations, and writes once — all within a single synchronous execution with no interleaving.

```python
# Generated script sent via run_command
import re
p = "config.py"
c = open(p).read()
c = c.replace("VERSION = 1", "VERSION = 2", 1)
c = c.replace("DEBUG = False", "DEBUG = True", 1)
open(p, "w").write(c)
```

**Strengths**: Zero race window (single process, single read-write). No new infrastructure. Works with any tool backend.

**Weaknesses**: Bypasses filesystem abstraction (security policy, audit logging, backup creation). Hard to validate old_string uniqueness. Error messages are opaque. The agent must construct the script correctly — LLMs are unreliable at generating edit scripts. No partial-failure feedback per edit.

---

### Strategy 3: `edit_lines` for Contiguous Ranges

**Mechanism**: When multiple edits target contiguous or nearby line ranges in the same file, combine them into a single `edit_lines` call with a broader range. Instead of editing lines 5-7 and 9-11 separately, edit lines 5-11 in one call with the merged content.

**Strengths**: Uses an existing tool. Reduces call count. No new code.

**Weaknesses**: Only works for line-number-based edits (not string-match `edit_file`). The LLM must know exact line numbers, which drift after each edit. Non-contiguous edits can't be merged. Does not solve the race — two `edit_lines` calls still race unless combined by the caller.

---

### Strategy 4: Unified Diff / Patch

**Mechanism**: Generate a single unified diff covering all desired changes and apply it via `apply_diff()`. The `patch` command applies hunks atomically within a single process invocation.

```
--- a/config.py
+++ b/config.py
@@ -1,2 +1,2 @@
-VERSION = 1
+VERSION = 2
-DEBUG = False
+DEBUG = True
```

**Strengths**: Single process, single read-write (via `patch`). Standard format. `patch` has built-in context validation (rejects if context lines don't match). Can express complex multi-hunk edits.

**Weaknesses**: The LLM must generate a correct unified diff — error-prone for large changes. `apply_diff()` shells out to the `patch` binary (dependency, security surface). The `patch` process itself is not guarded against concurrent invocations on the same file. No per-edit result mapping. Fuzzy matching can apply incorrectly.

---

### Strategy 5: File Locking (flock / fcntl)

**Mechanism**: Use OS-level advisory file locks (`fcntl.flock` with `LOCK_EX`) on a sidecar `.lock` file or the file itself. Acquire before read, release after write.

```python
import fcntl
async def aedit_locked(path, ...):
    lock_path = path + ".soothe.lock"
    with open(lock_path, "w") as lock_fd:
        await asyncio.to_thread(fcntl.flock, lock_fd, fcntl.LOCK_EX)
        try:
            content = await aread(path)
            new_content = transform(content)
            await awrite(path, new_content)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
```

**Strengths**: Works across processes (not just coroutines). Kernel-enforced. No in-process registry needed.

**Weaknesses**: `flock` is synchronous — must be wrapped in `asyncio.to_thread()`, adding overhead. Advisory locks require all writers to cooperate (external processes editing the file are unaffected). Does not work on network filesystems (NFS, SMB) where `flock` semantics are unreliable or no-ops. Lock file cleanup is needed (orphaned lock files on crash). Does not work for virtual/in-memory filesystems.

---

### Strategy 6: Optimistic Concurrency with Version Stamps

**Mechanism**: Capture a version stamp (content hash or mtime) at read time. Before writing, re-check the stamp. If it changed (another writer modified the file), abort and retry the entire read-modify-write cycle. If retries are exhausted, return a conflict error.

```python
async def aedit_optimistic(path, old_str, new_str, max_retries=3):
    for attempt in range(max_retries):
        content = await aread(path)
        stamp = sha256(content)            # version stamp
        if old_str not in content:
            raise Not Found
        new_content = content.replace(old_str, new_str, 1)
        # Re-read to check stamp before writing
        current = await aread(path)
        if sha256(current) != stamp:
            continue                        # someone changed it — retry
        await awrite(path, new_content)
        return success
    raise EditConflictError("concurrent modification, retries exhausted")
```

**Strengths**: No locks — maximum parallelism for non-conflicting edits. No external dependencies. Works across processes (hash-based). Detects conflicts rather than silently losing them.

**Weaknesses**: **TOCTOU gap**: between the stamp re-check and the write, another writer can still sneak in (the check-then-write is not atomic). To close this gap, you need a compare-and-swap primitive, which requires either file locking (Strategy 5) or an atomic rename (write to temp, `os.rename` is atomic, but you still need to ensure no other writer renamed in between). Under high contention, retries waste CPU and increase latency. Requires careful retry-backoff to avoid live-lock.

---

### Strategy 7: In-Memory Staging Buffer

**Mechanism**: Maintain an in-memory representation of file content within the agent's working memory. All edits apply to the in-memory buffer (instant, no I/O, no race). Flush the buffer to disk once at the end of the turn (or when a read of a different file is needed, or when the buffer exceeds a size limit).

```
Turn start:
  buffer = {}  # path → (content, dirty)

edit_file(path, old, new):
  if path not in buffer:
    buffer[path] = aread(path)       # one read, first access
  buffer[path] = buffer[path].replace(old, new)  # in-memory, instant
  mark dirty

Turn end (or flush trigger):
  for path, content in buffer.items():
    if dirty:
      awrite(path, content)          # one write per file
```

**Strengths**: Eliminates all races within a turn (edits are in-memory, serialized by the single-threaded event loop). Minimizes I/O (one read + one write per file per turn). Enables undo (revert buffer). Sub-millisecond edit latency.

**Weaknesses**: Memory pressure for large files or many files. Stale buffer if an external process modifies the file mid-turn (need version stamp on flush). Buffer must be invalidated when other tools (e.g., `run_command`) might modify files. Complex flush/invalidation logic. Breaks the "each tool call is independent" mental model — buffer state persists across calls within a turn.

---

### Strategy 8: Batch-Edit API Primitive

**Mechanism**: Expose a single `edit_batch` tool that accepts a list of edit operations for a given file and applies them in one `aedit_batched()` call. The LLM emits one `edit_batch` call instead of N `edit_file` calls.

```python
@tool
def edit_batch(path: str, operations: list[EditOp]) -> EditResult:
    """Apply multiple edits to a file in one atomic operation."""
    return await fs.aedit_batched(path, operations)
```

**Strengths**: The `aedit_batched()` primitive **already exists** in `LocalFilesystem` — no new filesystem code needed. Single read-modify-write eliminates the race within the batch. Per-operation result mapping (already implemented: `failed_operations` list). Overlap detection already implemented.

**Weaknesses**: Does not solve cross-batch races (two `edit_batch` calls to the same file still race). Requires the LLM to use the new tool instead of `edit_file` — model behavior change. The `aedit_batched()` call itself still has the read-write gap vs. external writers.

---

### Strategy 9: Transactional Edit Queue

**Mechanism**: All edit operations are submitted to a per-file transaction queue. The queue processes operations FIFO, applying them to an in-memory snapshot and flushing to disk at transaction boundaries (commit). Conflicts are detected at commit time. Provides ACID-like guarantees per file.

```
edit_file(path, old, new):
  txn = queue.get_or_create(path)
  txn.enqueue(ReplaceOp(old, new))
  # returns immediately with a future

  --- queue worker (per file) ---
  while True:
    batch = txn.collect(window=50ms)
    content = aread(path)         # one read
    for op in batch:
      content = op.apply(content)
    awrite(path, content)         # one write
    resolve_futures(batch)
```

**Strengths**: Strongest guarantees — serializable, atomic per batch, conflict-detecting. Subsumes coalescing (Strategy 7's batching) and batch primitive (Strategy 8's API). Clean separation: callers enqueue, queue manages consistency.

**Weaknesses**: Most complex to implement. Introduces a persistent queue subsystem (memory, ordering, crash recovery). Adds latency for single edits (queue overhead). Overkill for the common case of 1-3 edits per file per turn.

---

## Analysis Matrix

### Dimensions

- **Implementation complexity**: LOC estimate, new dependencies, new subsystems
- **Performance**: round-trips to disk, latency profile, throughput under contention
- **Accuracy**: race-free guarantee, partial-failure handling, idempotency

### Comparison Table

| # | Strategy | Complexity (LOC / deps) | Round-trips | Latency | Race-Free | Partial-Failure | Idempotent |
|---|----------|------------------------|-------------|---------|-----------|-----------------|------------|
| 1 | **Serialize-per-file** (asyncio.Lock) | ~30 LOC, 0 deps | 1 read + 1 write per edit | Low (no contention) / blocks under contention | ✅ Yes (within process) | ✅ Lock released on exception | ❌ No (retry may double-apply) |
| 2 | **Single-write Python script** | ~0 LOC (uses run_command) | 1 read + 1 write total | Lowest (single call) | ✅ Yes (single process) | ❌ Script failure = all lost, no per-edit feedback | ❌ No |
| 3 | **edit_lines contiguous** | ~0 LOC (uses existing tool) | 1 read + 1 write per call | Low | ❌ No (only if caller merges) | ❌ All-or-nothing per call | ❌ No |
| 4 | **Unified diff / patch** | ~0 LOC (uses apply_diff) | 1 process invocation | Low | ❌ No (patch not guarded) | ✅ `patch` rejects on context mismatch | ✅ Yes (patch is idempotent with `--reject`) |
| 5 | **File locking (flock/fcntl)** | ~50 LOC, 0 deps | 1 read + 1 write per edit | Low / blocks under contention | ✅ Yes (across processes, local FS) | ✅ Lock released on crash (advisory) | ❌ No |
| 6 | **Optimistic concurrency** (version stamps) | ~60 LOC, 0 deps | 1 read + 1 write per attempt (2-3 on conflict) | Lowest (no contention) / retries on conflict | ⚠️ TOCTOU gap unless paired with atomic rename | ✅ Conflict error returned to caller | ✅ Yes (retry re-reads) |
| 7 | **In-memory staging buffer** | ~150 LOC, 0 deps | 1 read + 1 write per file per turn | Sub-ms (in-memory) / flush at turn end | ✅ Yes (within turn) | ⚠️ Buffer lost on crash | ⚠️ Buffer must invalidate on external change |
| 8 | **Batch-edit API primitive** | ~20 LOC tool wrapper (aedit_batched exists) | 1 read + 1 write per batch | Lowest (single call) | ⚠️ Within batch only; cross-batch races | ✅ Per-op `failed_operations` list | ❌ No |
| 9 | **Transactional edit queue** | ~300 LOC, 0 deps | 1 read + 1 write per window | Low (batched) / queue overhead | ✅ Yes (serializable) | ✅ Atomic per batch, futures resolved individually | ⚠️ Retry requires re-enqueue |

### Qualitative Summary

```
                        Race-Free ──────────────────── Not Race-Free
                            │
  Strong guarantee          │         Weak guarantee
  ┌─────────────────┐       │       ┌──────────────────┐
  │ 9. Txn Queue    │       │       │ 6. Optimistic*   │  (*TOCTOU gap)
  │ 1. Serialize    │       │       │ 8. Batch API*    │  (*cross-batch)
  │ 5. flock        │       │       │ 3. edit_lines    │
  │ 7. Staging buf  │       │       │ 4. Diff/patch    │
  └─────────────────┘       │       │ 2. Py script     │
                            │       └──────────────────┘
  High complexity ◀─────────┴─────────────────────────▶ Low complexity
  (300 LOC)                                           (0 LOC)
```

### Detail: Strategy 6 TOCTOU Gap

The optimistic concurrency check is:

```
t1: READ → content, stamp = hash(content)
t2: transform → new_content
t3: READ → current; if hash(current) != stamp: retry   ← check
t4: WRITE → new_content                                 ← act
```

Between t3 and t4, another writer can modify the file. The check passes but the write still clobbers. To close this gap, the write must be **conditional** — e.g., write to a temp file and `os.rename` (atomic on POSIX), but only if the source file's stamp still matches. Python's `os.rename` is atomic but does not provide a compare-and-swap. The only way to fully close the gap is to pair optimistic concurrency with a lock (Strategy 5) or an atomic rename guarded by a lock.

---

## Recommended Design

### The Optimal Combination

No single strategy is sufficient. The recommended design layers three strategies to achieve race-freedom, performance, and minimal complexity:

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: Coalescing Middleware (Strategy 7 + 8 hybrid)        │
│  ─────────────────────────────────────────────────────────────  │
│  • Detection window (50 ms) groups same-file edits            │
│  • Dispatches as single aedit_batched() call                   │
│  • Eliminates intra-turn race + reduces I/O                    │
│  • Result-maps back to original call IDs                       │
│  • In-memory snapshot per file per turn (staging buffer)       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  Layer 2: Per-File Async Mutex (Strategy 1)                    │
│  ─────────────────────────────────────────────────────────────  │
│  • asyncio.Lock per resolved file path                         │
│  • Acquired before aedit_batched(), released after write       │
│  • Eliminates inter-batch and inter-agent race                 │
│  • Different files → different locks → full parallelism        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  Layer 1: Atomic Write + Version Stamp (Strategy 6 + 4)        │
│  ─────────────────────────────────────────────────────────────  │
│  • Write to temp file, os.rename (atomic on POSIX)             │
│  • Capture old_hash at read; verify before rename              │
│  • Detects external process modification (outside Layer 2)     │
│  • Crash safety: rename is atomic — no partial writes          │
└─────────────────────────────────────────────────────────────────┘
```

### Rationale for Each Layer

**Layer 1 (Atomic write + version stamp)** — *Crash safety + external-writer detection*

This is the foundation. Even if Layers 2 and 3 are bypassed (e.g., an external process or a code path that skips the middleware), the write is atomic (temp file + `os.rename`) and the version stamp detects concurrent modification. This closes the TOCTOU gap of Strategy 6 by making the final write a conditional atomic rename.

Implementation in `LocalFilesystem.awrite_atomic()`:

```python
async def awrite_atomic(self, path, content, expected_hash=None):
    resolved = self._resolve_path(path)
    tmp = resolved.with_suffix(resolved.suffix + ".soothe.tmp")

    if expected_hash is not None:
        # Verify file hasn't changed since we read it
        async with aiofiles.open(resolved, "rb") as f:
            current = await f.read()
        if self._compute_hash(current.decode()) != expected_hash:
            raise EditConflictError(f"concurrent modification detected: {path}")

    # Write to temp file, then atomic rename
    async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
        await f.write(content)
        await f.flush()
        os.fsync(f.fileno())       # ensure durability before rename

    os.replace(str(tmp), str(resolved))   # atomic on POSIX
```

**Layer 2 (Per-file async mutex)** — *Inter-batch and inter-agent race elimination*

The `asyncio.Lock` per file path ensures that even if two coalescing windows or two agents edit the same file, their `aedit_batched()` calls are serialized. This is the simplest correct guard within a single process.

```python
class FileEditLockRegistry:
    """Per-file async locks, lazily created."""
    _locks: dict[str, asyncio.Lock]

    def get_or_create(self, path: str) -> asyncio.Lock:
        # Must be called from event loop thread — no race on dict
        if path not in self._locks:
            self._locks[path] = asyncio.Lock()
        return self._locks[path]
```

The lock is acquired in `aedit_batched()` (or a wrapper), making the entire read-modify-write atomic within the process. Different files use different locks — no cross-file serialization.

**Layer 3 (Coalescing + staging)** — *Performance: minimize I/O, eliminate intra-turn race*

The `EditCoalescingMiddleware` from the prior draft (2026-06-27) groups same-file edits within a 50 ms detection window into a single `aedit_batched()` call. This:
- Eliminates redundant reads (1 read per file per window, not 1 per edit)
- Eliminates the intra-turn race (edits in the same window are applied to the same in-memory snapshot)
- Reduces middleware traversal (1 batched call vs N individual calls)

The staging buffer extends coalescing across the full turn: the file is read once on first access, all subsequent edits apply to the in-memory buffer, and the buffer is flushed once at turn end (or when a non-edit tool needs the file).

### Decision Tree

The design uses a decision tree to select the appropriate path at runtime:

```
Incoming edit_file call
         │
         ▼
┌────────────────────────┐
│ Is this within a       │ YES  → Add to coalescing buffer (Layer 3)
│ coalescing window?     │──────────────────────────────────────────┐
│ (same turn, same file) │                                          │
└────────────────────────┘                                          │
         │ NO                                                        │
         ▼                                                           │
┌────────────────────────┐                                          │
│ Are there other edits  │ YES  → Enqueue in per-file transaction   │
│ pending for this file? │──────────────────────────────────────────┤
│                        │    queue (Layer 3 flush path)            │
└────────────────────────┘                                          │
         │ NO                                                        │
         ▼                                                           │
┌────────────────────────┐                                          │
│ Acquire per-file       │ ← Layer 2 (asyncio.Lock)                 │
│ async lock             │                                           │
└─────────────┬──────────┘                                          │
              │                                                      │
              ▼                                                      │
┌────────────────────────┐                                          │
│ Read file + capture    │ ← Layer 1 (version stamp)                │
│ content hash           │                                           │
└─────────────┬──────────┘                                          │
              │                                                      │
              ▼                                                      │
┌────────────────────────┐                                          │
│ Apply edit transform   │                                           │
└─────────────┬──────────┘                                          │
              │                                                      │
              ▼                                                      │
┌────────────────────────┐                                          │
│ Atomic write           │ ← Layer 1 (temp + rename)                │
│ (verify hash, rename)  │                                           │
└─────────────┬──────────┘                                          │
              │                                                      │
              ▼                                                      │
┌────────────────────────┐                                          │
│ Release lock           │ ← Layer 2                                 │
└─────────────┬──────────┘                                          │
              │                                                      │
              ▼                                                      │
         Success / ConflictError ────────────────────────────────────┘
```

### Why Not the Other Strategies

| Strategy | Why Not Primary |
|----------|----------------|
| **2. Single-write Python script** | Bypasses security policy, audit logging, backup creation. LLM unreliable at generating correct edit scripts. No per-edit feedback. **Rejected.** |
| **3. edit_lines contiguous** | Only works for line-based edits; LLM line numbers drift. Doesn't solve the race. **Subsumed by Layer 3 coalescing** (which merges any edit types). |
| **4. Unified diff / patch** | LLM unreliable at generating correct diffs. `patch` binary dependency. Not guarded against concurrent invocation. **Optional fallback** for agents that prefer diff-based editing, but guarded by Layer 2 lock. |
| **5. flock / fcntl** | Synchronous (needs `to_thread`). Doesn't work on NFS/virtual filesystems. Lock file cleanup burden. **Subsumed by Layer 2** (`asyncio.Lock` is simpler and sufficient for in-process races). Can be added as an option for cross-process safety if needed. |
| **9. Transactional edit queue** | 300 LOC of queue infrastructure for a problem that Layer 2+3 solves in ~80 LOC. Overkill for 1-3 edits per file per turn. **Deferred** — if future multi-agent workloads create high contention, upgrade Layer 3's coalescing into a full transaction queue. |

### What About `FileLockMiddleware` (Existing, Uninstalled)?

The existing `FileLockMiddleware` is a **cross-loop** lock for autopilot mode (different StrangeLoops editing the same file). It is **complementary** to this design:

- **This design's Layer 2** (`asyncio.Lock` per file) guards the read-modify-write cycle **within a single process**.
- **`FileLockMiddleware`** guards **across StrangeLoops** (different goals/loops that may run in separate worker processes).

The recommended action: install `FileLockMiddleware` in autopilot mode (as originally intended) **and** add Layer 2's per-file lock to `LocalFilesystem` for solo mode. They operate at different granularities and do not conflict.

---

## Component Overview

### Layer 1: Atomic Write + Version Stamp

**Location**: `packages/soothe/src/soothe/core/filesystem/local.py`

| Component | Responsibility |
|-----------|---------------|
| `awrite_atomic()` | Write to temp file, verify expected_hash, `os.replace` (atomic rename) |
| `_compute_hash()` | SHA-256 of content (already exists) |
| `EditConflictError` | Raised when version stamp mismatch detected |

**Changes to `aedit_batched()`**: After computing `new_content`, call `awrite_atomic(path, new_content, expected_hash=old_hash)` instead of direct `aiofiles.open(path, "w")`.

### Layer 2: Per-File Async Mutex

**Location**: `packages/soothe/src/soothe/core/filesystem/local.py`

| Component | Responsibility |
|-----------|---------------|
| `_file_locks: dict[str, asyncio.Lock]` | Per-path lock registry (instance attribute on `LocalFilesystem`) |
| `_get_file_lock(path) -> asyncio.Lock` | Lazily create or return existing lock |

**Changes to `aedit_batched()`**: Wrap the read-modify-write in `async with self._get_file_lock(path):`.

### Layer 3: Coalescing Middleware

**Location**: `packages/soothe/src/soothe/middleware/edit_coalescing.py` (new file, per prior draft)

| Component | Responsibility |
|-----------|---------------|
| `EditCoalescingMiddleware` | Detection window, group by file, dispatch as `aedit_batched()` |
| `_pending_edits: dict[str, list[PendingEdit]]` | Buffer of incoming edits per file |
| `_process_after_window()` | 50 ms timer → merge → dispatch → result-map |

### Data Flow

```
LLM emits 3 edit_file calls (2 to config.py, 1 to utils.py)
         │
         ▼
EditCoalescingMiddleware (Layer 3)
  ├── config.py: [edit_A, edit_B] → group
  └── utils.py:  [edit_C]         → group
         │  (50 ms window)
         ▼
For each file group:
  async with _get_file_lock(path):        ← Layer 2
      content = aread(path)               ← 1 read
      old_hash = hash(content)
      for op in group:
          content = op.apply(content)     ← in-memory transform
      awrite_atomic(path, content, old_hash)  ← Layer 1
         │
         ▼
Result mapping → resolve futures for edit_A, edit_B, edit_C
```

### Architectural Constraints

1. **Lock registry is per-`LocalFilesystem` instance** — not global. This is correct because each daemon process has one `LocalFilesystem`, and cross-process safety is handled by `FileLockMiddleware` (autopilot) or version stamps (Layer 1).
2. **`os.replace` is atomic on POSIX only** — on Windows, `os.replace` is also atomic (Python 3.3+). No platform-specific code needed.
3. **Temp file naming** — uses `.soothe.tmp` suffix to avoid collisions with user files. Temp file is in the same directory (required for `rename` to be atomic — cross-filesystem rename is not atomic).
4. **`aedit_batched()` is the only write path** — all edit tools (`edit_file`, `edit_lines`, `insert_lines`, `delete_lines`) route through `aedit_batched()` when coalescing is active. Direct `aedit()` calls (bypassing middleware) still benefit from Layer 1+2 if the lock+atomic-write is added to `aedit()` itself.

---

## Edge Cases

### 1. Concurrent Edits to Different Files

**Scenario**: Two `edit_file` calls target `config.py` and `utils.py` simultaneously.

**Behavior**: Fully parallel. Layer 2 uses different `asyncio.Lock` instances per path. No contention. Layer 3 coalesces them into separate batch groups. Each batch acquires its own lock independently.

**No special handling needed** — the design is per-file, not global.

### 2. Very Large Files

**Scenario**: Editing a 50 MB log file or a large generated data file.

**Concerns**:
- **Memory**: `aedit_batched()` reads the entire file into memory (`content = await f.read()`). A 50 MB file × N concurrent edits = 50N MB.
- **Latency**: Reading and writing 50 MB adds ~100-500 ms per operation.
- **Atomic write**: `os.replace` of a 50 MB temp file is instant (rename, not copy), but `fsync` of 50 MB is slow.

**Mitigations**:
- `LocalFilesystem` already enforces `max_file_size_bytes` (default 10 MB) — files above this are rejected on read.
- For large files, the staging buffer (Layer 3) is critical: read once, apply all edits in memory, write once — avoiding N× read/write.
- `fsync` can be made optional (configurable) — skip for non-critical files, enable for configuration/source files.
- Future: streaming line-based edit for very large files (read line-by-line, apply transforms, write to temp line-by-line). Out of scope for this design.

### 3. Network Filesystems (NFS, SMB, CIFS)

**Scenario**: The workspace is on an NFS mount or SMB share.

**Concerns**:
- **`flock`/`fcntl`**: Advisory locks are unreliable on NFS (client-side caching, no server-side lock manager in NFSv3). NFSv4 has byte-range locking but Python's `fcntl` may not use it correctly. → **Strategy 5 is not reliable here** — another reason it's not the primary.
- **`os.replace`**: Atomic rename is supported on NFSv3+ (server-side rename is atomic). However, if the temp file and target are on different NFS clients, the rename may not be atomic.
- **Version stamps (hash)**: Work correctly on NFS — the hash is computed from content read via NFS, which is eventually consistent. If another client writes between read and write, the hash mismatch is detected.
- **`asyncio.Lock`**: Works correctly — it's in-process, not affected by the filesystem.

**Mitigation**:
- Layer 1 (version stamp) is the **primary defense** on network filesystems — it detects concurrent modification even from other machines.
- Layer 2 (`asyncio.Lock`) protects within the process.
- Layer 3 (coalescing) reduces the number of read-write cycles, reducing the window for NFS-related races.
- **Configuration**: Add a `filesystem_backend` config field (`"local"` vs `"network"`). On `"network"`, enable stricter version-stamp checking (re-read + re-hash immediately before every write, even with the lock held) and disable `fsync` (NFS does its own caching).

### 4. Crash Recovery

**Scenario**: The daemon crashes (OOM, SIGKILL, power loss) during an edit operation.

**Failure modes and recovery**:

| Crash Point | On-Disk State | Recovery |
|-------------|---------------|----------|
| After read, before write | Original file intact | No recovery needed — edit is lost, agent retries on restart |
| During temp file write | Original file intact + partial `.soothe.tmp` | Temp file is orphaned. On next edit, detect stale temp file (older than edit start time), delete it. Original file is untouched. |
| After temp write, before `os.replace` | Original file + complete `.soothe.tmp` | Same as above — orphaned temp. Next edit deletes stale temp and proceeds. |
| During `os.replace` | `os.replace` is atomic on POSIX — either old or new file, never partial | No recovery needed. Either the edit applied or it didn't. |
| After `os.replace`, before result returned | New file on disk, but caller got no response | Caller (agent) doesn't know if edit applied. On retry, version stamp will differ if edit applied → `EditConflictError` → agent re-reads and re-edits. |

**Stale temp file cleanup**: On startup and before each edit, check for `.soothe.tmp` files. If a temp file exists and is older than a configurable staleness threshold (default: 5 minutes), delete it. This is safe because a temp file older than 5 minutes means the editing process crashed.

**Staging buffer loss (Layer 3)**: If the daemon crashes mid-turn, the in-memory staging buffer is lost. Edits that were buffered but not flushed are gone. This is acceptable because:
- The agent's turn is replayed from the checkpoint (LangGraph checkpoint) on restart.
- The replay re-emits the edit calls, which re-apply from scratch.
- Version stamps detect if any buffered edits partially flushed.

### 5. External Process Modifies File Mid-Turn

**Scenario**: A `run_command` call modifies a file that the staging buffer holds a stale copy of.

**Mitigation**:
- The staging buffer is **invalidated** when any non-edit tool is called. After `run_command` returns, all dirty buffer entries are flushed and the buffer is cleared.
- Version stamps (Layer 1) provide a final safety net: even if the buffer is stale, the `awrite_atomic()` hash check detects the external modification and raises `EditConflictError`.
- The agent receives the error and re-reads the file.

### 6. Symbolic Links and Path Aliasing

**Scenario**: Two edit calls use different paths that resolve to the same file (e.g., `./config.py` and `./symlink_to_config.py`).

**Mitigation**: Layer 2's lock registry must use `os.path.realpath()` (resolved canonical path) as the key, not the raw input path. This ensures `./config.py` and `./symlink_to_config.py` map to the same lock.

### 7. Empty Files and New File Creation

**Scenario**: `edit_file` on a file that doesn't exist yet (or was just created by a prior `write_file` call in the same turn).

**Mitigation**:
- `aedit()` raises `PathNotFoundError` — correct behavior, the agent should use `write_file` to create.
- The staging buffer handles this: if `write_file` creates a file in the same turn, the buffer is populated. Subsequent `edit_file` calls find the file in the buffer.
- `awrite_atomic()` handles the creation case: temp file is created, `os.replace` creates the target (atomic on POSIX).

---

## Implementation Plan

### Phase 1: Layer 1 + Layer 2 (Correctness)

**Goal**: Eliminate the lost-update race within a single process.

| Step | File | Change |
|------|------|--------|
| 1 | `filesystem/local.py` | Add `_file_locks` dict and `_get_file_lock()` method |
| 2 | `filesystem/local.py` | Add `awrite_atomic()` method (temp + fsync + `os.replace`) |
| 3 | `filesystem/local.py` | Modify `aedit()` to use lock + `awrite_atomic()` with version stamp |
| 4 | `filesystem/local.py` | Modify `aedit_lines()` similarly |
| 5 | `filesystem/local.py` | Modify `aedit_batched()` to use lock + `awrite_atomic()` |
| 6 | `filesystem/exceptions.py` | Add `EditConflictError` exception |
| 7 | `tests/integration/test_parallel_edits.py` | Add test: two concurrent `aedit()` calls to same file → both applied or one gets `EditConflictError` |

**Estimated LOC**: ~80 new, ~30 modified.

### Phase 2: Layer 3 (Performance — Coalescing)

**Goal**: Reduce I/O and eliminate intra-turn race.

| Step | File | Change |
|------|------|--------|
| 8 | `middleware/edit_coalescing.py` | Create `EditCoalescingMiddleware` (per prior draft 2026-06-27) |
| 9 | `middleware/_builder.py` | Insert `EditCoalescingMiddleware` at position 3 |
| 10 | Downstream middleware | Add fast-path check for `_batched` marker |
| 11 | `tests/unit/middleware/test_edit_coalescing.py` | Tests for grouping, merge, conflict, result mapping |

**Estimated LOC**: ~200 new (per prior draft). Depends on Phase 1's `aedit_batched()` being lock-guarded.

### Phase 3: Cross-Process Safety (Autopilot)

**Goal**: Eliminate cross-loop races in autopilot mode.

| Step | File | Change |
|------|------|--------|
| 12 | `middleware/file_lock.py` | Install in autopilot middleware chain (currently not wired) |
| 13 | `autopilot/file_lock_registry.py` | Ensure `FileLockRegistry` is in main workspace (currently only in worktree) |
| 14 | Integration test | Two StrangeLoops edit same file → second gets conflict error |

**Estimated LOC**: ~20 wiring + test code. Implementation already exists.

### Phase 4: Staging Buffer (Performance — Turn-Level)

**Goal**: Minimize I/O across a full turn.

| Step | File | Change |
|------|------|--------|
| 15 | `middleware/edit_coalescing.py` | Extend to maintain turn-level staging buffer |
| 16 | Buffer invalidation | Invalidate on non-edit tool call, on `run_command` |
| 17 | Flush at turn end | Hook into agent loop's turn-completion callback |

**Estimated LOC**: ~100 new. Deferred to Phase 4 — Phase 1-3 already provide correctness and good performance.

---

## Success Criteria

1. **INV-1**: Two concurrent `edit_file` calls to the same file → both edits present in final file, OR one returns `EditConflictError`. No silent loss. (Verified by integration test.)
2. **INV-2**: Three `edit_file` calls to the same file in one turn → exactly 1 file read and 1 file write on disk. (Verified by I/O count test.)
3. **INV-3**: No synchronous blocking call on the event loop during edit operations. (Verified by async profiler.)
4. **INV-4**: Kill daemon during `aedit_batched()` → file is either original or fully new, never partial. No orphaned temp files after 5 minutes. (Verified by crash test.)
5. **Performance**: 10 parallel `edit_file` calls to same file → total latency < 2× single-edit latency (vs 10× without coalescing). (Verified by benchmark.)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `asyncio.Lock` dict grows unbounded (many files edited once) | Add LRU eviction: locks unused for >5 minutes are removed. A removed lock is safe — next edit creates a new one. |
| `os.replace` fails on cross-filesystem temp (e.g., `/tmp` on different mount) | Temp file is always in the **same directory** as the target (suffix `.soothe.tmp`). Same filesystem guaranteed. |
| `fsync` slows down edits on slow disks | Make `fsync` configurable (`filesystem.fsync_on_write: true/false`). Default `true` for source files, `false` for logs. |
| Coalescing window adds 50 ms latency to single edits | Window is only started when an edit arrives. For single edits (no second edit within 50 ms), the window expires and the edit proceeds immediately. Net latency for single edits: ~50 ms (acceptable). Can tune to 25 ms if needed. |
| Staging buffer creates stale reads for `run_command` | Buffer is invalidated (flushed + cleared) before any non-edit tool call. Version stamp on flush catches residual staleness. |
| `EditConflictError` confuses the agent | Error message includes: file path, expected hash, actual hash, suggestion to re-read and retry. The agent's error-recovery loop handles this naturally. |

---

## Testing Strategy

### Unit Tests

| Test | File | Verifies |
|------|------|----------|
| `test_file_lock_registry` | `test_file_lock.py` | Lock creation, per-path isolation, LRU eviction |
| `test_awrite_atomic` | `test_unified.py` | Temp file creation, rename, hash verification |
| `test_edit_conflict_detection` | `test_unified.py` | `EditConflictError` raised on hash mismatch |
| `test_coalescing_grouping` | `test_edit_coalescing.py` | Edits grouped by file path |
| `test_coalescing_merge` | `test_edit_coalescing.py` | Deletions → insertions → replacements ordering |
| `test_coalescing_overlap` | `test_edit_coalescing.py` | Overlapping edits → conflict error |
| `test_result_mapping` | `test_edit_coalescing.py` | Batch result mapped to original call IDs |

### Integration Tests

| Test | File | Verifies |
|------|------|----------|
| `test_parallel_same_file_no_loss` | `test_parallel_edits.py` | INV-1: no silent loss |
| `test_parallel_different_files` | `test_parallel_edits.py` | Different files → fully parallel |
| `test_single_read_per_batch` | `test_parallel_edits.py` | INV-2: one read per file per batch |
| `test_crash_recovery` | `test_parallel_edits.py` | INV-4: atomic write, temp cleanup |
| `test_external_modification` | `test_parallel_edits.py` | Version stamp detects external write |
| `test_symlink_aliasing` | `test_parallel_edits.py` | Symlink and real path share lock |

### Benchmark

| Benchmark | Metric |
|-----------|--------|
| 1 edit, no coalescing | Baseline latency |
| 10 edits same file, no coalescing | 10× latency (race present) |
| 10 edits same file, with coalescing | < 2× baseline latency (INV-2 + performance) |
| 10 edits different files, with coalescing | ~1× baseline latency (parallel) |

---

## Out of Scope

- **Binary file editing** — This design addresses text files only. Binary file edits use `write_file` (full overwrite), which is inherently atomic with `awrite_atomic()`.
- **Cross-machine distributed locking** — For multi-daemon setups (future), a distributed lock service (Redis, etcd) would be needed. The version stamp (Layer 1) provides best-effort detection until then.
- **Git-index-aware edits** — Editing files that are staged in git's index. Git's index is separate from the working tree; this design operates on the working tree only.
- **Streaming edits for >10 MB files** — Future work: line-by-line streaming edit for very large files to avoid full-content buffering.

---

## Files Modified/Created

| File | Phase | Change |
|------|-------|--------|
| `foundation/core/filesystem/local.py` | 1 | Add `_file_locks`, `_get_file_lock()`, `awrite_atomic()`; modify `aedit()`, `aedit_lines()`, `aedit_batched()` |
| `foundation/core/filesystem/exceptions.py` | 1 | Add `EditConflictError` |
| `foundation/core/filesystem/unified.py` | 1 | Add `awrite_atomic()` to abstract interface |
| `middleware/edit_coalescing.py` | 2 | **Create** — Coalescing middleware |
| `middleware/_builder.py` | 2 | Wire `EditCoalescingMiddleware` at position 3 |
| `middleware/policy.py` | 2 | Fast-path check for `_batched` marker |
| `middleware/skill_activation.py` | 2 | Fast-path check |
| `middleware/rate_limit.py` | 2 | Fast-path check |
| `middleware/tool_concurrency.py` | 2 | Fast-path check |
| `middleware/file_lock.py` | 3 | Wire into autopilot middleware chain |
| `foundation/autopilot/file_lock_registry.py` | 3 | Ensure present in main workspace |
| `tests/integration/test_parallel_edits.py` | 1-3 | Race, crash, external-modification tests |
| `tests/unit/middleware/test_edit_coalescing.py` | 2 | Coalescing unit tests |
| `packages/soothe/pyproject.toml` | 2 | Add `aiofiles>=24.1.0` (if not already present) |

---

## References

- Prior draft: `docs/drafts/2026-06-27-edit-coalescing-async-io-design.md` (Layer 3 origin)
- RFC-101: Tool interface (middleware chain structure)
- RFC-102: Security filesystem policy (path validation, permissions)
- RFC-222: Autopilot goal engine architecture (`FileLockRegistry`, cross-loop locking)
- Existing implementation: `packages/soothe/src/soothe/core/filesystem/local.py` (`aedit`, `aedit_batched`, `apply_diff`)
- Existing middleware: `packages/soothe/src/soothe/middleware/file_lock.py` (uninstalled cross-loop lock)
