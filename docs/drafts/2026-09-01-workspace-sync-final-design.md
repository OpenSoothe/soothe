# Workspace Sync: Materialization and Incremental Persistence — Final Design

**Status:** Final (consolidated design — supersedes all prior workspace-sync drafts)
**Version:** 2.0
**Date:** 2026-09-01
**Scope:** Filesystem-native agent runtime with multi-backend durable object storage (S3, GCS, Azure, local), local filesystem workspace, incremental materialization, dirty tracking, checkpointing, and incremental persistence.

> **Supersedes:**
> - `2026-08-25-research-workspace-materialization-design.md` (v1.6 — original materialization design)
> - `2026-09-01-workspace-sync-layer-comparison.md` (layer placement analysis — conclusion adopted)
> - `2026-09-01-workspace-sync-via-s3-uri-design.md` (`s3://` URI entry point — generalized to any URI scheme)
> - `2026-09-01-fsspec-vs-s3-review.md` (fsspec vs boto3 review — decision: adopt fsspec)
>
> This document is the single authoritative design for the workspace sync subsystem. All prior drafts are removed.

---

## 1. Problem

A filesystem-native research agent expects user resources and generated artifacts to exist as ordinary filesystem paths. The surrounding platform stores uploaded resources and persistent artifacts in an object store (S3-compatible, GCS, Azure Blob, or local filesystem for dev/testing).

A naive implementation performs:

```text
object store → download entire resource tree → agent filesystem
agent → upload entire output tree → object store
```

This wastes bandwidth because:

1. Resources are frequently reused across research runs.
2. Agent outputs are incrementally modified rather than rewritten from scratch.
3. Research runs may contain many intermediate files that do not need persistence.
4. Large resources may change only partially.
5. Multiple runs may share identical resources.
6. Uploading every filesystem event to object storage introduces excessive network traffic.
7. The object store should be durable storage, not the agent's hot working filesystem.

The system therefore needs a filesystem workspace with **incremental materialization, local caching, dirty tracking, content addressing, checkpointing, and incremental persistence**.

---

## 2. Design principles

### 2.1 Object store is the durable source of truth

The object store (S3/MinIO/GCS/Azure/local) stores: user resources, resource manifests, durable checkpoints, published artifacts, content-addressed blobs. The agent never needs to know that the object store exists. The storage backend is abstracted behind the `WorkspaceSyncBackend` protocol (§6b).

### 2.2 Filesystem is the execution authority

During a run: `Agent → Local FS`. The agent can freely create, modify, rename, and delete files without network latency.

### 2.3 Materialization is not synchronization

Materialization means: `logical resource manifest → local filesystem representation`. It is **not** continuous bidirectional synchronization (see §38).

### 2.4 Writes are eventually persisted

The normal lifecycle is:

```text
write locally → dirty tracking → checkpoint → storage backend
```

not `write → network → storage backend`.

### 2.5 Content identity is independent of path

The system uses SHA-256 content hashes: `content → SHA-256 → immutable blob`. A path such as `input/paper.pdf` is only a logical reference.

### 2.6 Transport is fsspec — protocol is not

The `WorkspaceSyncBackend` protocol carries workspace-layer semantics (content-addressed blobs, manifest optimistic concurrency, checkpoint lifecycle, artifact publication). fsspec is the **transport layer** behind one concrete `FsspecSyncBackend` adapter — it is not a replacement for the protocol. This gives N backends (S3, GCS, Azure, local, memory, SFTP, WebDAV) for the cost of one adapter.

---

## 3. High-level architecture

```text
                         ┌────────────────────────────┐
                         │  S3 / MinIO / GCS / Azure  │
                         │  / Local / Memory           │
                         │  (durable store)            │
                         │                             │
                         │ resources/                  │
                         │ manifests/                  │
                         │ blobs/                      │
                         │ checkpoints/                │
                         │ artifacts/                  │
                         └─────────────┬───────────────┘
                                       │
                              Resource Manifest
                                       │
                                       ▼
              ┌──────────────────────────────────────────────┐
              │     WorkspaceSyncBackend (protocol)           │  ← soothe-sdk
              │     get_blob / put_blob / head_blob           │
              │     get_manifest / put_manifest               │
              │     list/get/put_checkpoint                    │
              │     publish_artifact                          │
              └──────────────────────┬───────────────────────┘
                                     │  (injected)
                                     ▼
                    ┌──────────────────────────────┐
                    │    Workspace Manager          │  ← soothe (host)
                    └──────────────┬───────────────┘
                                 │
                 ┌───────────────┴────────────────┐
                 │                                │
                 ▼                                ▼
        ┌─────────────────┐              ┌────────────────┐
        │ Local CAS Cache │              │ Workspace State │
        │                 │              │ SQLite | PgSQL  │
        │ SHA256 → blob   │              │ dirty/state     │
        └────────┬────────┘              └───────┬────────┘
                 │                              │
                 └──────────────┬───────────────┘
                                │
                         reflink / hardlink
                                │
                                ▼
                   ┌────────────────────────┐
                   │    Agent Workspace     │
                   │                        │
                   │ input/                 │
                   │ working/               │
                   │ output/                │
                   │ manifest.json          │
                   └───────────┬────────────┘
                               │
                         filesystem-native agent
                               │
                               ▼
                        filesystem writes
                               │
                         FS event watcher
                               │
                               ▼
                        Dirty Tracker
                               │
                    ┌──────────┴──────────┐
                    │                     │
               checkpoint              publish
                    │                     │
                    ▼                     ▼
            WorkspaceSyncBackend   WorkspaceSyncBackend
            (→ durable store)       (→ durable store)
```

---

## 4. Core components

### 4.1 Workspace Manager

Responsible for the complete lifecycle of an agent workspace.

Responsibilities:

- create workspace
- load resource manifest
- materialize resources
- maintain local cache
- track filesystem mutations
- calculate content hashes
- create checkpoints
- commit artifacts
- recover interrupted runs
- cleanup workspace

Conceptual API:

```python
workspace = await workspace_manager.open(run_id)
await workspace.materialize(resources)
await agent.run(workspace.root)
await workspace.checkpoint()
artifacts = await workspace.publish()
await workspace.close()
```

> **API consistency note:** all lifecycle methods are `async` (network and disk I/O).

---

## 5. Workspace layout

Each agent run gets an isolated directory. Placement follows the Soothe workspace convention (RFC-621): daemon-generated workspaces live under `$SOOTHE_HOME/data/workspaces/` (or the configured `data/workspaces/` root), distinct from the Docker volume mount point at `$SOOTHE_HOME/workspaces/`.

```text
$SOOTHE_HOME/data/workspaces/
└── <run-id>/
    ├── input/
    │   ├── paper.pdf
    │   ├── paper2.pdf
    │   └── notes.md
    │
    ├── working/
    │   ├── extracted/
    │   ├── chunks/
    │   ├── images/
    │   └── tmp/
    │
    ├── output/
    │   ├── report.md
    │   ├── references.bib
    │   └── analysis.json
    │
    ├── .workspace/            # runtime-owned, hidden from agent
    │   ├── manifest.json
    │   ├── state.db           # workspace-local runtime cache (see §21)
    │   └── checkpoints/
    │
    └── ...
```

Only `input`, `working`, and `output` are exposed as ordinary agent directories. `.workspace` is runtime-owned and should be hidden from the agent (path-policy enforcement, RFC-102).

---

## 6. Resource model

A resource is a logical input supplied to the agent. The model is **purely content-addressed** — `sha256` is the identity. Physical location (S3 key, GCS path, local file) is a backend implementation detail and does **not** appear on the wire contract.

```json
{
  "id": "res-123",
  "path": "input/paper.pdf",
  "size": 18273491,
  "sha256": "abc123...",
  "content_type": "application/pdf"
}
```

> **Design decision:** The SDK `Resource` is content-addressed (`sha256` is the canonical identity); no `uri` field is carried. The physical location is resolved internally by the `WorkspaceSyncBackend` implementation (see §6b). The `Resource` is just "I want content X at logical path Y." This makes CAS deduplication automatic — the backend resolves `sha256 → blob path` internally, and the same content used by 1,000 runs references one blob.

The canonical model is defined as a Pydantic `BaseModel` in `soothe-sdk` (see §6b for the protocol).

---

## 6b. Storage-backend protocol (`WorkspaceSyncBackend`)

