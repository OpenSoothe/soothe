# Research Workspace Materialization and Incremental Persistence

**Status:** Proposed (design draft — pending user review)
**Version:** 1.6 (dual-backend durability: WorkspaceStateStore follows persistence.default_backend)
**Date:** 2026-08-25
**Scope:** Filesystem-native agent runtime, S3-compatible object store (MinIO) as durable backing, local filesystem workspace

> This is a **workspace subsystem** design, not an agent-identity design. It serves any **filesystem-native** agent (e.g. a research/analysis agent that reads uploaded PDFs and writes reports). The agent identity that consumes this workspace is left to a separate RFC.

---

## Primary goals

- Minimize network bandwidth between the object store and the agent host
- Preserve filesystem-native agent behavior (the agent sees ordinary paths, no object-store awareness)
- Support incremental / diff-based agent writing with crash recovery
- Keep the object store (MinIO) as durable storage, not the agent's hot working filesystem

---

## 1. Problem

A filesystem-native research agent expects user resources and generated artifacts to exist as ordinary filesystem paths. The surrounding platform stores uploaded resources and persistent artifacts in an S3-compatible object store (MinIO).

A naive implementation performs:

```text
object store → download entire resource tree → agent filesystem
agent → upload entire output tree → object store
```

This wastes bandwidth because:

1. Resources are frequently reused across research runs
2. Agent outputs are incrementally modified rather than rewritten from scratch
3. Research runs may contain many intermediate files that do not need persistence
4. Large resources may change only partially
5. Multiple runs may share identical resources
6. Uploading every filesystem event to object storage introduces excessive network traffic
7. The object store should be durable storage, not the agent's hot working filesystem

The system therefore needs a filesystem workspace with **incremental materialization, local caching, dirty tracking, content addressing, checkpointing, and incremental persistence**.

---

## 2. Design principles

### 2.1 Object store is the durable source of truth

The object store (S3/MinIO) stores: user resources, resource manifests, durable checkpoints, published artifacts, content-addressed blobs. The agent never needs to know that the object store exists. The storage backend is abstracted behind the `WorkspaceSyncBackend` protocol (§6b).

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

---

## 3. High-level architecture

