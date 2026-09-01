# RFC-906: Workspace Sync — Materialization and Incremental Persistence

**RFC**: 906
**Title**: Workspace Sync — Materialization and Incremental Persistence
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-09-01
**Author**: Xiaming Chen
**Depends On**: RFC-001 (Core Modules), RFC-102 (Security Filesystem Policy), RFC-621 (Workspace Host Convention), RFC-801/802 (Persistence Architecture), RFC-803 (StrangeLoop Checkpoint Backend)
**Design Draft**: `docs/drafts/2026-09-01-workspace-sync-final-design.md`

## Abstract

This RFC specifies the workspace sync subsystem: a filesystem-native agent workspace with incremental materialization, local CAS caching, dirty tracking, debounced checkpointing, and incremental persistence to a durable object store (S3, GCS, Azure Blob, local). The transport layer uses fsspec — one `FsspecSyncBackend` adapter supports all backends. The `WorkspaceSyncBackend` protocol (already in `soothe-sdk`) stays unchanged; the Workspace Manager and concrete backend live in `soothe` (host).

## Motivation

A filesystem-native research agent expects resources and artifacts as ordinary filesystem paths. The surrounding platform stores resources in an object store. A naive implementation downloads/uploads entire trees — wasting bandwidth on reused resources, incrementally modified outputs, and intermediate files that don't need persistence.

The system needs: incremental materialization, content-addressed caching, dirty tracking, checkpointing, and incremental persistence — all backend-agnostic behind a protocol boundary.

## Guiding Principles

1. **Object store is the durable source of truth** — the agent never sees it.
2. **Filesystem is the execution authority** — during a run, the agent writes locally with zero network latency.
3. **Materialization is not synchronization** — one-way (store → FS); persistence is one-way (FS → store).
4. **Writes are eventually persisted** — write locally → dirty tracking → checkpoint → storage backend.
5. **Content identity is independent of path** — SHA-256 content hashes; a path is only a logical reference.
6. **Transport is fsspec — protocol is not** — fsspec sits behind the `WorkspaceSyncBackend` protocol as a transport detail. One adapter, N backends.

## Component Overview

```text
S3/GCS/Azure/Local/Memory (durable store)
        │
        │ Resource Manifest
        ▼
WorkspaceSyncBackend (protocol)          ← soothe-sdk
  get_blob / put_blob / head_blob
  get_manifest / put_manifest
  list/get/put_checkpoint
  publish_artifact
        │ (injected)
        ▼
WorkspaceManager                         ← soothe (host)
  ├── Local CAS Cache (SHA-256 → blob)
  ├── Dirty Tracker (inotify/FSEvents/stat-scan)
  ├── Debounced Checkpointer
  └── FsspecSyncBackend (fsspec — unified adapter)
        │
        ▼
Agent Workspace (input/ working/ output/)
```

## Component Responsibilities

### WorkspaceSyncBackend Protocol (soothe-sdk)

**Purpose**: Abstract object-store operations behind a thin async protocol.

**Capabilities**: blob ops (content-addressed), manifest ops (optimistic concurrency), checkpoint ops, publish ops, optional streaming.

**Interfaces**: Provides `WorkspaceSyncBackend` Protocol; requires nothing (transport-agnostic).

### WorkspaceManager (soothe — host)

**Purpose**: Orchestrate the complete lifecycle of an agent workspace.

**Capabilities**: create workspace, load manifest, materialize resources, maintain CAS cache, track dirty files, create checkpoints, publish artifacts, recover interrupted runs, cleanup.

**Interfaces**: Requires `WorkspaceSyncBackend` (injected); provides `Workspace` handle.

### FsspecSyncBackend (soothe — host)

**Purpose**: Unified transport adapter — one implementation for all fsspec-supported filesystems (S3, GCS, Azure, local, memory).

**Capabilities**: Translates each `WorkspaceSyncBackend` call into fsspec operations via `asyncio.to_thread()`; path-layout mapper with security validation; dedicated thread pool.

**Interfaces**: Implements `WorkspaceSyncBackend`; requires `fsspec` + optional backend extras.

### WorkspaceStateStore (soothe — host)

**Purpose**: Per-workspace runtime cache tracking dirty files, blob cache index, and checkpoint references.

**Capabilities**: SQLite (workspace-local) or PostgreSQL (shared pool) following `persistence.default_backend`.

**Interfaces**: Factory pattern mirroring `create_cron_job_store()`.

## Data Flow

### Flow 1: Materialization

1. Fetch manifest from storage backend.
2. For each resource: check local CAS → hardlink/reflink to workspace, or download → verify SHA-256 → store in CAS → materialize.
3. Repeated materialization of unchanged resources = zero object-data bandwidth.

### Flow 2: Checkpoint

1. Agent writes files → dirty tracker records events.
2. Debounce window expires → checkpoint triggered.
3. Hash dirty files → CAS lookup → upload new blobs → update manifest.
4. Write checkpoint payload (snapshot or delta) to state store + storage backend.
5. Background uploader persists asynchronously.

### Flow 3: Publish

1. Agent declares artifacts.
2. Workspace Manager hashes and uploads to `publish_prefix`.
3. Returns `Artifact` with `published_uri`.

## Architectural Constraints