> **Design decision:** The Workspace Manager depends on a **protocol boundary** so the storage backend is pluggable. The CAS, dirty tracking, checkpointing, and workspace lifecycle stay as concrete host code; only the object-store operations are abstracted. This matches Soothe's existing pattern (`VectorStoreProtocol` + `VectorRecord` both live in `soothe-sdk`, with concrete implementations in the host).

### Protocol boundary

The protocol abstracts **only the object-store operations** the Workspace Manager needs. The Workspace Manager (concrete, in `soothe`) depends on the protocol + data models. The algorithm (CAS + dirty tracking + debouncing + checkpointing) is backend-agnostic by construction — it only talks to the protocol.

```text
┌─────────────────────────────────────────────────────────┐
│  soothe-sdk (shared contracts)                          │
│                                                         │
│  Data models:  Resource, ManifestEntry, Manifest,      │
│                ArtifactSpec, Artifact                   │
│  Protocol:     WorkspaceSyncBackend                    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  soothe (host runner)                                   │
│                                                         │
│  WorkspaceManager (concrete)                            │
│    ├─ CAS cache                                         │
│    ├─ dirty tracker                                      │
│    ├─ debounced checkpointer                            │
│    └─ backend: WorkspaceSyncBackend (injected)          │
│         ├─ FsspecSyncBackend  (fsspec — unified)        │
│         │    ├─ S3FileSystem       (s3fs)      [s3]     │
│         │    ├─ LocalFileSystem    (core)      [dev]    │
│         │    ├─ GCSFileSystem      (gcsfs)     [gcs]    │
│         │    ├─ AzureBlobFS        (adlfs)    [azure]   │
│         │    └─ MemoryFileSystem   (core)     [tests]   │
│         └─ path-layout mapper (sha256→path, etc.)       │
└─────────────────────────────────────────────────────────┘
```

### Protocol surface

The protocol is intentionally thin — blob ops, manifest ops, checkpoint ops, and publish ops. All methods are `async` and `idempotent`.

```python
@runtime_checkable
class WorkspaceSyncBackend(Protocol):
    # -- blob operations (content-addressed) -------------------------------
    async def get_blob(self, sha256: str) -> bytes | None: ...
    async def put_blob(self, sha256: str, data: bytes) -> None: ...
    async def head_blob(self, sha256: str) -> bool: ...

    # -- manifest operations ----------------------------------------------
    async def get_manifest(self, run_id: str) -> Manifest | None: ...
    async def put_manifest(
        self, run_id: str, manifest: Manifest, *,
        if_match: str | None = None,
    ) -> Manifest: ...

    # -- checkpoint operations --------------------------------------------
    async def list_checkpoints(self, run_id: str) -> list[str]: ...
    async def get_checkpoint(self, checkpoint_id: str) -> bytes | None: ...
    async def put_checkpoint(
        self, checkpoint_id: str, data: bytes,
        manifest: Manifest | None = None,
    ) -> None: ...

    # -- publish operations -----------------------------------------------
    async def publish_artifact(
        self, artifact_path: str, data: bytes, *,
        content_type: str | None = None,
    ) -> Artifact: ...

    # -- optional streaming (default impls buffer fully) -------------------
    async def stream_blob(self, sha256: str) -> AsyncIterator[bytes]: ...
    async def stream_checkpoint(self, checkpoint_id: str) -> AsyncIterator[bytes]: ...
```

### Why not a full workspace protocol?

A full `Workspace` protocol (`materialize`, `checkpoint`, `publish`, `recover`, `close`) was considered and **rejected**. The workspace lifecycle logic (CAS, dirty tracking, debouncing) is the hard part and should not be reimplemented per backend. Making the manager a protocol would produce N implementations of the same algorithm. The protocol boundary is at the storage backend, not the manager.

### Backend implementation: `FsspecSyncBackend`

> **Decision (from fsspec review):** Replace the originally-planned `S3WorkspaceSyncBackend` (boto3/aioboto3), `LocalFsSyncBackend` (stdlib), and deferred `GcsWorkspaceSyncBackend` with a single `FsspecSyncBackend` adapter that works with any fsspec-supported filesystem.

| Backend | Package | fsspec extra | Use case |
|---------|---------|-------------|----------|
| `FsspecSyncBackend` | `soothe` (host) | `fsspec` (core) | Unified adapter — works with any fsspec filesystem |
| → S3/MinIO | via `s3fs` | `[s3]` | Production — S3-compatible stores |
| → GCS | via `gcsfs` | `[gcs]` | Google Cloud Storage (works out of the box) |
| → Azure Blob | via `adlfs` | `[azure]` | Azure Blob Storage |
| → Local FS | via `LocalFileSystem` | (core) | Dev/testing |
| → Memory | via `MemoryFileSystem` | (core) | Unit tests |

**Rationale:** One `FsspecSyncBackend` adapter (~200 lines) replaces all three planned backends. New backends require zero code — just an optional pip extra. The `fsspec` core is lightweight (~2 MB, zero transitive deps); backend-specific packages (`s3fs`, `gcsfs`, `adlfs`) are optional extras installed only when needed.

The `FsspecSyncBackend` translates each `WorkspaceSyncBackend` call into fsspec operations:

| Protocol method | fsspec operation |
|---|---|
| `get_blob(sha256)` | `fs.cat(blob_path(sha256))` → `None` if `FileNotFoundError` |
| `put_blob(sha256, data)` | `fs.pipe(blob_path(sha256), data)` (write-once; check `exists` first) |
| `head_blob(sha256)` | `fs.exists(blob_path(sha256))` |
| `get_manifest(run_id)` | `fs.cat(manifest_path(run_id))` → parse JSON |
| `put_manifest(run_id, manifest, if_match=...)` | `fs.pipe(manifest_path, ...)` + read-then-write guard (§6c) |
| `list_checkpoints(run_id)` | `fs.ls(checkpoint_dir(run_id))` |
| `get_checkpoint(id)` | `fs.cat(checkpoint_path(id))` |
| `put_checkpoint(id, data)` | `fs.pipe(checkpoint_path(id), data)` |
| `publish_artifact(path, data)` | `fs.pipe(artifact_path, data)` → construct `Artifact` |
| `stream_blob(sha256)` | `fs.open(blob_path, 'rb')` with chunked read |

### Credential isolation

The `WorkspaceSyncBackend` implementation holds the storage credentials (passed as fsspec `storage_options`). The Workspace Manager receives an already-constructed backend instance — it never sees credentials. The agent never sees either. This enforces Invariant 4 (§45: "the agent never directly accesses the storage backend").

---

## 6c. FsspecSyncBackend design

### Async I/O gap

fsspec is sync-first; `AsyncFileSystem` exists but coverage is incomplete across backends (e.g., `adlfs` has limited async support). All fsspec calls are wrapped in `asyncio.to_thread()`:

```python
async def get_blob(self, sha256: str) -> bytes | None:
    try:
        return await asyncio.to_thread(self._fs.cat, self._blob_path(sha256))
    except FileNotFoundError:
        return None
```

This is the same pattern that would have been needed for `boto3`. The performance characteristics are identical — both approaches offload sync I/O to a thread pool.

For backends where `AsyncFileSystem` is well-supported (notably `s3fs`), the async variant can be used directly as a future optimization.

### Optimistic concurrency (if_match)

`put_manifest(..., if_match=version)` requires conditional write semantics. S3 supports this natively via `If-Match` ETag preconditions. fsspec's generic interface has no conditional write.

**Mitigation:** Implement a read-then-write guard inside `FsspecSyncBackend`:

```python
async def put_manifest(self, run_id, manifest, *, if_match=None):
    existing = await self.get_manifest(run_id)
    if if_match is not None and existing and existing.version != if_match:
        raise ConcurrentModificationError(...)
    data = manifest.model_dump_json().encode()
    await asyncio.to_thread(self._fs.pipe, self._manifest_path(run_id), data)
    return manifest
```

**Caveat:** This is a race condition — between the read and the write, another worker could update the manifest. For S3 backends, a fast-path using S3 conditional writes via `s3fs` internals is available. For other backends without conditional writes (local FS, SFTP), the race window is acceptable because:

- Workspaces are owned by exactly one run (Invariant 3, §45).
- Concurrent manifest writes only happen during crash recovery, which is designed to anchor on the latest snapshot (§14a recovery algorithm).

### Content-addressed write-once semantics

Blobs are immutable (Invariant 1, §45). `put_blob` must be idempotent — writing the same hash twice is a no-op. fsspec's `pipe()` overwrites by default, so `exists()` is checked first:

```python
async def put_blob(self, sha256: str, data: bytes) -> None:
    path = self._blob_path(sha256)
    if await asyncio.to_thread(self._fs.exists, path):
        return  # idempotent — blob already stored
    await asyncio.to_thread(self._fs.pipe, path, data)
```

### Path-layout mapper

The protocol is content-addressed (`sha256`), but fsspec is path-based. The backend maps hashes to paths using the object-store layout (§22):

```python
def _blob_path(self, sha256: str) -> str:
    return f"{self._root}/blobs/sha256/{sha256[:2]}/{sha256}"

def _manifest_path(self, run_id: str) -> str:
    return f"{self._root}/runs/{run_id}/manifest.json"

def _checkpoint_path(self, checkpoint_id: str) -> str:
    return f"{self._root}/runs/{checkpoint_id.rsplit('-', 1)[0]}/checkpoints/{checkpoint_id}.json"

def _artifact_path(self, artifact_path: str) -> str:
    return f"{self._root}/artifacts/{artifact_path}"
```

### Streaming support

fsspec supports chunked reads via `cat_file(..., start=, end=)` and `open(path, 'rb')` with iteration:

```python
async def stream_blob(self, sha256: str) -> AsyncIterator[bytes]:
    path = self._blob_path(sha256)
    f = await asyncio.to_thread(self._fs.open, path, "rb")
    try:
        while chunk := await asyncio.to_thread(f.read, 8192):
            yield chunk
    finally:
        await asyncio.to_thread(f.close)
```

### URI factory

The `construct_sync_backend(uri, config)` factory becomes trivially generic with fsspec:

```python
def construct_sync_backend(uri: str, config) -> WorkspaceSyncBackend:
    fs, root = fsspec.url_to_fs(uri, **_resolve_storage_options(uri, config))
    return FsspecSyncBackend(fs=fs, root=root)

# s3://bucket/prefix  → s3.S3FileSystem
# gs://bucket/prefix  → gcs.GCSFileSystem
# az://container/pfx  → adl.AzureBlobFileSystem
# file:///path/to/dir → LocalFileSystem
# memory://test       → MemoryFileSystem
```

This eliminates per-scheme `if/elif` dispatch and makes the system work with any fsspec-supported backend with zero code changes.

---

## 7. Manifest

The manifest is the synchronization contract.

```json
{
  "run_id": "run-123",
  "version": 7,
  "resources": [
    { "path": "input/paper.pdf", "sha256": "abc123...", "size": 18273491 },
    { "path": "input/notes.md",  "sha256": "def456...", "size": 8421 }
  ],
  "artifacts": [],
  "checkpoint_id": "c003"
}
```

The runtime first retrieves the manifest. It does **not** download all resources.

Fields:
- `run_id` — unique run identifier
- `version` — optimistic concurrency counter (see §37)
- `resources` — expected input resources (list of `ManifestEntry`)
- `artifacts` — expected output artifacts (list of `ManifestEntry`)
- `checkpoint_id` — which checkpoint this manifest represents, if any

---

## 8. Content-addressed storage

Use a local CAS cache:

```text
/agent-cache/
└── blobs/
    └── sha256/
        ├── ab/
        │   └── abcdef...
        ├── de/
        │   └── def456...
        └── ...
```

The cache key is `sha256(content)`. The same resource used by 1,000 runs therefore requires only one local copy.

---

## 9. Incremental materialization

Materialization algorithm:

```text
1. Fetch manifest.
2. For every resource:
   3. Check local workspace state.
   4. Check local CAS.
   5. If CAS contains hash: materialize locally (reflink/hardlink).
   6. Otherwise:
        download from the storage backend.
        verify SHA-256.
        store in CAS.
        materialize locally.
```

The common case becomes:

```text
storage backend → manifest only → Local CAS → hardlink/reflink → Workspace
```

Therefore: **repeated materialization of an unchanged resource requires zero object-data bandwidth.**

---

## 10. Hardlink / reflink strategy

Do not copy cached files unnecessarily. Preferred order: `reflink → hardlink → copy`.

Reflink is preferred when supported because it provides copy-on-write semantics:

```text
CAS blob → reflink → workspace/input/paper.pdf
```

If the agent modifies the file, the filesystem handles copy-on-write behavior.

> **Cross-filesystem caveat:** reflink (`FICLONE`) and hardlinks require source and destination on the same filesystem. If the CAS cache and the workspace root are on different volumes, the implementation MUST fall back to copy. The fallback chain is probed once at workspace open and cached for the run.

---

## 11. Lazy materialization (deferred — not in MVP)

Lazy materialization is an optional optimization: instead of downloading all resources up front, materialize only when accessed.

```text
open("paper3.pdf") → resource resolver → CAS lookup → download if missing → local file
```

This should be a **later** optimization because filesystem interception adds complexity. The default implementation uses eager materialization with CAS caching. (See non-goals, §47.)

---

## 12. Dirty tracking

The agent performs frequent incremental writes. The runtime tracks dirty files instead of rescanning the entire workspace.

### 12.1 Strategy: hybrid platform-adaptive watcher

The dirty tracker uses a **thin hybrid abstraction** that selects a native OS watcher when available and falls back to stat-scan polling otherwise. No third-party watcher library (e.g. `watchdog`) is introduced — the wrapper is ~200 lines of stdlib code.

| Platform | Primary backend | Fallback |
|----------|-----------------|----------|
| **Linux** | `inotify` (via `ctypes` or `os.scandir` diff) | stat-scan polling |
| **macOS** | `FSEvents` (via `ctypes` / CoreServices) | stat-scan polling |
| **Windows** | `ReadDirectoryChangesW` (via `pywin32` if installed) | stat-scan polling |

### 12.2 Event model

Events: `CREATE`, `MODIFY`, `DELETE`, `MOVE`.

```python
class FileEvent(BaseModel):
    kind: Literal["create", "modify", "delete", "move"]
    mtime: float
    size: int
```

### 12.3 Dirty state

The tracker maintains two structures:

```text
dirty_files = {
    "output/report.md":      FileEvent(kind="modify", mtime=..., size=...),
    "output/references.bib": FileEvent(kind="modify", mtime=..., size=...),
}
deleted_files = {
    "working/tmp/draft.md",   # recorded as deletion → checkpoint removes from manifest
}
```

**Deduplication:** multiple events on the same file within the debounce window collapse to one `FileEvent` (latest state wins).

**Delete tracking:** deletions are recorded separately from modifications so the checkpoint knows to remove entries from the remote manifest.

### 12.4 Exclusions

The watcher ignores the `.workspace/` directory (runtime-owned, not agent-written). Only `input/`, `working/`, and `output/` are observed.

### 12.5 Graceful degradation

If a native watcher fails to initialize (e.g. permission denied, resource limit), the tracker falls back to stat-scan polling with a configurable interval. A warning is logged. The poll interval MUST be ≤ the debounce window (§13) to avoid starving the checkpoint cycle.

Only dirty files are considered during checkpointing.

---

## 13. Debounced persistence

Do not upload immediately after each filesystem event.

Example policy:

```text
debounce window:     5 seconds
maximum checkpoint:  60 seconds
```

Sequence:

```text
agent writes report.md → dirty
agent writes report.md again → dirty
agent writes report.md again → dirty
5 seconds without change → checkpoint
```

Maximum checkpoint interval guarantees that continuously active agents still produce durable state.

> **Debounce vs. poll interval:** when the dirty tracker falls back to stat-scan polling (§12.5), the poll interval MUST be ≤ the debounce window. Otherwise the tracker never observes changes within the debounce window, starving the checkpoint cycle. Default poll interval: 2s (≤ 5s debounce).

---

## 14. Checkpoint vs publish

These are separate concepts.

### Checkpoint

Used for: crash recovery, resumability, long-running research, worker failure recovery. Checkpoint data may be internal.

### Publish

Used for: user-visible reports, final artifacts, completed research output.

```text
run-123/
├── checkpoints/
│   ├── c001
│   ├── c002
│   └── c003
└── artifacts/
    ├── report.md
    └── references.bib
```

A checkpoint does not automatically become a published artifact.

> **Disambiguation from RFC-803:** "checkpoint" here refers to **workspace artifact state** (which files are dirty, their content hashes, the manifest version) — a workspace-layer concept. RFC-803's "checkpoint" refers to **StrangeLoop loop-execution state** (the LangGraph/StrangeLoop execution graph). The two are at different layers and must not share storage or semantics. A workspace checkpoint is referenced *by* a StrangeLoop checkpoint when a loop owns a workspace run, but they remain distinct records.

