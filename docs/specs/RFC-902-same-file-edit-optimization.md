# RFC-902: Same-File Edit Concurrency and Optimization

**RFC**: 902
**Title**: Same-File Edit Concurrency and Optimization
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-28
**Dependencies**: RFC-101 (tool interface), RFC-102 (security filesystem policy), RFC-222 (autopilot goal engine)

---

## Abstract

When an LLM emits multiple `edit_file` tool calls in a single response, the agent runtime dispatches them in parallel via `asyncio.gather`. When two or more of those calls target the **same file**, each independently performs a read-modify-write cycle on disk with no mutual exclusion. Because no lock is held between the read and the write, the second write silently clobbers the first — a classic **lost-update race**. The agent receives success responses for both calls, but only one edit survives on disk.

This RFC specifies a three-layer concurrency architecture that eliminates the race, minimizes I/O, and provides crash safety:

- **Layer 1** — Atomic write via temp file + `os.replace` with version-stamp verification (crash safety + external-writer detection)
- **Layer 2** — Per-file `asyncio.Lock` mutex (in-process race elimination)
- **Layer 3** — Coalescing middleware with a staging buffer (I/O minimization + intra-turn race elimination)

The design is self-contained: it catalogs nine candidate strategies, analyzes their tradeoffs, and recommends the layered combination that is race-free, low-latency, and minimal in new code. Each layer's interface signatures, error handling, configuration, and migration plan are specified.

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
    async with aiofiles.open(resolved) as f:   # READ
        content = await f.read()
    # ... validate, replace ...
    new_content = content.replace(old_string, new_string, 1)
    async with aiofiles.open(resolved, "w") as f:  # WRITE
        await f.write(new_content)