1. **Protocol boundary at storage backend, not manager** — the CAS/dirty-tracking/checkpointing algorithm is backend-agnostic by construction. Making the manager a protocol would produce N implementations of the same algorithm.
2. **fsspec behind the protocol** — `FsspecSyncBackend` is the only concrete backend. New backends require zero code (optional pip extras).
3. **Content-addressed blobs are immutable** — write-once, idempotent `put_blob`.
4. **Optimistic concurrency on manifests** — S3 conditional writes (default), atomic rename (local FS), read-then-write guard (fallback).
5. **Agent never sees credentials or URIs** — only the `FsspecSyncBackend` holds storage credentials; the agent sees ordinary local paths.

## Security Constraints

1. **Path traversal protection (S1)**: All path construction methods validate inputs — `_validate_path_component()` rejects non-alphanumeric IDs; `_validate_relative_path()` rejects `..`, absolute paths, null bytes.
2. **Symlink escape prevention (S2)**: Dirty tracker uses `os.lstat()`; checkpoint rejects symlinks escaping workspace root.
3. **Credential leakage prevention (S3)**: `fs.use_cache = False`; clear `storage_options` after construction; prefer env vars / IAM roles.
4. **SSRF prevention (S8)**: Explicit scheme allowlist `{"s3", "gs", "az"}` — `file://`, `sftp://`, `http://` rejected.
5. **Blob integrity (S7)**: Hash verification on write; `.sha256` sidecar on CAS cache hit.
6. **Cleanup race prevention (S10)**: Multi-step cleanup with `closing` state flag.

## Core Invariants

1. Every persisted blob is immutable.
2. Every blob is identified by its cryptographic content hash.
3. A workspace is owned by exactly one run.
4. The agent never directly accesses the storage backend.
5. Local writes never require synchronous network access.
6. Every remote checkpoint references a complete manifest.
7. Published artifacts are immutable versions.
8. A failed upload can always be retried safely.
9. The storage backend is pluggable — the Workspace Manager algorithm is backend-agnostic.

## Package Placement

| Piece | Package |
|-------|---------|
| `WorkspaceSyncBackend` protocol + data models | `soothe-sdk` |
| `WorkspaceManager`, `Workspace`, CAS, dirty tracker, `FsspecSyncBackend` | `soothe` (host) |
| `WorkspaceStateStore` (SQLite/Postgres) + factory | `soothe` (host) |
| `construct_sync_backend(uri, config)` factory | `soothe` (host) |
| Workspace lifecycle RPCs | `soothe-daemon` |

```text
soothe-sdk → soothe-nano → soothe → soothe-daemon
```

No DAG arrows reversed. `fsspec` is a `soothe` (host) dependency only.

## Dependency Changes

```toml
# packages/soothe/pyproject.toml
[project]
dependencies = [
    # ... existing deps ...
    "fsspec>=2025.0",          # NEW — core, lightweight
]

[project.optional-dependencies]
s3 = ["s3fs>=2025.0"]
gcs = ["gcsfs>=2025.0"]
azure = ["adlfs>=2025.0"]
all-backends = ["s3fs>=2025.0", "gcsfs>=2025.0", "adlfs>=2025.0"]
```

No changes to `soothe-sdk` or `soothe-nano`.

## Module Layout

```text
soothe/workspace/
├── sync/                          ← NEW
│   ├── __init__.py
│   ├── manager.py                 ← WorkspaceManager
│   ├── workspace.py               ← Workspace (per-run handle)
│   ├── cas.py                     ← Local CAS cache
│   ├── dirty_tracker.py           ← Hybrid FS watcher
│   ├── debouncer.py               ← Debounced checkpoint trigger
│   ├── manifest_synth.py          ← Manifest synthesis from prefix listing
│   └── backends/
│       ├── __init__.py
│       └── fsspec.py              ← FsspecSyncBackend
├── state/                         ← NEW
│   ├── __init__.py
│   ├── protocol.py                ← WorkspaceStateStore protocol
│   ├── sqlite.py                  ← SqliteWorkspaceStateStore
│   ├── postgres.py               ← PostgresWorkspaceStateStore
│   └── factory.py                 ← create_workspace_state_store()
├── resolution.py                  ← MODIFY: URI scheme detection
└── __init__.py                    ← MODIFY: re-export new API
```

## Non-Goals

- Agent identity (separate RFC).
- Continuous bidirectional sync (materialization is one-way).
- Lazy materialization in MVP (eager + CAS is the MVP).
- Chunking in MVP (file-level CAS is sufficient).
- Patch journals in MVP (snapshot + delta is the MVP).
- Replacing StrangeLoop checkpoint system (RFC-803) — workspace checkpoints are a distinct, lower-layer concept.

## Relationship to Existing RFCs

| RFC | Relationship |
|-----|-------------|
| RFC-621 | Workspace placement follows daemon convention |
| RFC-102 | Path traversal, workspace boundary compose `SecureFilesystemBackend` |
| RFC-801/802 | State store follows `persistence.default_backend` |
| RFC-803 | Workspace checkpoints ≠ loop checkpoints (distinct layers) |
| RFC-306 | Workspace lifecycle adjacent to thread lifecycle |

## References

- Design draft: `docs/drafts/2026-09-01-workspace-sync-final-design.md` (v2.1, 53 sections)
- Implementation guide: `docs/impl/IG-771-workspace-sync-implementation.md`
- Protocol source: `packages/soothe-sdk/src/soothe_sdk/protocols/workspace_sync.py`