---

## 14a. Checkpoint payload format (snapshot + delta)

A checkpoint is a serialized `CheckpointPayload` (defined in `soothe_sdk.protocols`). The payload is self-describing: it carries a `kind` discriminator (`SNAPSHOT` or `DELTA`) so the recovery path knows how to apply it.

### Payload model

```python
class CheckpointType(StrEnum):
    SNAPSHOT = "snapshot"
    DELTA = "delta"

class CheckpointPayload(BaseModel):
    checkpoint_id: str                         # e.g. "c001"
    kind: CheckpointType                       # snapshot or delta
    manifest_version: int                     # manifest version this checkpoint applies to
    dirty_files: list[ManifestEntry]           # files changed since last checkpoint
    manifest_snapshot: Manifest | None = None # embedded full manifest (SNAPSHOT only)
    parent_checkpoint_id: str | None = None    # previous checkpoint (DELTA only)

    def is_snapshot(self) -> bool: ...
```

### Encoding rules

| Checkpoint # | `kind` | `dirty_files` | `manifest_snapshot` | `parent_checkpoint_id` |
|---|---|---|---|---|
| c001 (first) | `SNAPSHOT` | all dirty files at run start | full `Manifest` | `None` |
| c002 | `DELTA` | only files changed since c001 | `None` | `"c001"` |
| c003 | `DELTA` | only files changed since c002 | `None` | `"c002"` |
| c014 (compaction) | `SNAPSHOT` | all dirty files since c001 | full `Manifest` (latest) | `None` |
| c015 | `DELTA` | only files changed since c014 | `None` | `"c014"` |

### Why snapshot + delta

- **Full-snapshot-only** (Option A): trivially correct and idempotent, but re-uploads the entire manifest + dirty set every checkpoint. For a 500-entry manifest checkpointed every 60s over a 4-hour run, that's ~240 redundant uploads.
- **Delta-only** (Option B): minimal bandwidth, but recovery requires strict ordering, tombstone tracking for deletes, and gap-filling when a delta is lost. A single corrupted checkpoint invalidates the entire chain.
- **Snapshot + delta** (Option C, chosen): the first checkpoint and periodic compactions are self-contained `SNAPSHOT`s; intermediate checkpoints are compact `DELTA`s referencing their parent. Recovery anchors on the nearest preceding snapshot and replays deltas forward. A lost delta degrades gracefully — fall back to the last snapshot and restart from there.

### Compaction trigger

When the cumulative delta chain exceeds a threshold (default: delta count > 10, or cumulative `dirty_files` entries > 500), the Workspace Manager writes a new `SNAPSHOT` and resets the delta chain. This bounds recovery replay cost.

### Recovery algorithm

```text
1. list_checkpoints(run_id) → [c001, c002, ..., c015]
2. find the latest SNAPSHOT (scan backward for kind == SNAPSHOT)
3. deserialize SNAPSHOT → restore manifest_snapshot + dirty_files
4. for each subsequent DELTA in order:
       apply dirty_files to the workspace state
5. materialize from CAS using the final manifest
6. resume agent
```

### Wire format

`CheckpointPayload` serializes to JSON (or msgpack for compactness). The `put_checkpoint(data: bytes, ...)` protocol method accepts the serialized payload as opaque bytes — the backend stores it as-is and returns it on `get_checkpoint`. The Workspace Manager owns serialization/deserialization.

---

## 15. Incremental persistence

When a dirty file is checkpointed:

```text
dirty file → stat → content hash → CAS lookup
```

If the hash already exists: do not upload.
If it does not: upload blob.
Then update the manifest.

This makes uploads content-addressed and idempotent.

---

## 16. Large mutable files (deferred — not in MVP)

File-level CAS is sufficient for immutable resources. For large frequently modified files, use chunking. Default chunk size: `8 MiB`.

A file becomes:

```text
file
 ├── chunk A
 ├── chunk B
 ├── chunk C
 ├── chunk D
 └── chunk E
```

Manifest:

```json
{
  "size": 41943040,
  "chunk_size": 8388608,
  "chunks": ["sha256:A", "sha256:B", "sha256:C", "sha256:D", "sha256:E"]
}
```

If the new version is `A B X D E`, only `X` is transferred.

---

## 17. Fixed chunking first (deferred — not in MVP)

Use fixed-size chunks initially. Recommended: `8 MiB` default. Possible future optimization: `FastCDC` / content-defined chunking. Content-defined chunking is useful when bytes are inserted in the middle of large files because chunk boundaries remain more stable. It is not necessary for the initial implementation.

---

## 18. Text files and agent diff writing (deferred — not in MVP)

Research agents predominantly modify: Markdown, JSON, YAML, BibTeX, text, source code. These files are especially suitable for diff persistence.

For a large Markdown document:

```text
version 1 → patch 1 → patch 2 → patch 3
```

Rather than repeatedly uploading the entire document. Recommended architecture: `snapshot + patches` (not patches only). Periodic compaction creates a new snapshot.

```text
snapshot-v1 + patch-001 + patch-002 + patch-003 → snapshot-v2
```

---

## 19. Compression

For text patches: `diff → zstd → storage backend`.

For already-compressed data (PDF, JPEG, PNG, ZIP, Parquet), do not expect meaningful compression gains. The transfer pipeline should be content-type aware.

---

## 20. Avoid full-file hashing on every write

Do not calculate SHA-256 after every write. Instead:

```text
filesystem event → mark dirty → debounce → checkpoint → hash once
```

Cheap state (`mtime`, `size`, `inode`) is used for event/state tracking. SHA-256 is calculated only when persistence is required.

> **Watcher → state DB relationship:** the hybrid watcher (§12) populates `FileEvent` entries (`mtime`, `size`) into the in-memory dirty set. At checkpoint time, the Workspace Manager reads the dirty set, computes SHA-256 once per dirty file, and writes the resulting `ManifestEntry` into the `files` table of `state.db` (§21). The watcher never computes hashes; the state DB never watches the filesystem. This keeps the hot path cheap and the expensive path (hashing) batched.

---

## 21. Workspace state database

Each workspace has a small **state database** that tracks dirty files, blob cache index, and checkpoint *references* (not checkpoint payloads). The database backend follows the daemon's unified `persistence.default_backend` selection (AGENTS.md §10):

| `default_backend` | State DB | Location |
|--------------------|----------|----------|
| `sqlite` | SQLite file | `.workspace/state.db` (workspace-local) |
| `postgresql` | PostgreSQL tables in `soothe_metadata` DB | `workspace_state_*` tables (shared pool) |

### Dual-backend rationale

The state DB is a **runtime cache**, not a daemon durable store — only the *referenced* blobs and manifests (in the object store) are durable. However, AGENTS.md §10 mandates that all process-owned stores follow `persistence.default_backend` as a single mode. The workspace state DB is process-owned (created by the Workspace Manager running inside the host), so it must branch on the same setting rather than hardcode SQLite.

This mirrors the existing pattern used by:
- Cron store (`store_factory.py` → `CronJobStore` / `PostgresCronJobStore`)
- Display card store (`display_store.py` / `display_store_postgres.py`)
- StrangeLoop checkpoint backend (`SQLitePersistenceBackend` / `PostgreSQLPersistenceBackend`)

### Backend factory

```python
from soothe.persistence.workspace_state_factory import create_workspace_state_store

state_store = create_workspace_state_store(config, run_id)
# sqlite  → WorkspaceStateSqlite(db_path=workspace_dir / ".workspace" / "state.db")
# postgres → WorkspaceStatePostgres(dsn=config.resolve_postgres_dsn_for_database("metadata"),
#                                   run_id=run_id)
```

### `WorkspaceStateStore` protocol

```python
@runtime_checkable
class WorkspaceStateStore(Protocol):
    """Async interface for workspace-local state (files, blobs, checkpoints, artifacts)."""

    async def upsert_file(self, path: str, *, size: int, mtime: float,
                          inode: int | None, sha256: str | None,
                          status: str) -> None: ...
    async def get_file(self, path: str) -> dict | None: ...
    async def list_dirty_files(self) -> list[dict]: ...
    async def clear_dirty(self) -> None: ...

    async def upsert_blob(self, sha256: str, *, size: int,
                          local_path: str, last_used: float) -> None: ...
    async def get_blob(self, sha256: str) -> dict | None: ...

    async def insert_checkpoint(self, checkpoint_id: str, *,
                                manifest_hash: str, status: str) -> None: ...
    async def list_pending_checkpoints(self) -> list[dict]: ...
    async def update_checkpoint_status(self, checkpoint_id: str,
                                        status: str) -> None: ...

    async def upsert_artifact(self, path: str, *, sha256: str,
                              published_uri: str | None,
                              status: str) -> None: ...
```