```

Two concurrent invocations interleave:

```
Time  Call A                              Call B
----  ------                              ------
t1    read(path) -> content_v0
t2                                         read(path) -> content_v0   (stale!)
t3    modify(content_v0) -> content_v1
t4    write(path, content_v1)
t5                                         modify(content_v0) -> content_v2  (based on stale read)
t6                                         write(path, content_v2)          (clobbers A's edit)
```

Call A's edit is **silently lost**. No error is raised. The agent has no signal that its edit failed.

### Impact

| Scenario | Frequency | Consequence |
|----------|-----------|-------------|
| LLM emits 2+ `edit_file` calls to same file in one turn | Common in refactoring tasks | Silent data loss |
| Subagent + parent edit same file concurrently | Occasional in autopilot mode | One agent's work vanishes |
| Multiple StrangeLoops edit shared file | Rare (mitigated by cross-loop lock) | Cross-loop clobber |

### Current State of the Codebase

| Component | Status | Gap |
|-----------|--------|-----|
| `LocalFilesystem.aedit()` | Async via aiofiles, but read-modify-write is **not atomic** | No lock between read and write |
| `LocalFilesystem.aedit_batched()` | Batch primitive exists; applies N ops in one read-modify-write | No concurrency guard — two batches to same file still race |
| `FileLockMiddleware` | Implemented, tested, **not installed** | Cross-loop lock for autopilot only; not a within-loop concurrency guard |
| `apply_diff()` | Shells out to `patch` command | No locking; `patch` itself is not atomic |

---

## Guiding Principles

1. **Correctness first** — A race-free guarantee is non-negotiable. Performance optimizations that sacrifice correctness are rejected.
2. **Minimal new code** — Prefer composing existing primitives (`aedit_batched`, lock registries) over building new subsystems.
3. **Layered defense** — Use multiple strategies at different layers so a single layer's failure does not produce data loss.
4. **Fail loud, not silent** — If a conflict is unavoidable, raise an error the agent can act on. Never silently drop an edit.
5. **No blocking the event loop** — Locks must be async-aware (`asyncio.Lock`, not `threading.Lock` on the hot path).

---

## Terminology

| Term | Definition |
|------|------------|
| **Lost-update race** | Concurrent read-modify-write cycles where the last writer silently overwrites earlier writers' changes |
| **Read-modify-write cycle** | The pattern: read file -> transform content in memory -> write file back to disk |
| **Critical section** | The window between read and write where the file's on-disk state must not change |
| **Coalescing** | Grouping multiple edit operations targeting the same file into a single batched call |
| **Version stamp** | A content hash captured at read time, checked before write to detect concurrent modification |
| **Optimistic concurrency** | Proceed without locking; detect conflicts at write time via version stamp; retry on mismatch |
| **Pessimistic concurrency** | Acquire an exclusive lock before reading; hold until write completes; block other writers |
| **Batched edit** | A single `aedit_batched()` call applying multiple operations (delete, insert, replace) in one read-modify-write |
| **Staging buffer** | An in-memory snapshot of file content held for the duration of a turn; edits apply to the buffer, flushed once at turn end |
| **Detection window** | A short time interval (default 50 ms) during which incoming edit calls are grouped before dispatch |

---

## System Invariants

After this design is implemented, the following must always hold:

1. **INV-1 (No silent loss)**: If two edits to the same file are issued concurrently, either (a) both are applied, or (b) the conflicting edit returns an error to the caller. Silent loss is impossible.
2. **INV-2 (Single read per file per batch)**: Edits to the same file within a coalescing window result in exactly one file read and one file write.
3. **INV-3 (No event-loop block)**: File I/O and lock acquisition are async; no synchronous blocking call on the event loop's hot path.
4. **INV-4 (Crash safety)**: A crash during edit leaves either the original file or the fully written new file — never a partially written file (via atomic rename).

---

## Strategy Catalog

Nine candidate strategies were analyzed. Each is summarized below; the recommended design (Section: Component Overview) layers three of them.

### Strategy 1: Serialize-Per-File (Async Mutex)

Maintain a `dict[str, asyncio.Lock]` keyed by resolved file path. Every edit method acquires the per-file lock before reading and releases it after writing.

**Strengths**: Simple, correct, minimal conceptual change. Different files are fully parallel (different locks).
**Weaknesses**: Serializes all edits to the same file even when they target non-overlapping regions. Adds a lock lookup on every edit.

### Strategy 2: Single-Write Python Script

Emit a single `run_command` call that runs a Python script applying all edits in one process.

**Strengths**: Zero race window (single process, single read-write). No new infrastructure.
**Weaknesses**: Bypasses filesystem abstraction (security policy, audit logging, backup creation). LLMs are unreliable at generating correct edit scripts. No per-edit feedback. **Rejected.**

### Strategy 3: `edit_file_lines` for Contiguous Ranges

When multiple edits target contiguous line ranges, combine them into a single `edit_file_lines` call.

**Strengths**: Uses an existing tool. Reduces call count.
**Weaknesses**: Only works for line-number-based edits. LLM line numbers drift. Non-contiguous edits can't be merged. Does not solve the race. **Subsumed by Layer 3.**

### Strategy 4: Unified Diff / Patch

Generate a single unified diff and apply via `apply_diff()`.

**Strengths**: Single process invocation. `patch` has context validation.
**Weaknesses**: LLM unreliable at generating correct diffs. `patch` binary dependency. Not guarded against concurrent invocation. **Optional fallback**, guarded by Layer 2 lock.

### Strategy 5: File Locking (flock / fcntl)

Use OS-level advisory file locks (`fcntl.flock` with `LOCK_EX`).

**Strengths**: Works across processes. Kernel-enforced.
**Weaknesses**: Synchronous (needs `to_thread`). Doesn't work on NFS/virtual filesystems. Lock file cleanup burden. **Subsumed by Layer 2** (`asyncio.Lock` is simpler for in-process races). Can be added for cross-process safety if needed.

### Strategy 6: Optimistic Concurrency with Version Stamps

Capture a content hash at read time. Before writing, re-check the hash. If changed, abort and retry.

**Strengths**: No locks — maximum parallelism for non-conflicting edits. Works across processes.
**Weaknesses**: **TOCTOU gap**: between the hash re-check and the write, another writer can still sneak in. To close this gap, the write must be a conditional atomic rename (Layer 1). Under high contention, retries waste CPU.

### Strategy 7: In-Memory Staging Buffer

Maintain an in-memory representation of file content. All edits apply to the buffer. Flush to disk once at turn end.

**Strengths**: Eliminates all races within a turn. Minimizes I/O. Sub-millisecond edit latency. Enables undo.
**Weaknesses**: Memory pressure for large files. Stale buffer if external process modifies file mid-turn. Complex flush/invalidation logic. **Selected as Layer 3 component.**

### Strategy 8: Batch-Edit API Primitive

Expose a single `edit_batch` tool that applies multiple operations in one `aedit_batched()` call.

**Strengths**: The `aedit_batched()` primitive **already exists** in `LocalFilesystem`. Single read-modify-write eliminates the race within the batch. Per-operation result mapping already implemented.
**Weaknesses**: Does not solve cross-batch races. Requires the LLM to use a new tool. **Subsumed by Layer 3** (coalescing dispatches to `aedit_batched()` automatically).

### Strategy 9: Transactional Edit Queue

All edit operations submitted to a per-file transaction queue. ACID-like guarantees per file.

**Strengths**: Strongest guarantees — serializable, atomic per batch, conflict-detecting.
**Weaknesses**: ~300 LOC of queue infrastructure. Adds latency for single edits. Overkill for the common case. **Deferred** — if future multi-agent workloads create high contention, upgrade Layer 3 into a full transaction queue.

### Analysis Matrix

| # | Strategy | Complexity (LOC / deps) | Round-trips | Race-Free | Partial-Failure | Idempotent |
|---|----------|------------------------|-------------|-----------|-----------------|------------|
| 1 | Serialize-per-file (asyncio.Lock) | ~30 LOC, 0 deps | 1 read + 1 write per edit | Yes (within process) | Lock released on exception | No |
| 2 | Single-write Python script | ~0 LOC | 1 read + 1 write total | Yes (single process) | No per-edit feedback | No |
| 3 | edit_file_lines contiguous | ~0 LOC | 1 read + 1 write per call | No | All-or-nothing per call | No |
| 4 | Unified diff / patch | ~0 LOC | 1 process invocation | No (patch not guarded) | Patch rejects on mismatch | Yes |
| 5 | File locking (flock/fcntl) | ~50 LOC, 0 deps | 1 read + 1 write per edit | Yes (across processes, local FS) | Lock released on crash | No |
| 6 | Optimistic concurrency | ~60 LOC, 0 deps | 1 read + 1 write per attempt | TOCTOU gap unless paired with atomic rename | Conflict error returned | Yes |
| 7 | In-memory staging buffer | ~150 LOC, 0 deps | 1 read + 1 write per file per turn | Yes (within turn) | Buffer lost on crash | Must invalidate on external change |
| 8 | Batch-edit API primitive | ~20 LOC wrapper | 1 read + 1 write per batch | Within batch only | Per-op failed_operations list | No |
| 9 | Transactional edit queue | ~300 LOC, 0 deps | 1 read + 1 write per window | Yes (serializable) | Atomic per batch | Retry requires re-enqueue |

### TOCTOU Gap in Optimistic Concurrency

The optimistic concurrency check is:

```
t1: READ -> content, stamp = hash(content)
t2: transform -> new_content
t3: READ -> current; if hash(current) != stamp: retry   (check)
t4: WRITE -> new_content                                 (act)
```

Between t3 and t4, another writer can modify the file. The check passes but the write still clobbers. To close this gap, the write must be **conditional** — write to a temp file and `os.rename` (atomic on POSIX), but only if the source file's stamp still matches. This is exactly what Layer 1 provides.

---

## Component Overview

The recommended design layers three strategies to achieve race-freedom, performance, and minimal complexity:

```
+---------------------------------------------------------------+
|  Layer 3: Coalescing Middleware + Staging Buffer              |
|  (Strategy 7 + 8 hybrid)                                      |
|  - Detection window (50 ms) groups same-file edits            |
|  - Dispatches as single aedit_batched() call                  |
|  - Eliminates intra-turn race + reduces I/O                   |
|  - Result-maps back to original call IDs                      |
|  - In-memory snapshot per file per turn (staging buffer)     |
+------------------------------+--------------------------------+
                               |
+------------------------------v--------------------------------+
|  Layer 2: Per-File Async Mutex                                |
|  (Strategy 1)                                                 |
|  - asyncio.Lock per resolved file path                        |
|  - Acquired before aedit_batched(), released after write      |
|  - Eliminates inter-batch and inter-agent race                |
|  - Different files -> different locks -> full parallelism     |
+------------------------------+--------------------------------+
                               |
+------------------------------v--------------------------------+
|  Layer 1: Atomic Write + Version Stamp                        |
|  (Strategy 6 + atomic rename)                                 |
|  - Write to temp file, os.replace (atomic on POSIX)           |
|  - Capture old_hash at read; verify before rename             |
|  - Detects external process modification (outside Layer 2)    |
|  - Crash safety: rename is atomic -- no partial writes        |
+---------------------------------------------------------------+
```

### Rationale for Each Layer

**Layer 1 (Atomic write + version stamp)** — *Crash safety + external-writer detection*

This is the foundation. Even if Layers 2 and 3 are bypassed (e.g., an external process or a code path that skips the middleware), the write is atomic (temp file + `os.replace`) and the version stamp detects concurrent modification. This closes the TOCTOU gap of optimistic concurrency by making the final write a conditional atomic rename.

**Layer 2 (Per-file async mutex)** — *Inter-batch and inter-agent race elimination*

The `asyncio.Lock` per file path ensures that even if two coalescing windows or two agents edit the same file, their `aedit_batched()` calls are serialized. This is the simplest correct guard within a single process.

**Layer 3 (Coalescing + staging)** — *Performance: minimize I/O, eliminate intra-turn race*

The coalescing middleware groups same-file edits within a 50 ms detection window into a single `aedit_batched()` call. This eliminates redundant reads (1 read per file per window, not 1 per edit), eliminates the intra-turn race (edits in the same window are applied to the same in-memory snapshot), and reduces middleware traversal (1 batched call vs N individual calls). The staging buffer extends coalescing across the full turn.

### Why Not the Other Strategies

| Strategy | Why Not Primary |
|----------|----------------|
| 2. Single-write Python script | Bypasses security policy, audit logging, backup creation. LLM unreliable at generating correct edit scripts. No per-edit feedback. **Rejected.** |
| 3. edit_file_lines contiguous | Only works for line-based edits; LLM line numbers drift. Doesn't solve the race. **Subsumed by Layer 3.** |
| 4. Unified diff / patch | LLM unreliable at generating correct diffs. `patch` binary dependency. **Optional fallback** guarded by Layer 2 lock. |
| 5. flock / fcntl | Synchronous (needs `to_thread`). Doesn't work on NFS/virtual filesystems. Lock file cleanup burden. **Subsumed by Layer 2.** Can be added for cross-process safety. |
| 9. Transactional edit queue | 300 LOC of queue infrastructure for a problem that Layer 2+3 solves in ~80 LOC. Overkill for 1-3 edits per file per turn. **Deferred.** |

### Relationship to Existing `FileLockMiddleware`

The existing `FileLockMiddleware` is a **cross-loop** lock for autopilot mode (different StrangeLoops editing the same file). It is **complementary** to this design:

- **This design's Layer 2** (`asyncio.Lock` per file) guards the read-modify-write cycle **within a single process**.
- **`FileLockMiddleware`** guards **across StrangeLoops** (different goals/loops that may run in separate worker processes).

The recommended action: install `FileLockMiddleware` in autopilot mode (as originally intended) **and** add Layer 2's per-file lock to `LocalFilesystem` for solo mode. They operate at different granularities and do not conflict.

---

## Architectural Constraints

1. **Lock registry is per-`LocalFilesystem` instance** — not global. Each daemon process has one `LocalFilesystem`. Cross-process safety is handled by `FileLockMiddleware` (autopilot) or version stamps (Layer 1).
2. **`os.replace` is atomic on POSIX and Windows** (Python 3.3+). No platform-specific code needed.
3. **Temp file naming** — uses `.soothe.tmp` suffix to avoid collisions with user files. Temp file is in the **same directory** as the target (required for `rename` to be atomic — cross-filesystem rename is not atomic).
4. **`aedit_batched()` is the only write path** — all edit tools (`edit_file`, `edit_file_lines`, `insert_lines`, `delete_lines`) route through `aedit_batched()` when coalescing is active. Direct `aedit()` calls (bypassing middleware) still benefit from Layer 1+2 if the lock+atomic-write is added to `aedit()` itself.
5. **Lock registry key must be `os.path.realpath()`** — resolved canonical path, not raw input path. This ensures `./config.py` and `./symlink_to_config.py` map to the same lock.

---

## Detailed Design

### Layer 1: Atomic Write + Version Stamp

**Location**: `packages/soothe/src/soothe/foundation/core/filesystem/local.py`

#### Interface: `awrite_atomic`

```python
async def awrite_atomic(
    self,
    path: str | Path,
    content: str,
    expected_hash: str | None = None,
) -> WriteResult:
    """Write content to disk atomically via temp file + os.replace.

    If expected_hash is provided, the file's current content hash is
    verified before the rename. A mismatch raises EditConflictError.

    Args:
        path: Target file path (resolved internally).
        content: Full file content to write.
        expected_hash: SHA-256 of the content at read time.
            If None, no version check is performed.

    Returns:
        WriteResult with path, bytes_written, and new_hash.

    Raises:
        EditConflictError: If expected_hash is provided and the
            file's current hash does not match.
        OSError: If temp file creation or rename fails.
    """
    resolved = self._resolve_path(path)
    tmp = resolved.with_suffix(resolved.suffix + ".soothe.tmp")

    if expected_hash is not None:
        async with aiofiles.open(resolved, "rb") as f:
            current = await f.read()
        if self._compute_hash(current.decode("utf-8")) != expected_hash:
            raise EditConflictError(
                f"concurrent modification detected: {path}"
            )

    # Write to temp file, then atomic rename
    async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
        await f.write(content)
        await f.flush()
        if self._fsync_on_write:
            os.fsync(f.fileno())

    os.replace(str(tmp), str(resolved))

    new_hash = self._compute_hash(content)
    return WriteResult(
        path=str(path),
        bytes_written=len(content.encode("utf-8")),
        new_hash=new_hash,
    )
```

#### Interface: `EditConflictError`

**Location**: `packages/soothe/src/soothe/foundation/core/filesystem/exceptions.py`

```python
class EditConflictError(Exception):
    """Raised when a version stamp mismatch indicates concurrent modification.

    Attributes:
        path: The file path that had a conflict.
        expected_hash: The hash captured at read time.
        actual_hash: The hash found at write time (None if file was deleted).
    """

    def __init__(
        self,
        path: str,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
    ):
        self.path = path
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        super().__init__(
            f"concurrent modification detected: {path}"
        )
```

#### Changes to `aedit_batched()`

After computing `new_content`, call `awrite_atomic(path, new_content, expected_hash=old_hash)` instead of direct `aiofiles.open(path, "w")`.

#### Changes to `aedit()`

Same pattern: capture `old_hash` at read time, pass as `expected_hash` to `awrite_atomic()`.

#### Changes to `apply_diff()`

After `patch` applies, re-read the file and verify the hash matches the expected post-patch hash. If not, raise `EditConflictError`. The `patch` command itself provides context-line validation, but the version stamp adds protection against concurrent invocations.

---

### Layer 2: Per-File Async Mutex

**Location**: `packages/soothe/src/soothe/foundation/core/filesystem/local.py`

#### Interface: `FileEditLockRegistry`

```python
class FileEditLockRegistry:
    """Per-file async locks, lazily created.

    Locks are keyed by os.path.realpath() to ensure symlink-aliased
    paths share the same lock. An LRU eviction policy removes locks
    unused for longer than eviction_timeout seconds to prevent
    unbounded growth.

    This class is NOT thread-safe for dict mutation. It must be
    accessed only from the event loop thread. Since asyncio.Lock
    acquisition is async and the event loop is single-threaded,
    there is no race on the _locks dict.
    """

    def __init__(self, eviction_timeout: float = 300.0):
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_used: dict[str, float] = {}
        self._eviction_timeout = eviction_timeout

    def get_or_create(self, path: str) -> asyncio.Lock:
        """Return the lock for the given path, creating it if needed.

        Args:
            path: Raw file path (will be canonicalized via realpath).

        Returns:
            The asyncio.Lock for this file path.
        """
        canonical = os.path.realpath(path)
        now = time.monotonic()
        self._last_used[canonical] = now
        if canonical not in self._locks:
            self._locks[canonical] = asyncio.Lock()
        self._evict_stale(now)
        return self._locks[canonical]

    def _evict_stale(self, now: float) -> None:
        """Remove locks unused for longer than eviction_timeout."""
        stale = [
            path for path, t in self._last_used.items()
            if now - t > self._eviction_timeout
        ]
        for path in stale:
            # Only evict if not currently held
            if not self._locks[path].locked():
                del self._locks[path]
                del self._last_used[path]
```

#### Integration into `aedit_batched()`

```python
async def aedit_batched(
    self, path, operations, *, backup=True
) -> BatchedEditResult:
    lock = self._file_locks.get_or_create(str(path))
    async with lock:
        # --- critical section (serialized per file) ---
        content = await self._aread_internal(path)
        old_hash = self._compute_hash(content)
        # ... apply operations, detect overlaps ...
        new_content = "".join(lines)
        await self.awrite_atomic(path, new_content, expected_hash=old_hash)
        # --- end critical section ---
    return BatchedEditResult(...)
```

#### Integration into `aedit()`

```python
async def aedit(self, path, old_string, new_string, replace_all=False):
    lock = self._file_locks.get_or_create(str(path))
    async with lock:
        content = await self._aread_internal(path)
        old_hash = self._compute_hash(content)
        # ... validate, replace ...
        new_content = content.replace(old_string, new_string, 1)
        await self.awrite_atomic(path, new_content, expected_hash=old_hash)
    return EditResult(...)
```

---

### Layer 3: Coalescing Middleware + Staging Buffer

**Location**: `packages/soothe/src/soothe/middleware/edit_coalescing.py` (new file)

#### Interface: `EditCoalescingMiddleware`

```python
class EditCoalescingMiddleware(AgentMiddleware):
    """Groups same-file edit calls within a detection window.

    When an edit tool call arrives, it is added to a per-file pending
    buffer instead of executing immediately. A 50 ms detection window
    timer collects additional edits to the same file. When the window
    expires, all pending edits for each file are dispatched as a single
    aedit_batched() call. Results are mapped back to the original
    call IDs.

    If no second edit arrives within the window, the single edit
    proceeds after the window expires (net latency: ~50 ms for
    single edits).

    A staging buffer extends coalescing across the full turn: the file
    is read once on first access, all subsequent edits apply to the
    in-memory buffer, and the buffer is flushed once at turn end or
    when a non-edit tool is called.
    """

    EDIT_TOOL_NAMES: frozenset[str] = frozenset({
        "edit_file",
        "edit_file_lines",
        "insert_lines",
        "delete_lines",
    })

    def __init__(
        self,
        detection_window_ms: int = 50,
        enable_staging_buffer: bool = True,
    ):
        self._detection_window = detection_window_ms / 1000.0
        self._enable_staging = enable_staging_buffer
        self._pending_edits: dict[str, list[PendingEdit]] = {}
        self._staging_buffer: dict[str, StagingEntry] = {}
        self._lock = asyncio.Lock()
        self._window_timer: asyncio.Task | None = None
```

#### Interface: `PendingEdit`

```python
@dataclass
class PendingEdit:
    """A single edit operation awaiting batch dispatch."""
    tool_name: str
    file_path: str
    args: dict[str, Any]
    result_future: asyncio.Future
    call_id: str
    timestamp: float = field(default_factory=time.monotonic)
```

#### Interface: `StagingEntry`

```python
@dataclass
class StagingEntry:
    """In-memory snapshot of a file for the staging buffer."""
    content: str
    content_hash: str
    dirty: bool = False
    last_synced: float = field(default_factory=time.monotonic)

    def apply_edit(self, old_string: str, new_string: str) -> int:
        """Apply a string replacement to the in-memory content.

        Returns the number of replacements made.
        """
        count = self.content.count(old_string)
        self.content = self.content.replace(old_string, new_string)
        self.dirty = True
        return count
```

#### Detection Window Flow

```python
async def _on_edit_arrived(self, edit: PendingEdit) -> None:
    """Add edit to pending buffer and start window if needed."""
    async with self._lock:
        path_key = os.path.realpath(edit.file_path)
        if path_key not in self._pending_edits:
            self._pending_edits[path_key] = []
        self._pending_edits[path_key].append(edit)

        if self._window_timer is None or self._window_timer.done():
            self._window_timer = asyncio.create_task(
                self._process_after_window()
            )

async def _process_after_window(self) -> None:
    """Wait for detection window, then dispatch all pending edits."""
    await asyncio.sleep(self._detection_window)
    async with self._lock:
        pending = self._pending_edits
        self._pending_edits = {}
        self._window_timer = None

    for path, edits in pending.items():
        await self._dispatch_batched_edits(path, edits)
```

#### Batch Dispatch

```python
async def _dispatch_batched_edits(
    self, path: str, edits: list[PendingEdit]
) -> None:
    """Convert pending edits to BatchedEditOperations and dispatch.

    Operations are ordered: deletions (descending) ->
    insertions (ascending) -> replacements (descending by line number)
    to preserve line indices during in-memory application.

    Overlapping replacements are detected and rejected with
    EditConflictError for the conflicting edits.
    """
    operations = self._convert_to_operations(edits)

    # Check for overlapping line ranges
    overlaps = self._find_overlaps(operations)
    if overlaps:
        for edit in overlaps:
            edit.result_future.set_exception(
                EditConflictError(
                    f"overlapping edits in same batch: {edit.file_path}"
                )
            )
        # Non-overlapping edits still proceed
        operations = [
            op for op in operations if op not in overlaps
        ]

    backend = self._get_backend()
    result = await backend.aedit_batched(path, operations, backup=True)

    # Map results back to original call IDs
    self._resolve_futures(edits, result)
```

#### Staging Buffer Invalidation

```python
async def _invalidate_staging_buffer(self) -> None:
    """Flush and clear the staging buffer.

    Called before any non-edit tool invocation (e.g., run_command)
    to ensure the agent reads fresh disk content.
    """
    for path, entry in list(self._staging_buffer.items()):
        if entry.dirty:
            backend = self._get_backend()
            await backend.awrite_atomic(
                path,
                entry.content,
                expected_hash=entry.content_hash,
            )
    self._staging_buffer.clear()
```

#### Data Flow

```
LLM emits 3 edit_file calls (2 to config.py, 1 to utils.py)
         |
         v
EditCoalescingMiddleware (Layer 3)
  |-- config.py: [edit_A, edit_B] -> group
  +-- utils.py:  [edit_C]         -> group
         |  (50 ms window)
         v
For each file group:
  async with _get_file_lock(path):        <- Layer 2
      content = aread(path)               <- 1 read
      old_hash = hash(content)
      for op in group:
          content = op.apply(content)     <- in-memory transform
      awrite_atomic(path, content, old_hash)  <- Layer 1
         |
         v
Result mapping -> resolve futures for edit_A, edit_B, edit_C
```

---

## Error Handling

### `EditConflictError` Recovery

When `EditConflictError` is raised, the caller (agent) receives a structured error:

```python
# Error message format (no internal identifiers in user-visible text):
# "concurrent modification detected: config.py
#  Expected hash: a1b2c3..., Actual hash: d4e5f6...
#  Suggestion: re-read the file and retry the edit."
```

The agent's error-recovery loop handles this naturally: it re-reads the file and re-applies the edit. The version stamp ensures the re-read gets the latest content.

### Partial Batch Failure

When `aedit_batched()` reports per-operation failures (via `failed_operations`), the coalescing middleware resolves the successful edits' futures normally and sets exceptions on the failed ones:

```python
for edit, op_result in zip(edits, result.operation_results):
    if op_result.success:
        edit.result_future.set_result(op_result)
    else:
        edit.result_future.set_exception(
            EditError(f"edit failed: {op_result.error}")
        )
```

### Stale Temp File Cleanup

On startup and before each edit, check for `.soothe.tmp` files:

```python
def _cleanup_stale_temp(self, target_path: Path) -> None:
    """Remove orphaned temp files older than the staleness threshold."""
    tmp = target_path.with_suffix(target_path.suffix + ".soothe.tmp")
    if tmp.exists():
        age = time.time() - tmp.stat().st_mtime
        if age > self._temp_staleness_threshold:
            tmp.unlink()
```

### Lock Registry LRU Eviction

Locks unused for longer than `eviction_timeout` (default 300 seconds) are removed. A removed lock is safe — the next edit creates a new one. Only locks not currently held are evicted.

---

## Configuration

New configuration fields in `FilesystemConfig`:

```python
class FilesystemConfig(BaseModel):
    # ... existing fields ...

    fsync_on_write: bool = Field(
        default=True,
        description="Call fsync before atomic rename for crash safety.",
    )
    temp_file_suffix: str = Field(
        default=".soothe.tmp",
        description="Suffix for temporary files during atomic write.",
    )
    temp_staleness_threshold_seconds: float = Field(
        default=300.0,
        description="Age threshold for orphaned temp file cleanup.",
    )
    file_lock_eviction_timeout_seconds: float = Field(
        default=300.0,
        description="Idle time before per-file locks are evicted from the registry.",
    )
```

New configuration fields in middleware config:

```python
class EditCoalescingConfig(BaseModel):
    enabled: bool = Field(
        default=True,
        description="Enable edit coalescing middleware for same-file edit batching.",
    )
    detection_window_ms: int = Field(
        default=50,
        description="Time window to collect same-file edits before batch dispatch.",
    )
    enable_staging_buffer: bool = Field(
        default=True,
        description="Maintain in-memory file snapshots across a full agent turn.",
    )
    staging_buffer_max_files: int = Field(
        default=100,
        description="Maximum files held in the staging buffer before forced flush.",
    )
    staging_buffer_max_bytes: int = Field(
        default=104857600,  # 100 MB
        description="Maximum total content size in the staging buffer before forced flush.",
    )
```

Network filesystem awareness:

```python
class FilesystemConfig(BaseModel):
    # ... existing fields ...

    backend_type: Literal["local", "network"] = Field(
        default="local",
        description="Filesystem backend type. 'network' enables stricter version-stamp checking.",
    )
```

When `backend_type == "network"`: re-read and re-hash immediately before every write (even with the lock held), and disable `fsync` (NFS does its own caching).

---

## Migration Plan

### Phase 1: Layer 1 + Layer 2 (Correctness)

**Goal**: Eliminate the lost-update race within a single process.

| Step | File | Change |
|------|------|--------|
| 1 | `foundation/core/filesystem/exceptions.py` | Add `EditConflictError` exception |
| 2 | `foundation/core/filesystem/local.py` | Add `_file_locks` registry and `_get_file_lock()` method |
| 3 | `foundation/core/filesystem/local.py` | Add `awrite_atomic()` method (temp + fsync + `os.replace`) |
| 4 | `foundation/core/filesystem/local.py` | Modify `aedit()` to use lock + `awrite_atomic()` with version stamp |
| 5 | `foundation/core/filesystem/local.py` | Modify `aedit_lines()` similarly |
| 6 | `foundation/core/filesystem/local.py` | Modify `aedit_batched()` to use lock + `awrite_atomic()` |
| 7 | `foundation/core/filesystem/unified.py` | Add `awrite_atomic()` to abstract interface |
| 8 | `tests/integration/test_parallel_edits.py` | Test: two concurrent `aedit()` calls to same file |

**Estimated LOC**: ~80 new, ~30 modified.

**Compatibility**: Fully backward-compatible. Existing callers of `aedit()` / `aedit_batched()` get race protection transparently. No API changes.

**Rollback**: Revert the lock acquisition and `awrite_atomic()` calls. The original `aiofiles.open(path, "w")` path remains as fallback.

### Phase 2: Layer 3 (Performance — Coalescing)

**Goal**: Reduce I/O and eliminate intra-turn race.

| Step | File | Change |
|------|------|--------|
| 9 | `middleware/edit_coalescing.py` | Create `EditCoalescingMiddleware` |
| 10 | `middleware/_builder.py` | Insert `EditCoalescingMiddleware` at position 3 |
| 11 | Downstream middleware | Add fast-path check for `_batched` marker |
| 12 | `tests/unit/middleware/test_edit_coalescing.py` | Tests for grouping, merge, conflict, result mapping |

**Estimated LOC**: ~200 new. Depends on Phase 1's `aedit_batched()` being lock-guarded.

**Compatibility**: Middleware is opt-in via config (`edit_coalescing.enabled: true`). Default `true` for new deployments, `false` for existing deployments during migration.

**Rollback**: Set `edit_coalescing.enabled: false` in config. Middleware is skipped; edits go directly to `aedit()` / `aedit_batched()` (which still have Layer 1+2 protection).

### Phase 3: Cross-Process Safety (Autopilot)

**Goal**: Eliminate cross-loop races in autopilot mode.

| Step | File | Change |
|------|------|--------|
| 13 | `middleware/file_lock.py` | Install in autopilot middleware chain (currently not wired) |
| 14 | `foundation/autopilot/engine/file_lock_registry.py` | Ensure `FileLockRegistry` is in main workspace |
| 15 | Integration test | Two StrangeLoops edit same file |

**Estimated LOC**: ~20 wiring + test code. Implementation already exists.

**Compatibility**: Autopilot-mode-only change. Solo mode is unaffected.

### Phase 4: Staging Buffer (Performance — Turn-Level)

**Goal**: Minimize I/O across a full turn.

| Step | File | Change |
|------|------|--------|
| 16 | `middleware/edit_coalescing.py` | Extend to maintain turn-level staging buffer |
| 17 | Buffer invalidation | Invalidate on non-edit tool call, on `run_command` |
| 18 | Flush at turn end | Hook into agent loop's turn-completion callback |

**Estimated LOC**: ~100 new. Deferred to Phase 4 — Phases 1-3 already provide correctness and good performance.

### Phased Rollout Strategy

| Phase | Risk | Rollout | Feature Flag |
|-------|------|---------|-------------|
| 1 | Low (internal, transparent) | Immediate deploy | None (always on) |
| 2 | Medium (new middleware) | Opt-in, then default | `edit_coalescing.enabled` |
| 3 | Low (autopilot only) | Autopilot deployments | `autopilot.file_lock.enabled` |
| 4 | Medium (turn-level state) | Opt-in | `edit_coalescing.enable_staging_buffer` |

---

## Edge Cases

### 1. Concurrent Edits to Different Files

Two `edit_file` calls target `config.py` and `utils.py` simultaneously. Fully parallel — Layer 2 uses different `asyncio.Lock` instances per path. No contention. Layer 3 coalesces them into separate batch groups. No special handling needed.

### 2. Very Large Files

Editing a 50 MB file: `aedit_batched()` reads the entire file into memory. `LocalFilesystem` already enforces `max_file_size_bytes` (default 10 MB) — files above this are rejected on read. The staging buffer is critical for large files: read once, apply all edits in memory, write once. `fsync` can be made optional via config. Future: streaming line-based edit for very large files (out of scope).

### 3. Network Filesystems (NFS, SMB, CIFS)

`flock`/`fcntl` are unreliable on NFS. `os.replace` is supported on NFSv3+ but may not be atomic across clients. Version stamps (hash) work correctly on NFS — the hash detects concurrent modification from other machines. Mitigation: Layer 1 (version stamp) is the primary defense; Layer 2 (`asyncio.Lock`) protects within the process; `backend_type: "network"` enables stricter checking and disables `fsync`.

### 4. Crash Recovery

| Crash Point | On-Disk State | Recovery |
|-------------|---------------|----------|
| After read, before write | Original file intact | Edit lost; agent retries on restart |
| During temp file write | Original file + partial `.soothe.tmp` | Temp orphaned; next edit deletes stale temp |
| After temp write, before `os.replace` | Original file + complete `.soothe.tmp` | Same as above |
| During `os.replace` | Either old or new (atomic) | No recovery needed |
| After `os.replace`, before result | New file, caller got no response | Caller retries; version stamp detects if already applied |

Staging buffer loss on crash: the agent's turn is replayed from the LangGraph checkpoint. Replayed edit calls re-apply from scratch. Version stamps detect partially flushed edits.

### 5. External Process Modifies File Mid-Turn

A `run_command` call modifies a file that the staging buffer holds a stale copy of. Mitigation: the staging buffer is invalidated (flushed + cleared) when any non-edit tool is called. Version stamps (Layer 1) provide a final safety net: `awrite_atomic()` hash check detects the external modification and raises `EditConflictError`.

### 6. Symbolic Links and Path Aliasing

Two edit calls use different paths that resolve to the same file (e.g., `./config.py` and `./symlink_to_config.py`). Mitigation: Layer 2's lock registry uses `os.path.realpath()` as the key, ensuring both paths map to the same lock.

### 7. Empty Files and New File Creation

`edit_file` on a nonexistent file raises `PathNotFoundError` — correct behavior; the agent should use `write_file` to create. The staging buffer handles same-turn creation: if `write_file` creates a file, the buffer is populated. `awrite_atomic()` handles creation: temp file is created, `os.replace` creates the target atomically.

---

## Testing Strategy

### Unit Tests

| Test | File | Verifies |
|------|------|----------|
| `test_file_lock_registry` | `test_file_lock.py` | Lock creation, per-path isolation, LRU eviction |
| `test_awrite_atomic` | `test_unified.py` | Temp file creation, rename, hash verification |
| `test_edit_conflict_detection` | `test_unified.py` | `EditConflictError` raised on hash mismatch |
| `test_coalescing_grouping` | `test_edit_coalescing.py` | Edits grouped by file path |
| `test_coalescing_merge` | `test_edit_coalescing.py` | Deletions -> insertions -> replacements ordering |
| `test_coalescing_overlap` | `test_edit_coalescing.py` | Overlapping edits -> conflict error |
| `test_result_mapping` | `test_edit_coalescing.py` | Batch result mapped to original call IDs |

### Integration Tests

| Test | File | Verifies |
|------|------|----------|
| `test_parallel_same_file_no_loss` | `test_parallel_edits.py` | INV-1: no silent loss |
| `test_parallel_different_files` | `test_parallel_edits.py` | Different files -> fully parallel |
| `test_single_read_per_batch` | `test_parallel_edits.py` | INV-2: one read per file per batch |
| `test_crash_recovery` | `test_parallel_edits.py` | INV-4: atomic write, temp cleanup |
| `test_external_modification` | `test_parallel_edits.py` | Version stamp detects external write |
| `test_symlink_aliasing` | `test_parallel_edits.py` | Symlink and real path share lock |

### Benchmark

| Benchmark | Metric |
|-----------|--------|
| 1 edit, no coalescing | Baseline latency |
| 10 edits same file, no coalescing | 10x latency (race present) |
| 10 edits same file, with coalescing | < 2x baseline latency |
| 10 edits different files, with coalescing | ~1x baseline latency (parallel) |

---

## Success Criteria

1. **INV-1**: Two concurrent `edit_file` calls to the same file -> both edits present in final file, OR one returns `EditConflictError`. No silent loss.
2. **INV-2**: Three `edit_file` calls to the same file in one turn -> exactly 1 file read and 1 file write on disk.
3. **INV-3**: No synchronous blocking call on the event loop during edit operations.
4. **INV-4**: Kill daemon during `aedit_batched()` -> file is either original or fully new, never partial. No orphaned temp files after 5 minutes.
5. **Performance**: 10 parallel `edit_file` calls to same file -> total latency < 2x single-edit latency.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `asyncio.Lock` dict grows unbounded | LRU eviction: locks unused for >5 minutes are removed |
| `os.replace` fails on cross-filesystem temp | Temp file is always in the **same directory** as the target |
| `fsync` slows down edits on slow disks | Configurable via `filesystem.fsync_on_write` |
| Coalescing window adds 50 ms latency to single edits | Window only starts when an edit arrives; for single edits, expires and proceeds immediately. Can tune to 25 ms |
| Staging buffer creates stale reads for `run_command` | Buffer invalidated (flushed + cleared) before any non-edit tool call; version stamp on flush catches residual staleness |
| `EditConflictError` confuses the agent | Error message includes file path, expected hash, actual hash, suggestion to re-read and retry |

---

## Out of Scope

- **Binary file editing** — This design addresses text files only. Binary file edits use `write_file` (full overwrite), which is inherently atomic with `awrite_atomic()`.
- **Cross-machine distributed locking** — For multi-datacenter deployments. Future work.
- **Git-index-aware edits** — Git's index is separate from the working tree; this design operates on the working tree only.
- **Streaming edits for >10 MB files** — Future work: line-by-line streaming edit for very large files.
- **Transactional edit queue (Strategy 9)** — Deferred; if future multi-agent workloads create high contention, upgrade Layer 3 into a full transaction queue.

---

## Files Modified/Created

| File | Phase | Change |
|------|-------|--------|
| `foundation/core/filesystem/exceptions.py` | 1 | Add `EditConflictError` |
| `foundation/core/filesystem/local.py` | 1 | Add `_file_locks`, `_get_file_lock()`, `awrite_atomic()`; modify `aedit()`, `aedit_lines()`, `aedit_batched()` |
| `foundation/core/filesystem/unified.py` | 1 | Add `awrite_atomic()` to abstract interface |
| `middleware/edit_coalescing.py` | 2 | **Create** — Coalescing middleware + staging buffer |
| `middleware/_builder.py` | 2 | Wire `EditCoalescingMiddleware` at position 3 |
| `middleware/policy.py` | 2 | Fast-path check for `_batched` marker |
| `middleware/skill_activation.py` | 2 | Fast-path check |
| `middleware/rate_limit.py` | 2 | Fast-path check |
| `middleware/tool_concurrency.py` | 2 | Fast-path check |
| `middleware/file_lock.py` | 3 | Wire into autopilot middleware chain |
| `foundation/autopilot/engine/file_lock_registry.py` | 3 | Ensure present in main workspace |
| `tests/integration/test_parallel_edits.py` | 1-3 | Race, crash, external-modification tests |
| `tests/unit/middleware/test_edit_coalescing.py` | 2 | Coalescing unit tests |
| `config/models.py` | 1-2 | Add `FilesystemConfig` and `EditCoalescingConfig` fields |

---

## Related Documents

- [RFC Standard](./rfc-standard.md)
- [RFC Index](./rfc-index.md)
- RFC-101: Tool interface (middleware chain structure)
- RFC-102: Security filesystem policy (path validation, permissions)
- RFC-222: Autopilot goal engine architecture (cross-loop locking)
- Prior design draft: `docs/archive/drafts/2026-06-27-edit-coalescing-async-io-design.md` (Layer 3 origin)
