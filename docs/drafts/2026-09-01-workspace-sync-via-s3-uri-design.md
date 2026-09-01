# Workspace Sync via `s3://` URI as `current_workspace`

**Status:** Discussion (design exploration — pending review)
**Date:** 2026-09-01
**Scope:** Extending the `loop_new` `client_workspace` / `current_workspace` arg to accept remote URIs (`s3://path/to/dir`), enabling Soothe to materialize a temporary local workspace and sync with S3-compatible object storage.

**Related:**
- `docs/drafts/2026-08-25-research-workspace-materialization-design.md` (the workspace subsystem this builds on)
- `docs/drafts/2026-09-01-workspace-sync-layer-comparison.md` (implementation layer analysis: `soothe-nano` vs `soothe` — conclusion: `soothe`)
- `docs/specs/RFC-621-workspace-host-convention.md` (workspace path translation, Docker mount)
- `soothe_sdk.protocols.workspace_sync` (`WorkspaceSyncBackend`, `Resource`, `Manifest`, `Artifact`)

---

## 1. The idea (restated)

Today, `loop_new` accepts a `client_workspace` that is a **local filesystem path** (or a host path translatable to a container path via RFC-621 `workspace_mount`). The daemon validates it with `validate_client_workspace()` and either uses it directly or falls back to a daemon-generated workspace under `$SOOTHE_HOME/data/workspaces/`.

The proposal: allow `client_workspace` (or a sibling field) to carry a **remote URI** like `s3://my-bucket/projects/research-2026/`. When Soothe sees this, it:

1. Creates a **temporary local workspace** (the agent's filesystem-native working dir).
2. **Materializes** the S3 prefix into that local workspace (download → CAS → hardlink/reflink).
3. Runs the agent against the local workspace (agent is fully filesystem-native, no S3 awareness).
4. **Syncs** dirty changes back to S3 via debounced checkpointing + incremental persistence.
5. On completion, **publishes** final artifacts to S3 and cleans up the local temp workspace.

This is exactly the lifecycle already designed in the research-workspace materialization draft (§25: CREATE RUN → LOAD MANIFEST → MATERIALIZE FS → START AGENT → DIRTY TRACKER → CHECKPOINT → PUBLISH → CLEANUP). The new piece is: **the trigger is a `s3://` URI in the workspace arg, not a pre-populated manifest.**

---

## 2. Why this fits the existing design

The research-workspace materialization design (§6b, §9, §15) already defines:

- `WorkspaceSyncBackend` protocol (in `soothe-sdk`) with `get_blob`, `put_blob`, `head_blob`, `get_manifest`, `put_manifest`, `publish_artifact`, etc.
- `S3WorkspaceSyncBackend` (concrete, in `soothe` host) — written against the S3 API surface, works against MinIO/AWS S3/RDS-S3.
- Incremental materialization: manifest → CAS lookup → download-if-missing → hardlink/reflink to workspace.
- Dirty tracking → debounced checkpoint → CAS → background upload to storage backend.

The `s3://` URI is simply the **entry point** that tells the Workspace Manager: "this run's backing store is S3, here is the bucket+prefix, materialize from there." Everything downstream is already specified.

### What's missing in the current code

`validate_client_workspace()` (in `soothe/workspace/resolution.py`) calls `Path(workspace).expanduser().resolve()` — it assumes a local path. A `s3://` URI would fail `Path()` resolution or, worse, be silently treated as a relative path. The router (`_handle_loop_new` in `router.py` ~line 1796) checks `resolved.exists()` — an S3 URI never "exists" locally.

So the gap is: **URI-scheme detection + Workspace Manager bootstrap when the workspace arg is a remote URI.**

---

## 3. Proposed flow

```text
Client                          Soothe Daemon
──────                          ─────────────
loop_new {
  client_workspace:             _handle_loop_new
  "s3://bucket/proj/"           │
}                               ├─ detect URI scheme (s3://, gs://, file://)
                                │
                                ├─ if remote URI:
                                │    ├─ parse bucket + prefix
                                │    ├─ construct S3WorkspaceSyncBackend(endpoint, creds)
                                │    ├─ create temp local workspace
                                │    │   ($SOOTHE_HOME/data/workspaces/<run-id>/)
                                │    ├─ WorkspaceManager.open(run_id, backend, local_root)
                                │    ├─ backend.get_manifest(run_id) or synthesize from S3 listing
                                │    ├─ workspace.materialize(resources)
                                │    └─ effective_workspace = local_root  ← agent sees this
                                │
                                ├─ else (local path):
                                │    └─ existing RFC-621 resolution
                                │
                                └─ persist current_workspace = local_root
                                   persist workspace_sync_source = "s3://bucket/proj/"
                                   persist workspace_sync_backend config

agent runs on local_root ───────►  FS events → dirty tracker → checkpoint → S3
                                  │
agent finish ──────────────────►  workspace.publish(artifacts) → S3
                                  workspace.close() → cleanup local temp
```

### Key invariant

The agent **never sees `s3://`**. The agent sees an ordinary local filesystem path (`$SOOTHE_HOME/data/workspaces/<run-id>/`). The S3 URI is a **sync source**, recorded in loop metadata, and the Workspace Manager handles all remote I/O. This preserves Invariant 4 (§45 of the materialization design): "the agent never directly accesses the storage backend."

---

## 4. Design decisions to resolve

### 4.1 Field name: `client_workspace` vs. a new `workspace_sync_source`

**Option A — overload `client_workspace`:** Accept `s3://` in the existing field. Pro: no schema change. Con: conflates "local path the agent runs on" with "remote source to sync from" — these are conceptually different. Also, `client_workspace` currently means "a path that exists on the client/daemon host."

**Option B — new field `workspace_sync_source`:** Add an optional field. When present, the daemon materializes a temp workspace from that source and sets `current_workspace` to the local temp path. Pro: clean separation; `client_workspace` keeps its local-path semantics. Con: schema addition.

**Recommendation: Option B.** The semantics are genuinely different — `client_workspace` is "where the agent works locally," `workspace_sync_source` is "where to sync from/to remotely." Mixing them invites bugs (e.g., `validate_client_workspace` choking on `s3://`). The materialization design already separates these concepts (§6: Resource has `path` + `sha256`, no `uri`; the backend resolves location internally).

### 4.2 Manifest synthesis: explicit manifest vs. S3 prefix listing

The materialization design assumes a `Manifest` exists in the object store (`backend.get_manifest(run_id)`). But a raw `s3://bucket/proj/` prefix may not have a manifest — it may just be a directory of files.

**Option A — require a manifest:** The S3 prefix must contain `manifest.json`. Pro: content-addressed from the start, CAS dedup works immediately. Con: user must pre-generate manifests — friction for ad-hoc usage.

**Option B — synthesize manifest from S3 listing:** On `open()`, the backend lists the prefix, computes SHA-256 for each object (via S3 `HEAD` ETag or streaming hash), and builds a `Manifest` on the fly. Pro: zero-friction `s3://bucket/proj/` works out of the box. Con: first-run listing + hashing cost; ETag is MD5 for single-part uploads (not SHA-256) — need a streaming `get_blob` + hash.

**Recommendation: Option B for MVP, with Option A as fast-path.** If `manifest.json` exists at the prefix root, use it (Option A). Otherwise, synthesize via S3 `ListObjectsV2` + streaming hash (Option B). The synthesized manifest is cached in the workspace state DB (§21) so subsequent materializations of the same prefix are cheap.

### 4.3 Sync direction: one-way materialize vs. bidirectional sync

The materialization design explicitly rejects continuous bidirectional sync (§38): "Materialization is one-way (store → FS); persistence is one-way (FS → store). No live conflict resolution."

**This proposal is consistent with that.** The `s3://` source is materialized once at `open()`, then the agent works locally, then changes are checkpointed/published back. It is **not** a live mount of S3 as a filesystem (no FUSE, no s3fs). If the user expects `s3://` to behave like a mounted network drive with real-time consistency, that is a different feature and should be a separate RFC.

**Recommendation: keep one-way materialize + one-way publish.** Document clearly that `s3://` as workspace means "sync-in at start, sync-out at end (and on checkpoints)," not "live mount."

### 4.4 Credentials and endpoint configuration

The `S3WorkspaceSyncBackend` holds credentials (§6b credential isolation). Where do they come from?

**Option A — from the URI:** `s3://bucket/prefix` with credentials from environment (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL_S3` for MinIO). Pro: zero-config if env is set. Con: no per-run credential override.

**Option B — from config:** A `workspace_sync` config section declares endpoint, credentials, and the URI references the bucket+prefix only. Pro: centralized credential management. Con: more config.

**Option C — from the URI with inline options:** `s3://bucket/prefix?endpoint=https://minio.local:9000` (non-standard but pragmatic). Con: URI abuse.

**Recommendation: Option A (env) + Option B (config) hybrid.** Env vars work out of the box (standard AWS SDK behavior). A `workspace_sync` config section (`endpoint_url`, `region`, `credentials_profile`) overrides env for daemon-managed deployments. The URI itself is just `s3://bucket/prefix`. This matches how `boto3`/`aioboto3` already work.

### 4.5 Cleanup: delete local temp workspace on close

When the agent finishes and artifacts are published to S3, the local temp workspace (`$SOOTHE_HOME/data/workspaces/<run-id>/`) should be cleaned up — unless crash recovery is needed.

**Recommendation:** Keep the local workspace until `workspace.close()` is explicitly called (or a grace period for crash recovery). The CAS cache (`/agent-cache`) is shared across runs and not cleaned per-run. This matches §29 (cache eviction) and §28 (concurrency — CAS is immutable, shared).

---

## 5. Integration points with existing code

### 5.1 `router.py` — `_handle_loop_new`

Add URI-scheme detection before the existing `validate_client_workspace` path:

```python
raw_workspace = msg.get("client_workspace") or msg.get("workspace")
sync_source = msg.get("workspace_sync_source")  # NEW field

if _is_remote_uri(raw_workspace):
    sync_source = raw_workspace
    raw_workspace = None  # don't treat as local path

if sync_source:
    # Materialize temp workspace from remote source
    backend = _construct_sync_backend(sync_source, config)
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

### 5.2 `soothe/workspace/resolution.py`

Add a URI classifier:

```python
def is_remote_workspace_uri(value: str) -> bool:
    """True if value is a remote URI (s3://, gs://, etc.) not a local path."""
    return "://" in value and not value.startswith("file://")
```

`validate_client_workspace` must reject remote URIs (it's for local paths only).

### 5.3 `soothe_sdk.protocols.workspace_sync`

No protocol change needed — `WorkspaceSyncBackend` already has `get_blob`/`put_blob`/`get_manifest`/`put_manifest`/`publish_artifact`. The new piece is a **factory** that constructs the right backend from a URI:

```python
def construct_sync_backend(uri: str, config) -> WorkspaceSyncBackend:
    scheme = uri.split("://")[0]
    if scheme == "s3":
        return S3WorkspaceSyncBackend(
            bucket=..., prefix=...,
            endpoint_url=config.workspace_sync.endpoint_url,
            credentials=...,
        )
    raise ValueError(f"Unsupported workspace sync scheme: {scheme}")
```

This factory lives in `soothe` (host), not `soothe-sdk` (the SDK has the protocol, the host has the concrete backends).

### 5.4 Loop metadata

New metadata fields persisted on `loop_new`:

| Field | Purpose |
|-------|---------|
| `workspace_sync_source` | The original `s3://` URI |
| `workspace_sync_backend` | Serialized backend config (endpoint, bucket, prefix) |
| `current_workspace` | The local temp workspace path (as today) |

On crash recovery, the daemon reads `workspace_sync_source`, reconstructs the backend, calls `workspace.recover(checkpoint_id)`, and resumes.

---

## 6. What this does NOT change

- **Agent behavior:** The agent sees a local path. No S3 awareness. No new tools needed.
- **Materialization algorithm (§9):** Unchanged — manifest → CAS → hardlink/reflink.
- **Dirty tracking (§12):** Unchanged — FS events → dirty set → debounce → checkpoint.
- **Checkpoint/publish (§14, §15, §32):** Unchanged — local state DB → background uploader → S3.
- **CAS dedup (§24):** Unchanged — content-addressed blobs shared across runs.
- **Security (§35):** Unchanged — credentials stay in the backend, agent never sees them.

The only new surface is: **URI detection at `loop_new` + backend factory + manifest synthesis from S3 listing.**

---

## 7. Open questions

1. **Manifest synthesis cost.** For a prefix with 10,000 files, the first `ListObjectsV2` + streaming hash pass is expensive. Should we cap the number of resources materialized in one go, or paginate materialization? (The design supports lazy materialization in Phase 4, but MVP is eager.)

2. **Write-back semantics.** When the agent writes to `output/report.md`, does it sync back to the **same** `s3://bucket/proj/` prefix, or to a separate `s3://bucket/proj-output/`? If same prefix, we need to handle overwrite of source resources. **Recommendation:** write artifacts to a configurable `workspace_sync.publish_prefix` (default: `<source>/artifacts/`), never overwrite the source.

3. **`gs://` and other schemes.** The `WorkspaceSyncBackend` protocol is scheme-agnostic. `GcsWorkspaceSyncBackend` is future work. For MVP, only `s3://` is implemented. The URI classifier and factory should reject unsupported schemes with a clear error.

4. **Local `file://` URIs.** Should `file:///path/to/dir` be accepted as a no-op sync source (materialize from a local directory)? This would be useful for testing the sync path without S3. The `LocalFsSyncBackend` (§6b, dev/testing) already exists for this. **Recommendation:** yes, accept `file://` as a testing path.

5. **Re-sync on resume.** If a loop is resumed after the agent wrote some files, does the daemon re-materialize from S3 (potentially overwriting local changes)? **Recommendation:** no — on resume, use the local workspace state DB + last checkpoint. Only re-materialize from S3 if the local workspace is missing (crash recovery, §26).

---

## 8. Summary

The proposal — `s3://path/to/dir` as a workspace arg that triggers temp local workspace + S3 sync — is **a natural extension of the existing research-workspace materialization design**, not a new architecture. The materialization, CAS, dirty tracking, checkpoint, and publish machinery is already specified. The new work is:

1. URI-scheme detection in `loop_new` (router.py).
2. A `workspace_sync_source` field (clean separation from `client_workspace`).
3. A backend factory (`construct_sync_backend(uri, config)`).
4. Manifest synthesis from S3 listing (when no `manifest.json` exists).
5. Loop metadata persistence of the sync source for crash recovery.

Everything else — the agent's filesystem-native experience, CAS dedup, debounced persistence, credential isolation — is already designed and invariant-preserving.