### Tables (SQLite schema, mirrored in PostgreSQL)

#### files
```text
path | size | mtime | inode | sha256 | status
```

#### blobs
```text
sha256 | size | local_path | last_used
```

#### checkpoints
```text
id | timestamp | manifest_hash | status
```

#### artifacts
```text
path | sha256 | published_uri | status
```

Both backends provide fast local state lookup without repeatedly scanning the workspace.

### PostgreSQL schema details

When running in PostgreSQL mode, the workspace state tables live in the `soothe_metadata` database (the same database used by cron and display card stores). Tables are namespaced per-run:

```sql
-- All workspace state tables are prefixed with ws_ and partitioned by run_id
CREATE TABLE IF NOT EXISTS ws_files (
    run_id    TEXT NOT NULL,
    path      TEXT NOT NULL,
    size      BIGINT,
    mtime     DOUBLE PRECISION,
    inode     BIGINT,
    sha256    TEXT,
    status    TEXT NOT NULL DEFAULT 'clean',
    PRIMARY KEY (run_id, path)
);

CREATE TABLE IF NOT EXISTS ws_blobs (
    run_id     TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    size       BIGINT,
    local_path TEXT,
    last_used  DOUBLE PRECISION,
    PRIMARY KEY (run_id, sha256)
);

CREATE TABLE IF NOT EXISTS ws_checkpoints (
    run_id        TEXT NOT NULL,
    id            TEXT NOT NULL,
    timestamp     DOUBLE PRECISION NOT NULL,
    manifest_hash TEXT,
    status        TEXT NOT NULL DEFAULT 'pending_upload',
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS ws_artifacts (
    run_id        TEXT NOT NULL,
    path          TEXT NOT NULL,
    sha256        TEXT,
    published_uri TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (run_id, path)
);

CREATE INDEX IF NOT EXISTS idx_ws_checkpoints_status
    ON ws_checkpoints (run_id, status);
```

The `run_id` column allows multiple concurrent workspace runs to share the same PostgreSQL database without interference. Cleanup on workspace close deletes all rows for that `run_id`.

---

## 22. Object-store layout

> **Backend note:** The physical layout below is the `FsspecSyncBackend` implementation's concern. It works identically across S3, GCS, Azure, and local FS because fsspec abstracts the path operations.

Recommended object layout:

```text
agent/
├── blobs/
│   └── sha256/
│       ├── ab/
│       │   └── abcdef...
│       └── ...
│
├── resources/
│   └── <resource-id>/
│       ├── manifest.json
│       └── versions/
│           ├── 1.json
│           └── 2.json
│
├── runs/
│   └── <run-id>/
│       ├── manifest.json
│       ├── checkpoints/
│       │   ├── c001.json
│       │   └── c002.json
│       └── artifacts/
│           ├── report.md
│           └── references.bib
```

Blobs are immutable. Manifests are versioned. This provides safe deduplication.

---

## 23. Content-addressed blob lifecycle

```text
content → SHA256 → blob hash
                            │
              ┌─────────────┴─────────────┐
              │                           │
          local CAS                     object store
              │                           │
              └─────────────┬─────────────┘
                            │
                    multiple references
```

A blob is immutable and can safely be shared between runs.

---

## 24. Global deduplication

Suppose 100 runs use the same 50 MB PDF.

Without CAS: `100 × 50 MB = 5 GB`.
With CAS: `1 × 50 MB = 50 MB`.

The 100 manifests simply reference the same content hash. This provides both bandwidth savings and storage savings.

---

## 25. Agent lifecycle

```text
CREATE RUN
    │
    ▼
LOAD MANIFEST
    │
    ▼
CHECK LOCAL CACHE
    │
    ├── HIT ──────────────┐
    │                     │
    └── MISS              │
         │                │
      DOWNLOAD            │
         │                │
      VERIFY HASH         │
         │                │
      STORE CAS           │
         │                │
         └───────┬────────┘
                 ▼
          MATERIALIZE FS
                 │
                 ▼
           START AGENT
                 │
                 ▼
          AGENT WORKS
                 │
            FS EVENTS
                 │
                 ▼
          DIRTY TRACKER
                 │
                 ▼
             CHECKPOINT
                 │
                 ▼
               CAS
                 │
                 ▼
          storage backend
                 │
                 ▼
            AGENT FINISH
                 │
                 ▼
             PUBLISH
                 │
                 ▼
          storage backend
                 │
                 ▼
             CLEANUP
```

---

## 26. Crash recovery

If the worker dies:

```text
worker A
   │
   ├── checkpoint 1
   ├── checkpoint 2
   └── crash
```

A new worker:

```text
worker B
   │
   ▼
load latest checkpoint
   │
   ▼
materialize from CAS
   │
   ▼
resume agent
```

No need to reconstruct the entire original upload.

---

## 27. Idempotency

All operations should be idempotent.

- **Materialization:** `if local hash == expected hash: skip`
- **Blob upload:** `if blob exists: skip`
- **Checkpoint:** `if manifest hash already exists: skip`
- **Publish:** `if artifact hash already published: skip`

This makes retries safe.

---

## 28. Concurrency

Multiple runs may execute simultaneously. Never allow two runs to mutate the same workspace.

Use: `/workspaces/<run-id>` (isolated) and shared `/agent-cache`.

The CAS is immutable, so concurrent reads are safe. Use atomic rename for newly created blobs:

```text
temporary blob → fsync → atomic rename → final hash path
```

---

## 29. Cache eviction

The local CAS can grow indefinitely. Use an LRU or size-based policy with grace-period protection.

```text
cache capacity:       500 GB
high watermark:       450 GB
low watermark:        400 GB
eviction_grace_secs:  600 (10 min)
```

When high watermark is reached:

```text
1. Identify blobs with reference_count == 0 AND last_unref_timestamp < now - grace_period
2. Evict least-recently-used among those
3. Stop when at low watermark
```

Never evict blobs currently referenced by active workspaces.

---

## 30. Reference tracking

Maintain:

```text
active_workspace → set[blob_hash]
blob → reference_count (atomic counter)
blob → last_unref_timestamp (set when ref_count drops to 0)
```

A blob is evictable only when:

```text
reference_count == 0 AND (now - last_unref_timestamp) >= eviction_grace_secs
```

**Rationale (10-minute grace period):** The grace period captures cross-run reuse. Run A materializes a 50 MB PDF, closes its workspace (`ref_count → 0`). If Run B starts within 10 minutes and needs the same PDF, it's a cache hit — zero bandwidth. Without a grace period, Run B would suffer a cache miss and re-download.

**Reference lifecycle:**
- **Increment:** On materialize (hardlink/reflink from CAS to workspace).
- **Decrement:** On workspace close (not on file deletion — the blob may be re-materialized during recovery).
- **Grace clock:** Starts when `reference_count` transitions from 1 → 0.
- **Evictable:** Only after grace period expires AND high watermark triggers.

This prevents deleting a resource while a future run might benefit from it.

---

## 31. Network optimization

Network transfers should use: concurrent downloads, concurrent uploads, bounded worker pools, streaming I/O, HTTP connection reuse, multipart transfers for large blobs, compression for text patches, hash-based deduplication. Do not create one network connection per file.

Use a bounded pool, for example:

```text
download workers: 4–16
upload workers:   4–16
```

depending on network and storage-backend capacity.

---

## 32. Backpressure

The agent should never be blocked by a slow storage-backend checkpoint.

Bad:

```text
agent → checkpoint → wait for network → continue
```

Prefer:

```text
agent → local checkpoint queue → continue
                                       │
                                       └────► background uploader
```

The local checkpoint becomes durable on local disk first. The uploader asynchronously persists it to the storage backend.

> **Local durability mechanism (dual-backend):** The checkpoint payload is written to the workspace `WorkspaceStateStore` (§21) with `status='pending_upload'`. This is the same state store that tracks dirty files and blob cache — whether it's a SQLite file (`.workspace/state.db`) or PostgreSQL tables (`ws_checkpoints` in `soothe_metadata`), the checkpoint is durably recorded before the background uploader attempts the remote push. The uploader queries `list_pending_checkpoints()` (FIFO order), uploads blobs first, then the manifest, and finally calls `update_checkpoint_status(id, 'uploaded')`. If the process crashes, recovery scans for `status='pending_upload'` rows and re-attempts. This follows the same pattern as the StrangeLoop async checkpoint worker (RFC-803) and the cron store's pending-job queue.