```text
                         ┌────────────────────┐
                         │  S3 / MinIO / GCS  │
                         │  (durable store)   │
                         │                    │
                         │ resources/         │
                         │ manifests/         │
                         │ blobs/             │
                         │ checkpoints/       │
                         │ artifacts/         │
                         └─────────┬──────────┘
                                   │
                            Resource Manifest
                                   │
                                   ▼
              ┌────────────────────────────────────────┐
              │     WorkspaceSyncBackend (protocol)    │  ← soothe-sdk
              │     get_blob / put_blob / head_blob   │
              │     get_manifest / put_manifest       │
              │     list/get/put_checkpoint           │
              │     publish_artifact                  │
              └────────────────────┬─────────────────┘
                                   │  (injected)
                                   ▼
                    ┌──────────────────────────┐
                    │    Workspace Manager     │  ← soothe (host)
                    └────────────┬─────────────┘
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

### Protocol boundary (Option C)

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
│         ├─ S3WorkspaceSyncBackend  (boto3/aioboto3)     │
│         ├─ LocalFsSyncBackend       (dev/testing)        │
│         └─ GcsWorkspaceSyncBackend  (future)            │
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

A full `Workspace` protocol (`materialize`, `checkpoint`, `publish`, `recover`, `close`) was considered (Option B) and **rejected**. The workspace lifecycle logic (CAS, dirty tracking, debouncing) is the hard part and should not be reimplemented per backend. Making the manager a protocol would produce N implementations of the same algorithm. The protocol boundary is at the storage backend, not the manager.

### Backend implementations

| Backend | Package | Use case |
|---------|---------|----------|
| `S3WorkspaceSyncBackend` | `soothe` (host) | Production — any S3-compatible store (MinIO, RDS-S3, AWS S3) |
| `LocalFsSyncBackend` | `soothe` (host) | Dev/testing — no network, uses local directory as the "remote" store |
| `GcsWorkspaceSyncBackend` | future | Google Cloud Storage |

The S3 adapter MUST be written against the S3 API surface (not MinIO-specific extensions) so it works against any S3-compatible store. MinIO is the reference implementation.

### Credential isolation

The `WorkspaceSyncBackend` implementation holds the storage credentials. The Workspace Manager receives an already-constructed backend instance — it never sees credentials. The agent never sees either. This enforces Invariant 4 (§45: "the agent never directly accesses the storage backend").

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

### 12.1 Strategy: hybrid platform-adaptive watcher (Option D, chosen)

The dirty tracker uses a **thin hybrid abstraction** that selects a native OS watcher when available and falls back to stat-scan polling otherwise. No third-party watcher library (e.g. `watchdog`) is introduced — the wrapper is ~200 lines of stdlib code.

| Platform | Primary backend | Fallback |
|----------|-----------------|----------|
| **Linux** | `inotify` (via `ctypes` or `os.scandir` diff) | stat-scan polling |
| **macOS** | `FSEvents` (via `ctypes` / CoreServices) | stat-scan polling |
| **Windows** | `ReadDirectoryChangesW` (via `pywin32` if installed) | stat-scan polling |

Rationale for rejecting alternatives:

- **inotify-only (Option A):** Linux-only; does not work on macOS dev hosts.
- **stat-scan polling only (Option B):** Adds latency equal to the poll interval, which fights the debounced persistence design (§13) — the debounce window can never be smaller than the poll interval.
- **`watchdog` library (Option C):** Heavy transitive dependency; fragile cross-platform abstraction; unnecessary bloat for a thin wrapper.

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

**Delete tracking:** deletions are recorded separately from modifications so the checkpoint knows to remove entries from the remote manifest. This is the easy-to-forget case.

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

### Why snapshot + delta (not full-snapshot-only or delta-only)

- **Full-snapshot-only** (Option A): trivially correct and idempotent, but re-uploads the entire manifest + dirty set every checkpoint. For a 500-entry manifest checkpointed every 60s over a 4-hour run, that's ~240 redundant uploads.
- **Delta-only** (Option B): minimal bandwidth, but recovery requires strict ordering, tombstone tracking for deletes, and gap-filling when a delta is lost. A single corrupted checkpoint invalidates the entire chain.
- **Snapshot + delta** (Option C, chosen): the first checkpoint and periodic compactions are self-contained `SNAPSHOT`s; intermediate checkpoints are compact `DELTA`s referencing their parent. Recovery anchors on the nearest preceding snapshot and replays deltas forward. A lost delta degrades gracefully — fall back to the last snapshot and restart from there.

This mirrors the §18 text-diff pattern (snapshot + patches with periodic compaction) at the metadata level, keeping one mental model across both subsystems.

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

The factory branches on `config.persistence.default_backend`, the same pattern as `create_cron_job_store` and the StrangeLoop checkpoint backend selection. Both implementations expose the same async API (a `WorkspaceStateStore` protocol — see below).

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

> **New external dependency note:** Soothe currently has **no** MinIO/S3 dependency in the codebase. This design introduces an S3-compatible object store as a new external backing service. The adapter MUST be written against the S3 API surface (not MinIO-specific extensions) so it works against MinIO, RDS-S3, or any S3-compatible store. MinIO is the reference implementation. The physical layout below is the `S3WorkspaceSyncBackend` implementation's concern — other backends may use a different layout.

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
S3 adapter (S3 API surface)
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
                         ┌─────────────┐
                         │  S3 / MinIO  │
                         │             │
                         │ resources   │
                         │ CAS blobs   │
                         │ manifests   │
                         └──────┬──────┘
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

**In short:** The object store (S3/MinIO) is the durable content-addressed store. The local filesystem is the agent's transaction workspace. The `WorkspaceSyncBackend` protocol (in `soothe-sdk`) abstracts the storage backend; the Workspace Manager (concrete, in `soothe`) bridges the two using manifests, CAS, dirty tracking, asynchronous checkpoints, and incremental persistence — all backend-agnostic.

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
| `WorkspaceManager`, `Workspace`, CAS cache, dirty tracker, S3/MinIO adapter | `soothe` (host runner) |
| `WorkspaceStateStore` protocol + `SqliteWorkspaceStateStore` / `PostgresWorkspaceStateStore` + `create_workspace_state_store()` factory | `soothe` (host runner) |
| `LocalFsSyncBackend` (dev/testing backend) | `soothe` (host runner) |
| Workspace lifecycle RPCs / admin IO | `soothe-daemon` |
| CLI/TUI commands that trigger workspace operations | `soothe-cli` (via WebSocket, not direct import) |

The S3 adapter MUST import only `soothe-sdk` contracts and a standard S3 client library — it must not import `soothe-autopilot`, `soothe-daemon`, or `soothe-cli`.

---

## 49. Open questions (for RFC formalization)

These are flagged for resolution during RFC formalization, not blockers for draft approval:

1. **Agent identity.** Which filesystem-native agent consumes this workspace? A new RFC (or a revision to an existing built-in agent RFC) should name it. Candidate: a `research_workspace` agent or an extension of an existing analysis agent.
2. **Object-store provisioning.** Is the S3-compatible store (MinIO) a daemon-managed sidecar (docker-compose service) or an externally-provided S3 endpoint? Affects config shape and credential management.
3. **Workspace run ↔ thread/loop linkage.** Should a workspace run be 1:1 with a StrangeLoop thread, or can a single thread own multiple sequential workspace runs? Affects `recover()` semantics and RFC-803 cross-referencing.
4. **`.workspace/` visibility enforcement.** Confirm that RFC-102's `SecurityConfig` path blacklist can hide a subdirectory (not just file types); if not, a small RFC-102 extension is needed.
5. **macOS watcher in production.** `FSEvents` is fine for dev hosts, but production runs in Linux containers — confirm the watcher abstraction's stat-scan fallback is acceptable for the MVP or whether `inotify`-only is acceptable with macOS as dev-only. (Decision: hybrid watcher with FSEvents on macOS dev hosts and inotify on Linux containers is the MVP; stat-scan fallback for degraded environments. See §12.)
