# Implementation Guide: Workspace Sync — Materialization and Incremental Persistence

**Guide**: IG-771
**Title**: Workspace Sync Implementation Guide
**Created**: 2026-09-01
**Related RFCs**: RFC-906 (Workspace Sync Architecture), RFC-102 (Security Filesystem Policy), RFC-621 (Workspace Host Convention)

## Overview

This guide implements the workspace sync subsystem specified in RFC-906. The subsystem provides filesystem-native agent workspaces with incremental materialization, CAS caching, dirty tracking, checkpointing, and incremental persistence to durable object storage via fsspec.

## Prerequisites

- [x] RFC-906 drafted
- [x] `WorkspaceSyncBackend` protocol exists in `soothe-sdk` (already implemented)
- [x] `fsspec` added to `soothe` dependencies
- [x] Development environment setup

## Implementation Plan

### Phase 1: FsspecSyncBackend + Security Primitives

**Goal**: Implement the concrete `FsspecSyncBackend` adapter with full security validation — the foundation that all subsequent phases depend on.

**Tasks**:
- [x] Add `fsspec` dependency to `packages/soothe/pyproject.toml`
- [x] Create `packages/soothe/src/soothe/workspace/sync/` package structure
- [x] Implement `FsspecSyncBackend` class in `sync/backends/fsspec.py`
- [x] Implement path validation utilities (`_validate_path_component`, `_validate_relative_path`)
- [x] Implement `construct_sync_backend()` factory with scheme allowlist
- [x] Implement `is_remote_workspace_uri()` URI classifier in `workspace/resolution.py`
- [x] Implement `IntegrityError` and `ConcurrentModificationError` exceptions
- [x] Write unit tests using `MemoryFileSystem`

### Phase 2: CAS Cache + Materialization

**Goal**: Local content-addressed storage cache with hardlink/reflink/copy fallback chain.

**Tasks**:
- [x] Implement `CASCache` in `sync/cas.py`
- [x] Implement materialization algorithm (manifest → CAS → hardlink/reflink)
- [x] Probe filesystem capabilities (reflink/hardlink support) at workspace open
- [x] Write CAS unit tests

### Phase 3: Dirty Tracker + Debouncer

**Goal**: Track filesystem mutations and trigger debounced checkpoints.

**Tasks**:
- [x] Implement hybrid dirty tracker in `sync/dirty_tracker.py` (inotify/FSEvents/stat-scan)
- [x] Implement `FileEvent` model and dirty set management
- [x] Implement debouncer in `sync/debouncer.py`
- [x] Add symlink detection (`os.lstat()`) and rejection of escaping symlinks
- [x] Handle inotify `ENOSPC` with per-subtree fallback
- [x] Write dirty tracker unit tests

### Phase 4: Checkpoint + Publish

**Goal**: Checkpoint lifecycle (snapshot + delta), background uploader, artifact publication.

**Tasks**:
- [x] Implement `CheckpointPayload` serialization/deserialization
- [x] Implement snapshot + delta checkpoint algorithm with compaction
- [x] Implement background uploader with backpressure (`max_pending_checkpoints`)
- [x] Implement artifact publication to `publish_prefix`
- [x] Implement crash recovery algorithm
- [x] Write checkpoint and publish unit tests

### Phase 5: WorkspaceStateStore + Integration

**Goal**: Per-workspace state database and daemon integration.

**Tasks**:
- [x] Implement `WorkspaceStateStore` protocol in `state/protocol.py`
- [x] Implement `SqliteWorkspaceStateStore` in `state/sqlite.py`
- [ ] Implement `PostgresWorkspaceStateStore` in `state/postgres.py` (deferred — SQLite mode sufficient for development)
- [x] Implement `create_workspace_state_store()` factory in `state/factory.py`
- [x] Implement `WorkspaceManager` in `sync/manager.py`
- [x] Implement `Workspace` handle in `sync/workspace.py`
- [ ] Integrate URI detection in daemon `_handle_loop_new` (next phase)
- [x] Write integration tests

## File Structure

```
packages/soothe/src/soothe/workspace/
├── sync/
│   ├── __init__.py
│   ├── manager.py
│   ├── workspace.py
│   ├── cas.py
│   ├── dirty_tracker.py
│   ├── debouncer.py
│   ├── manifest_synth.py
│   └── backends/
│       ├── __init__.py
│       └── fsspec.py
├── state/
│   ├── __init__.py
│   ├── protocol.py
│   ├── sqlite.py
│   ├── postgres.py
│   └── factory.py
├── resolution.py          (MODIFY)
└── __init__.py             (MODIFY)

packages/soothe/tests/unit/workspace/
├── sync/
│   ├── __init__.py
│   ├── test_fsspec_backend.py
│   ├── test_cas.py
│   ├── test_dirty_tracker.py
│   └── test_debouncer.py
└── state/
    ├── __init__.py
    └── test_state_store.py
```

## Testing Strategy

### Unit Tests

Phase 1 tests use `MemoryFileSystem` from fsspec core — zero I/O, zero network:

```python
async def test_put_blob_stores_content():
    fs = MemoryFileSystem()
    backend = FsspecSyncBackend(fs=fs, root="/test")
    await backend.put_blob("abc123...", b"hello")
    assert await backend.head_blob("abc123...") is True
    assert await backend.get_blob("abc123...") == b"hello"

async def test_put_blob_rejects_hash_mismatch():
    """S7: integrity verification on write."""
    fs = MemoryFileSystem()
    backend = FsspecSyncBackend(fs=fs, root="/test")
    with pytest.raises(IntegrityError):
        await backend.put_blob("wrong_hash", b"hello")

async def test_path_traversal_rejected():
    """S1: path traversal in artifact_path."""
    fs = MemoryFileSystem()
    backend = FsspecSyncBackend(fs=fs, root="/test")
    with pytest.raises(ValueError):
        await backend.publish_artifact("../../etc/passwd", b"data")

async def test_scheme_allowlist():
    """S8: SSRF prevention."""
    with pytest.raises(ValueError, match="unsupported.*scheme"):
        construct_sync_backend("file:///etc/passwd", config={})
```

### Integration Tests

Phase 5+ integration tests use a local `LocalFileSystem` with temp directories.

## Verification

- [x] All tests pass (`pytest packages/soothe/tests/unit/workspace/`) — 147 tests
- [x] `ruff check` clean (workspace sync + state modules)
- [x] `ruff format` clean
- [x] No vulture issues (workspace sync + state modules)
- [x] RFC-906 status updated to "Implemented (partial)"
- [ ] `./scripts/verify_finally.sh` green (pre-existing boundary violation in `soothe-autopilot` rail files, not from workspace sync)
- [ ] Daemon `_handle_loop_new` integration (next phase)

## Related Documents

- RFC-906: `docs/specs/RFC-906-workspace-sync-materialization.md`
- Design draft: `docs/drafts/2026-09-01-workspace-sync-final-design.md`
- Protocol source: `packages/soothe-sdk/src/soothe_sdk/protocols/workspace_sync.py`