---

## 33. Durability levels

Introduce configurable persistence levels:

| Level | Behavior |
|-------|----------|
| **Memory** | No checkpoint |
| **Local** | Checkpoint to local disk only |
| **Remote** | Checkpoint asynchronously to storage backend |
| **Published** | Artifact explicitly committed as user-visible durable output |

Example progression: `LOCAL → REMOTE → PUBLISHED`.

Not every intermediate state deserves the same durability cost.

---

## 34. Artifact publication

Agent output should be explicitly declared.

```json
{
  "artifacts": [
    { "path": "output/report.md", "type": "report", "publish": true },
    { "path": "working/chunks/", "publish": false }
  ]
}
```

Default: `output/ → publish`, `working/ → ephemeral`, unless explicitly configured otherwise.

---

## 35. Security

The workspace must be isolated per run.

Requirements:

- unique workspace ID
- no cross-run writable paths
- controlled filesystem permissions
- object-store credentials unavailable to the agent
- object-store credentials held only by Workspace Manager
- path traversal protection
- symlink policy
- resource size limits
- disk quotas
- cleanup after completion

The agent should never receive `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`, AWS credentials, or equivalent storage credentials.

> **Relationship to RFC-102:** path traversal protection, workspace boundary enforcement, and file-type restrictions are already specified by RFC-102's `SecureFilesystemBackend` and `SecurityConfig`. The Workspace Manager should **compose** `SecureFilesystemBackend` for the agent-facing filesystem boundary rather than reimplement path validation. The `.workspace/` directory is enforced as off-limits via the existing path blacklist mechanism.

---

## 36. Failure cases

| Failure | Recovery |
|---------|----------|
| Download interrupted | Resume multipart transfer if supported |
| Hash mismatch | Delete temporary object and retry |
| Storage backend unavailable during checkpoint | Keep local checkpoint. Retry asynchronously. |
| Worker crash | Resume from latest remote checkpoint |
| Disk full | Pause agent and trigger cache eviction or fail cleanly |
| Corrupted CAS blob | Verify checksum and redownload |
| Manifest conflict | Use optimistic versioning (§37) |

---

## 37. Optimistic manifest versioning

Each manifest has a `version`. When committing: `read version N → write version N+1` using conditional object update semantics where available (S3 `If-Match` / ETag precondition). This prevents stale workers from overwriting newer state.

> **fsspec note:** For S3 backends, the `FsspecSyncBackend` can use `s3fs` internals to access native S3 conditional writes as a fast-path. For other backends without conditional writes, the read-then-write guard (§6c) is used. The race window is acceptable because workspaces are owned by exactly one run (Invariant 3).

---

## 38. Why not continuous object-store ↔ FS sync?

Avoid `ObjectStore ←→ FS` as a continuously synchronized filesystem. It introduces: conflict resolution, event loops, object-store latency, excessive network traffic, temporary-file pollution, ambiguous ownership, difficult crash semantics.

Instead:

```text
object store → materialize → FS is authoritative → checkpoint → object store
```

The workspace behaves like a transaction.

---

## 39. Recommended API

The agent runtime should expose a concrete `Workspace` class (in `soothe` host). It receives a `WorkspaceSyncBackend` instance via dependency injection. The data models (`Resource`, `Manifest`, `ArtifactSpec`, `Artifact`) are imported from `soothe-sdk`.

```python
from soothe_sdk.protocols import (
    Resource, Manifest, ArtifactSpec, Artifact, WorkspaceSyncBackend,
)

class Workspace:
    root: Path
    _backend: WorkspaceSyncBackend  # injected

    async def materialize(self, resources: list[Resource]) -> None: ...
    async def checkpoint(self) -> Checkpoint: ...
    async def publish(self, artifacts: list[ArtifactSpec]) -> list[Artifact]: ...
    async def recover(self, checkpoint_id: str) -> None: ...
    async def close(self) -> None: ...
```

The agent itself only needs `workspace.root`. The `WorkspaceSyncBackend` protocol and all data models are defined in `soothe-sdk` (§6b), enabling CLI/SDK consumers to construct `Resource`/`ArtifactSpec` objects without importing host code.

---

## 40. Resource API (SDK contract)

Defined as a Pydantic `BaseModel` in `soothe_sdk.protocols`:

```python
class Resource(BaseModel):
    id: str                          # stable resource identifier
    path: str                        # relative workspace path
    size: int                        # bytes
    sha256: str                      # content hash (canonical identity)
    content_type: str | None = None  # MIME hint, optional

    @staticmethod
    def compute_sha256(data: bytes) -> str: ...
```

> **No `uri` field.** The model is purely content-addressed. Physical location is a backend concern.

Example:

```python
Resource(
    id="res-123",
    path="input/paper.pdf",
    size=18_273_491,
    sha256="abc123...",
    content_type="application/pdf",
)
```

---

## 41. Artifact API (SDK contract)

```python
class ArtifactSpec(BaseModel):
    path: str
    content_type: str | None = None
    publish: bool = True

class Artifact(BaseModel):
    path: str
    sha256: str
    size: int
    published_uri: str | None = None  # filled by backend on publish
    content_type: str | None = None
```

`Artifact` keeps `published_uri` because the *consumer* of a published artifact needs to know where to fetch it. `Resource` does not carry a `uri` because the *consumer* is the Workspace Manager, which already knows the backend.

Example:

```python
ArtifactSpec(
    path="output/report.md",
    content_type="text/markdown",
)
```

---

## 42. Recommended implementation phases

### Phase 1 — MVP

```text
Workspace Manager
FsspecSyncBackend (fsspec core + s3fs for S3)
manifest
local CAS
SHA-256
hardlink/reflink (+ copy fallback)
dirty tracking (hybrid: inotify + FSEvents + stat-scan fallback)
checkpoint
publish
```

Do **not** implement chunking, lazy materialization, or patch journals yet. This provides most of the value.

### Phase 2 — Performance

```text
background uploader
debounced checkpointing
parallel transfer
zstd text compression
LRU cache
WorkspaceStateStore (dual-backend: SQLite + PostgreSQL, follows persistence.default_backend)
```

### Phase 3 — Large file optimization

```text
8 MiB chunking
chunk manifest
incremental chunk upload/download
multipart transfer
```

### Phase 4 — Advanced optimization (optional, demand-driven)

```text
content-defined chunking
lazy materialization
patch journals
semantic document blocks
remote CAS
```

---

## 43. Recommended default configuration

```yaml
workspace:
  root: $SOOTHE_HOME/data/workspaces   # follows RFC-621 daemon-generated convention
  state_backend: default               # "default" follows persistence.default_backend; or "sqlite"/"postgresql" to override

sync:
  backend: fsspec                      # unified adapter — works with any fsspec filesystem
  fsspec:
    # backend-specific storage_options are resolved from the URI scheme
    # e.g., s3:// → {endpoint_url, key, secret, ...} from env or config

cache:
  root: /agent-cache
  max_size: 500GB
  high_watermark: 450GB
  low_watermark: 400GB
  eviction_policy: lru
  eviction_grace_seconds: 600   # 10 min — blobs with 0 refs are evictable only after this delay

materialization:
  strategy: cas
  link_mode: reflink
  fallback: hardlink
  fallback_copy: true

checkpoint:
  enabled: true
  debounce_seconds: 5
  max_interval_seconds: 60
  background_upload: true

hash:
  algorithm: sha256

chunking:
  enabled: false
  chunk_size: 8MiB

compression:
  text:
    enabled: true
    algorithm: zstd

network:
  download_workers: 8
  upload_workers: 8

publication:
  default_output_directory: output
```

---

## 44. Key performance characteristics

| Scenario | Cost |
|----------|------|
| **Reused immutable resource** | Manifest ~KB; object data 0 bytes; local work hardlink/reflink |
| **New small Markdown artifact** | hash → zstd → single small upload |
| **Modified large binary** (Phase 3) | chunk hashes → identify changed chunks → upload changed chunks only |
| **Frequently edited Markdown** (Phase 4) | dirty tracking → debounce → diff → zstd → background checkpoint |
| **Agent continuously writing** | agent continues working while persistence happens asynchronously |

---

## 45. Core invariants

1. Every persisted blob is immutable.
2. Every blob is identified by its cryptographic content hash.
3. A workspace is owned by exactly one run.
4. The agent never directly accesses the storage backend (only the `WorkspaceSyncBackend` implementation holds credentials).
5. Local writes never require synchronous network access.
6. Every remote checkpoint references a complete manifest.
7. Published artifacts are immutable versions.
8. A failed upload can always be retried safely.
9. The storage backend is pluggable — the Workspace Manager algorithm is backend-agnostic (only talks to `WorkspaceSyncBackend`).

---

## 46. Final architecture

```text
                              USER
                                │
                                │ upload
                                ▼
                         ┌─────────────────┐
                         │ S3/GCS/Azure/   │
                         │ Local/Memory    │
                         │                 │
                         │ resources       │
                         │ CAS blobs       │
                         │ manifests       │
                         └────────┬────────┘
                                │
                         manifest lookup
                                │
                                ▼
              ┌──────────────────────────────────┐
              │  WorkspaceSyncBackend (protocol) │  ← soothe-sdk
              └──────────────────┬───────────────┘
                                 │ (injected)
                                 ▼
                    ┌──────────────────────┐
                    │   Workspace Manager  │  ← soothe (host)
                    └──────────┬───────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
             ┌──────────────┐      ┌─────────────────────┐
             │ Local CAS    │      │ WorkspaceStateStore  │
             │ SHA256 blobs │      │ (SQLite | PostgreSQL)│
             └──────┬───────┘      └─────────┬───────────┘
                    │                     │
                    └──────────┬──────────┘
                               │
                       reflink/hardlink
                               │
                               ▼
                   ┌────────────────────────┐
                   │     Agent Workspace    │
                   │                        │
                   │ input/                 │
                   │ working/               │
                   │ output/                │
                   └────────────┬───────────┘
                                │
                    filesystem-native agent
                                │
                         filesystem writes
                                │
                                ▼
                         Dirty Tracker
                                │
                         debounce / queue
                                │
                                ▼
                     Background Checkpointer
                                │
                        hash / diff / CAS
                                │
                                ▼
                      WorkspaceSyncBackend
                                │
                           final publish
                                │
                                ▼
                         Durable Artifacts
```

The fundamental abstraction is:

```text
                ┌─────────────────────┐
                │      Resource       │
                │ logical input       │
                └──────────┬──────────┘
                           │
                     materialize
                           │
                           ▼
                ┌─────────────────────┐
                │      Workspace      │
                │ mutable FS state    │
                └──────────┬──────────┘
                           │
                       checkpoint
                           │
                           ▼
                ┌─────────────────────┐
                │       Artifact      │
                │ durable CAS state   │
                └─────────────────────┘
```

**In short:** The object store (S3/GCS/Azure/local) is the durable content-addressed store. The local filesystem is the agent's transaction workspace. The `WorkspaceSyncBackend` protocol (in `soothe-sdk`) abstracts the storage backend; the Workspace Manager (concrete, in `soothe`) bridges the two using manifests, CAS, dirty tracking, asynchronous checkpoints, and incremental persistence — all backend-agnostic. The `FsspecSyncBackend` (in `soothe`) provides unified multi-backend transport via fsspec.

This architecture keeps filesystem-native agents completely filesystem-native while minimizing both **network bandwidth and filesystem copying**, and it leaves room for chunk-level deduplication and lazy materialization when large-scale workloads require them.

---

## 47. Non-goals

- **Agent identity.** This design does not define which agent consumes the workspace; a separate filesystem-native research agent RFC would reference this workspace subsystem.
- **Continuous bidirectional sync.** Materialization is one-way (store → FS); persistence is one-way (FS → store). No live conflict resolution.
- **Lazy materialization in MVP.** Eager materialization with CAS caching is the MVP; lazy/on-access materialization is Phase 4.
- **Chunking in MVP.** File-level CAS is sufficient for the initial implementation; chunking is Phase 3.
- **Patch journals in MVP.** Snapshot+patch persistence for text is Phase 4.
- **Replacing the StrangeLoop checkpoint system (RFC-803).** Workspace checkpoints are a distinct, lower-layer concept (artifact/file state), not a replacement for loop-execution checkpoints.

---

## 48. Relationship to existing Soothe architecture

This design touches several existing subsystems. Reconciliation summary:

| Existing RFC | Relationship |
|--------------|--------------|
| **RFC-619** (`deep_research`) | Out of scope. This workspace subsystem serves a **filesystem-native** agent (a separate concern); `deep_research` is web-only and does not use this workspace. |
| **RFC-621** (Workspace Host Convention) | Workspace placement follows the daemon-generated convention: `$SOOTHE_HOME/data/workspaces/<run-id>/`, distinct from the Docker volume mount at `$SOOTHE_HOME/workspaces/`. Container path translation applies to the agent-facing root. |
| **RFC-102** (Security Filesystem Policy) | Path traversal protection, workspace boundary enforcement, and `.workspace/` hiding compose the existing `SecureFilesystemBackend` rather than reimplementing it. |
| **RFC-801 / RFC-802** (Persistence Architecture) | The workspace `WorkspaceStateStore` follows `persistence.default_backend` — SQLite in SQLite mode, PostgreSQL tables (`ws_files`, `ws_blobs`, `ws_checkpoints`, `ws_artifacts` in `soothe_metadata`) in PostgreSQL mode. This is a **process-owned durable store** (not ephemeral). The factory pattern mirrors `create_cron_job_store()` and the StrangeLoop `SQLitePersistenceBackend`/`PostgreSQLPersistenceBackend` pair. |
| **RFC-803** (StrangeLoop Checkpoint Backend) | Workspace checkpoints (file/blob state) are a distinct layer from StrangeLoop loop checkpoints (execution-graph state). A loop checkpoint may *reference* a workspace checkpoint, but they do not share storage. |
| **RFC-306** (DurabilityProtocol) | Workspace run lifecycle (create/resume/suspend/cleanup) is conceptually adjacent to thread lifecycle but operates at the workspace-run granularity, not the thread granularity. Integration point, not overlap. |

### Package placement (AGENTS.md §7b)

The Workspace Manager is host-runner territory — it bridges object storage and the local filesystem for an agent run. Per the Soothe package DAG:

| Piece | Package |
|-------|---------|
| `WorkspaceSyncBackend` protocol + `Resource`/`ManifestEntry`/`Manifest`/`ArtifactSpec`/`Artifact`/`CheckpointType`/`CheckpointPayload` data models | `soothe-sdk` (shared contracts) |
| `WorkspaceManager`, `Workspace`, CAS cache, dirty tracker, `FsspecSyncBackend` (fsspec-based, supports S3/GCS/Azure/local/memory) | `soothe` (host runner) |
| `WorkspaceStateStore` protocol + `SqliteWorkspaceStateStore` / `PostgresWorkspaceStateStore` + `create_workspace_state_store()` factory | `soothe` (host runner) |
| `construct_sync_backend(uri, config)` factory (uses `fsspec.url_to_fs`) | `soothe` (host runner) |
| Workspace lifecycle RPCs / admin IO | `soothe-daemon` |
| CLI/TUI commands that trigger workspace operations | `soothe-cli` (via WebSocket, not direct import) |

The `FsspecSyncBackend` MUST import only `soothe-sdk` contracts and `fsspec` — it must not import `soothe-autopilot`, `soothe-daemon`, or `soothe-cli`.

### DAG compliance

```text
soothe-sdk
  │  WorkspaceSyncBackend protocol
  │  Resource, Manifest, Artifact models
  ↓
soothe-nano
  │  (no workspace sync code — just path resolution)
  ↓
soothe
  │  WorkspaceManager (concrete)
  │  FsspecSyncBackend (concrete, imports fsspec + optional s3fs/gcsfs/adlfs)
  │  CAS cache, dirty tracker, debouncer
  │  WorkspaceStateStore (SQLite/Postgres)
  ↓
soothe-daemon
     _handle_loop_new: detect remote URI, bootstrap WorkspaceManager
     workspace lifecycle RPCs
```

No DAG arrows are reversed. `soothe` imports `soothe-sdk` (for the protocol) and `soothe-nano` (for path resolution facade). `soothe-daemon` imports `soothe` (for the Workspace Manager). No package imports a downstream package.

---

## 49. Resolved design questions

These questions were open in prior drafts and are now resolved:

### Q1 — Agent identity

Which filesystem-native agent consumes this workspace? A new RFC (or a revision to an existing built-in agent RFC) should name it. Candidate: a `research_workspace` agent or an extension of an existing analysis agent. **Status: remains open for a separate RFC — not a blocker for this design.**

### Q2 — Object-store provisioning

Is the S3-compatible store (MinIO) a daemon-managed sidecar (docker-compose service) or an externally-provided S3 endpoint? Affects config shape and credential management. **Status: remains open for deployment architecture — not a blocker for this design.**

### Q3 — Workspace run ↔ thread/loop linkage

Should a workspace run be 1:1 with a StrangeLoop thread, or can a single thread own multiple sequential workspace runs? Affects `recover()` semantics and RFC-803 cross-referencing. **Status: remains open for RFC-803 reconciliation — not a blocker for this design.**

### Q4 — `.workspace/` visibility enforcement

Confirm that RFC-102's `SecurityConfig` path blacklist can hide a subdirectory (not just file types); if not, a small RFC-102 extension is needed. **Status: remains open for RFC-102 confirmation.**

### Q5 — macOS watcher in production

`FSEvents` is fine for dev hosts, but production runs in Linux containers — confirm the watcher abstraction's stat-scan fallback is acceptable for the MVP or whether `inotify`-only is acceptable with macOS as dev-only. **Resolved: hybrid watcher with FSEvents on macOS dev hosts and inotify on Linux containers is the MVP; stat-scan fallback for degraded environments. See §12.**

### Q6 — boto3 vs aioboto3 (formerly open question #2 in prior drafts)

**Resolved: Neither boto3 nor aioboto3 is a direct dependency.** `fsspec` is the transport abstraction; `s3fs` (which wraps `aiobotocore`) is an optional extra for S3 deployments. The async-I/O gap is bridged via `asyncio.to_thread()`. See §6c.

### Q7 — `gs://` and other URI schemes (formerly open in the `s3://` URI draft)

**Resolved: All fsspec-supported schemes work out of the box.** The `construct_sync_backend(uri, config)` factory uses `fsspec.url_to_fs(uri)` — no per-scheme dispatch code needed. `s3://`, `gs://`, `az://`, `file://`, and `memory://` all work with zero additional code. See §6c.

### Q8 — Manifest synthesis from prefix listing (no `manifest.json`)

**Resolved: Option B (synthesize) for MVP, with Option A (explicit manifest) as fast-path.** If `manifest.json` exists at the prefix root, use it. Otherwise, the `FsspecSyncBackend` lists the prefix via `fs.ls()`, computes SHA-256 for each object (via streaming hash), and builds a `Manifest` on the fly. The synthesized manifest is cached in the workspace state DB (§21) so subsequent materializations of the same prefix are cheap.

### Q9 — Write-back semantics

**Resolved: Write artifacts to a configurable `workspace_sync.publish_prefix`** (default: `<source>/artifacts/`), never overwrite the source prefix.

### Q10 — Re-sync on resume

**Resolved: No.** On resume, use the local workspace state DB + last checkpoint. Only re-materialize from the object store if the local workspace is missing (crash recovery, §26).

---

## 50. Dependency changes

### `packages/soothe/pyproject.toml`

```toml
[project]
dependencies = [
    # ... existing deps ...
    "fsspec>=2026.0",          # NEW — core, lightweight (~2 MB)
]

[project.optional-dependencies]
s3 = ["s3fs>=2026.0"]          # S3/MinIO support
gcs = ["gcsfs>=2026.0"]        # Google Cloud Storage
azure = ["adlfs>=2026.0"]      # Azure Blob Storage
all-backends = ["s3fs>=2026.0", "gcsfs>=2026.0", "adlfs>=2026.0"]
```

### No changes to `soothe-sdk` or `soothe-nano`

The protocol stays in the SDK. fsspec is a host-only dependency. Nano is unaffected.

---

## 51. Module layout

New modules under `packages/soothe/src/soothe/workspace/`:

```text
soothe/workspace/
├── sync/                          ← NEW
│   ├── __init__.py
│   ├── manager.py                 ← WorkspaceManager (lifecycle orchestrator)
│   ├── workspace.py               ← Workspace (per-run handle: open, materialize, checkpoint, publish, close)
│   ├── cas.py                     ← Local CAS cache (SHA-256 → blob, reflink/hardlink/copy)
│   ├── dirty_tracker.py           ← Hybrid FS watcher (inotify/FSEvents/stat-scan)
│   ├── debouncer.py               ← Debounced checkpoint trigger
│   ├── manifest_synth.py         ← Synthesize manifest from prefix listing (no manifest.json)
│   └── backends/
│       ├── __init__.py
│       └── fsspec.py              ← FsspecSyncBackend (fsspec — unified adapter)
├── state/                         ← NEW
│   ├── __init__.py
│   ├── protocol.py                ← WorkspaceStateStore protocol
│   ├── sqlite.py                  ← SqliteWorkspaceStateStore
│   ├── postgres.py               ← PostgresWorkspaceStateStore
│   └── factory.py                 ← create_workspace_state_store()
├── resolution.py                  ← MODIFY: detect remote URI scheme (s3://, gs://, etc.)
├── loop_workspace.py              ← EXISTING
├── core_resolution.py             ← EXISTING
├── scoped.py                      ← EXISTING
└── __init__.py                    ← MODIFY: re-export new public API
```

### URI entry point integration

In `soothe/workspace/resolution.py`, add a URI classifier:

```python
def is_remote_workspace_uri(value: str) -> bool:
    """True if value is a remote URI (s3://, gs://, az://, etc.) not a local path."""
    return "://" in value and not value.startswith("file://")
```

`validate_client_workspace` must reject remote URIs (it's for local paths only).

In the daemon router (`_handle_loop_new`), add URI-scheme detection before the existing `validate_client_workspace` path:

```python
raw_workspace = msg.get("client_workspace") or msg.get("workspace")
sync_source = msg.get("workspace_sync_source")  # NEW field

if _is_remote_uri(raw_workspace):
    sync_source = raw_workspace
    raw_workspace = None  # don't treat as local path

if sync_source:
    # Materialize temp workspace from remote source
    backend = construct_sync_backend(sync_source, config)
    local_root = await _workspace_manager.open_from_uri(
        run_id=loop_id,
        backend=backend,
        source_uri=sync_source,
    )
    effective_workspace = local_root
    meta_updates["workspace_sync_source"] = sync_source
else:
    # Existing local-path resolution (RFC-621)
    ...
```

### Loop metadata

New metadata fields persisted on `loop_new`:

| Field | Purpose |
|-------|---------|
| `workspace_sync_source` | The original URI (`s3://bucket/proj/`, `gs://bucket/proj/`, etc.) |
| `workspace_sync_backend` | Serialized backend config (endpoint, bucket, prefix, storage_options) |
| `current_workspace` | The local temp workspace path (as today) |

On crash recovery, the daemon reads `workspace_sync_source`, reconstructs the backend via `construct_sync_backend()`, calls `workspace.recover(checkpoint_id)`, and resumes.

---

## 52. Key invariant: the agent never sees the URI

The agent **never sees `s3://`, `gs://`, or any remote URI**. The agent sees an ordinary local filesystem path (`$SOOTHE_HOME/data/workspaces/<run-id>/`). The remote URI is a **sync source**, recorded in loop metadata, and the Workspace Manager handles all remote I/O. This preserves Invariant 4 (§45): "the agent never directly accesses the storage backend."

---

## 53. What this design does NOT change

- **Agent behavior:** The agent sees a local path. No object-store awareness. No new tools needed.
- **Materialization algorithm (§9):** Unchanged — manifest → CAS → hardlink/reflink.
- **Dirty tracking (§12):** Unchanged — FS events → dirty set → debounce → checkpoint.
- **Checkpoint/publish (§14, §15, §32):** Unchanged — local state DB → background uploader → object store.
- **CAS dedup (§24):** Unchanged — content-addressed blobs shared across runs.
- **Security (§35):** Unchanged — credentials stay in the backend, agent never sees them.
- **`WorkspaceSyncBackend` protocol:** Unchanged — stays in `soothe-sdk`.
- **`WorkspaceManager`:** Unchanged — stays concrete in `soothe`, talks to the protocol.
- **All 9 core invariants (§45):** Unchanged.
- **Package DAG:** `fsspec` is a dependency of `soothe` (host), not `soothe-sdk` or `soothe-nano`.
