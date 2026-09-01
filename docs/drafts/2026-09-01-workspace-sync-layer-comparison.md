# Workspace Sync: Implementation Layer Comparison — `soothe-nano` vs `soothe`

**Status:** Discussion (design analysis — pending review)
**Date:** 2026-09-01
**Scope:** Deciding whether the workspace sync feature (S3 materialization, CAS, dirty tracking, checkpointing, publish) should be implemented in `soothe-nano` or `soothe`.
**Related:**
- `docs/drafts/2026-08-25-research-workspace-materialization-design.md` (§48: package placement)
- `docs/drafts/2026-09-01-workspace-sync-via-s3-uri-design.md` (the `s3://` URI entry point)
- `AGENTS.md` §7b (package DAG and import boundaries)

---

## 1. Executive summary

**Implement in `soothe` (host runner), not `soothe-nano`.**

This is not a close call. The existing design (§48 of the materialization doc) already specifies this placement, and the codebase architecture strongly reinforces it. The workspace sync subsystem is host-runner territory: it bridges object storage and the local filesystem for an agent run, manages process-level resources (CAS cache, state DB, FS watchers), and must not exist in the in-process coding agent layer.

The protocol contracts (`WorkspaceSyncBackend`, `Resource`, `Manifest`, `Artifact`) already live in `soothe-sdk` — this is correct and should stay.

---

## 2. The two layers

### 2.1 `soothe-nano` — the in-process coding agent

```
soothe-nano (PyPI)
├── agent/          ← CoreAgent, LLM wiring, graph compilation
├── middleware/     ← _before_step / _after_step hooks (PRIVATE, closed to host)
├── workspace/      ← workspace_api, workspace_runtime, workspace_policy, workspace_filesystem
├── backends/       ← persistence (SQLite/Postgres KV store), durability, vector_store
├── filesystem/     ← secure filesystem backend (RFC-102)
├── persistence/    ← pool management, DB init, SQL migrations
└── ...
```

**What nano's `workspace/` package does today:**
- `workspace_api.py` — resolve which local path an agent stream should use (precedence: explicit → thread → daemon_default → cwd)
- `workspace_runtime.py` — `ContextVar`-based per-async-task workspace context (path, virtual mode, virtual home)
- `workspace_policy.py` — extract workspace from LangGraph configurable / messages / state (tool-execution resolution)
- `workspace_filesystem.py` — `FrameworkFilesystem`, `WorkspaceAwareBackend` (path normalization for tool I/O)

**Key characteristic:** nano's workspace code is about **which local directory the in-process agent operates on**. It is filesystem-path resolution and context propagation — not storage, not caching, not network I/O.

### 2.2 `soothe` — the host runner

```
soothe (host, OWNED)
├── workspace/      ← core_resolution, loop_workspace, resolution, scoped
├── runner/         ← host runner (agent execution lifecycle)
├── sloop/          ← StrangeLoop, Context Engine
├── persistence/    ← host persistence (SQLite/Postgres backends)
├── identity/       ← agent identity
└── ...
```

**What soothe's `workspace/` package does today:**
- `resolution.py` — `validate_client_workspace()`, `resolve_daemon_workspace()`, `translate_client_path_to_container()` / `translate_container_path_to_client()` (RFC-621 Docker mount translation)
- `loop_workspace.py` — `resolve_loop_workspace()`, `resolve_persisted_loop_workspace()` (daemon-generated workspace under `$SOOTHE_HOME/data/workspaces/<user>/ws_<hash>`)
- `scoped.py` — user-scoped workspace directory naming
- `core_resolution.py` — `WorkspacePrecedence` enum, `resolve_workspace()` dispatcher
- Re-exports nano's workspace API as a facade

**Key characteristic:** soothe's workspace code is about **workspace lifecycle management at the host level** — creating, validating, translating, and scoping workspace directories for daemon-managed runs. This is where `validate_client_workspace()` lives — the exact function that would need to recognize `s3://` URIs.

---

## 3. Why `soothe` is correct (6 reasons)

### Reason 1: The DAG forbids nano from importing host concerns

AGENTS.md §7b dependency DAG (allowed direction only):

```
soothe-sdk  (leaf)
    ↓
soothe-nano  (PyPI leaf)
    ↓
soothe  (host runner)
```

`soothe-nano` is a **downstream leaf** — it may import only `soothe-sdk`, `pydantic`, `langchain-core`, and `soothe-deepagents`. It **must not** import `soothe`, `soothe_autopilot`, `soothe_daemon`, or `soothe_cli`.

The workspace sync feature needs:
- `boto3` / `aioboto3` for S3 I/O (a heavy runtime dependency)
- Access to `$SOOTHE_HOME/data/workspaces/` (host filesystem layout)
- `WorkspaceStateStore` backed by the process-level persistence backend (SQLite or PostgreSQL, following `persistence.default_backend`)
- Integration with the host runner's lifecycle (`runner/` — when to open, checkpoint, publish, close the workspace)

If this code lived in `soothe-nano`, it would either:
- Pull `boto3` into the in-process agent's dependency tree (unacceptable for a PyPI package that should be lightweight), or
- Require nano to import host concerns (violating the DAG).

Neither is acceptable.

### Reason 2: The agent must never see the storage backend

The materialization design's Invariant 4 (§45): "the agent never directly accesses the storage backend."

`soothe-nano` IS the agent. Putting the sync backend in the agent layer would mean the agent layer holds the code that talks to S3. Even if the agent doesn't call it directly, the code proximity violates the architectural intent: the agent should be completely unaware that object storage exists.

In `soothe`, the Workspace Manager sits between the agent and the storage. The agent sees only local paths. The host runner manages the sync lifecycle around the agent's execution.

### Reason 3: Workspace state is process-owned, not agent-owned

The `WorkspaceStateStore` (§21, §48) tracks dirty file state, CAS index, checkpoint metadata. It follows `persistence.default_backend` — the **process-level** persistence mode (SQLite or PostgreSQL). This is a host-runner concern:

- The state DB schema (`ws_files`, `ws_blobs`, `ws_checkpoints`, `ws_artifacts`) lives in `soothe_metadata` in PostgreSQL mode.
- The factory pattern mirrors `create_cron_job_store()` and StrangeLoop's `SQLitePersistenceBackend` / `PostgreSQLPersistenceBackend` — both host-runner constructs.
- Nano's persistence layer (`backends/persistence/`) is a generic key-value `AsyncPersistStore` for thread state, not workspace file state. It's the wrong abstraction level.

### Reason 4: The lifecycle is host-managed, not agent-managed

The workspace sync lifecycle (§25):

```
CREATE RUN → LOAD MANIFEST → MATERIALIZE FS → START AGENT → DIRTY TRACKER → CHECKPOINT → PUBLISH → CLEANUP
```

This lifecycle wraps the agent's execution. The host runner (`soothe/runner/`) decides when to open the workspace, when to checkpoint (debounced, during agent execution), and when to publish (on agent completion). The agent itself has no awareness of this lifecycle — it just writes files.

`soothe-nano` is the thing being wrapped. Putting the wrapper inside the wrapped thing is circular.

### Reason 5: The `s3://` URI entry point is in `soothe` already

The prior discussion doc (§3) identifies the gap: `validate_client_workspace()` in `soothe/workspace/resolution.py` needs to detect `s3://` URIs. The router (`_handle_loop_new` in the daemon) needs to bootstrap the Workspace Manager when the workspace arg is a remote URI.

Both of these are host/daemon concerns:
- `validate_client_workspace()` is in `soothe/workspace/resolution.py` (host)
- `_handle_loop_new` is in the daemon router (host, specifically `soothe-daemon` which depends on `soothe`)

If the Workspace Manager lived in `soothe-nano`, the daemon would need to import nano to construct it — but the daemon already depends on `soothe`, and `soothe` already depends on `soothe-nano`. The natural injection point is `soothe`.

### Reason 6: The design doc already specifies this (§48)

The materialization design (§48, "Package placement") explicitly states:

> | Piece | Package |
> |-------|---------|
> | `WorkspaceSyncBackend` protocol + data models | `soothe-sdk` |
> | `WorkspaceManager`, `Workspace`, CAS cache, dirty tracker, S3/MinIO adapter | `soothe` (host runner) |
> | `WorkspaceStateStore` protocol + SQLite/Postgres implementations + factory | `soothe` (host runner) |
> | `LocalFsSyncBackend` (dev/testing) | `soothe` (host runner) |
> | Workspace lifecycle RPCs / admin IO | `soothe-daemon` |
> | CLI/TUI commands | `soothe-cli` (via WebSocket) |

This placement is correct and should be respected.

---

## 4. What goes where (concrete split)

### 4.1 `soothe-sdk` (shared contracts — already done)

Already exists: `soothe_sdk/protocols/workspace_sync.py`

Contains:
- `WorkspaceSyncBackend` protocol (blob ops, manifest ops, checkpoint ops, publish ops)
- `Resource`, `ManifestEntry`, `Manifest`, `ArtifactSpec`, `Artifact` data models
- `CheckpointType`, `CheckpointPayload` enums/models

**No change needed.** This is the protocol boundary. Both nano and soothe can import it.

### 4.2 `soothe` (host runner — where the implementation goes)

New modules under `packages/soothe/src/soothe/workspace/`:

```
soothe/workspace/
├── sync/                          ← NEW
│   ├── __init__.py
│   ├── manager.py                 ← WorkspaceManager (lifecycle orchestrator)
│   ├── workspace.py               ← Workspace (per-run handle: open, materialize, checkpoint, publish, close)
│   ├── cas.py                     ← Local CAS cache (SHA-256 → blob, reflink/hardlink/copy)
│   ├── dirty_tracker.py           ← Hybrid FS watcher (inotify/FSEvents/stat-scan)
│   ├── debouncer.py               ← Debounced checkpoint trigger
│   ├── manifest_synth.py          ← Synthesize manifest from S3 prefix listing (no manifest.json)
│   └── backends/
│       ├── __init__.py
│       ├── s3.py                  ← S3WorkspaceSyncBackend (boto3/aioboto3)
│       └── local_fs.py            ← LocalFsSyncBackend (dev/testing)
├── state/                         ← NEW
│   ├── __init__.py
│   ├── protocol.py                ← WorkspaceStateStore protocol
│   ├── sqlite.py                  ← SqliteWorkspaceStateStore
│   ├── postgres.py               ← PostgresWorkspaceStateStore
│   └── factory.py                 ← create_workspace_state_store()
├── resolution.py                  ← MODIFY: detect s3:// URI scheme
├── loop_workspace.py              ← EXISTING
├── core_resolution.py             ← EXISTING
├── scoped.py                      ← EXISTING
└── __init__.py                    ← MODIFY: re-export new public API
```

### 4.3 `soothe-nano` — no changes

Nano's `workspace/` package continues to handle:
- Local path resolution for the in-process agent
- `ContextVar` workspace context propagation
- Tool-execution workspace extraction from LangGraph state

Nano does not need to know that `s3://` exists. When the host materializes a temp workspace from S3, it sets the workspace path to the local temp dir — nano's existing resolution picks it up as an ordinary local path.

### 4.4 `soothe-daemon` — thin integration layer

The daemon's `_handle_loop_new` router (already in `soothe-daemon`) gains:
- URI scheme detection (delegates to `soothe.workspace.resolution`)
- Workspace Manager bootstrap (constructs `S3WorkspaceSyncBackend`, calls `WorkspaceManager.open()`)
- Persists `workspace_sync_source` in loop metadata

This is admin IO / lifecycle RPC territory — already the daemon's job.

---

## 5. Counter-argument: why might someone think nano is better?

### "Nano already has workspace code and persistence backends"

True, but the existing code is a different concern:
- Nano's `workspace/` is about **path resolution** (which local dir), not **storage sync** (remote ↔ local).
- Nano's `backends/persistence/` is a generic KV store for **thread state**, not **workspace file state**.
- Nano's `backends/durability/` manages **thread lifecycle** (create/resume/suspend), not **workspace lifecycle** (materialize/checkpoint/publish).

The names are similar; the concerns are disjoint.

### "Nano is where the agent runs, so workspace management should be close"

The opposite is true. The workspace sync subsystem **wraps** the agent's execution — it must sit above the agent, not inside it. The host runner (`soothe`) is the layer that orchestrates "before agent: materialize; during agent: dirty-track + checkpoint; after agent: publish." Nano is the thing being orchestrated.

### "Nano is PyPI-distributed, so putting sync there makes it reusable"

The sync feature is inherently host-coupled: it needs `$SOOTHE_HOME`, process-level persistence, FS watchers on the host OS, and `boto3`. It is not reusable as a standalone PyPI package — it only makes sense in the context of a Soothe daemon process. Putting it in nano would either bloat nano's dependency tree or require lazy imports that fragment the code.

---

## 6. Dependency flow (verified against DAG)

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
  │  S3WorkspaceSyncBackend (concrete, imports boto3)
  │  CAS cache, dirty tracker, debouncer
  │  WorkspaceStateStore (SQLite/Postgres)
  ↓
soothe-daemon
     _handle_loop_new: detect s3://, bootstrap WorkspaceManager
     workspace lifecycle RPCs
```

No DAG arrows are reversed. `soothe` imports `soothe-sdk` (for the protocol) and `soothe-nano` (for path resolution facade). `soothe-daemon` imports `soothe` (for the Workspace Manager). No package imports a downstream package.

---

## 7. Conclusion

| Criterion | `soothe-nano` | `soothe` |
|-----------|---------------|----------|
| DAG compliance | ✗ (would need boto3, host concerns) | ✓ (host runner, may import sdk + nano) |
| Agent isolation (Invariant 4) | ✗ (agent layer holds storage code) | ✓ (host wraps agent) |
| State store ownership | ✗ (thread KV store, wrong level) | ✓ (process-level, mirrors cron/StrangeLoop) |
| Lifecycle ownership | ✗ (agent can't wrap itself) | ✓ (runner orchestrates lifecycle) |
| URI entry point proximity | ✗ (validate_client_workspace is in soothe) | ✓ (same package) |
| Design doc §48 | ✗ (contradicts) | ✓ (matches) |

**Decision: implement in `soothe` (host runner).** Protocol contracts stay in `soothe-sdk`. Nano is unchanged. Daemon gets thin integration glue.

---

## 8. Open questions (for RFC formalization)

1. **`boto3` vs `aioboto3`:** The protocol is `async`. `aioboto3` provides native async, but `boto3` is more mature. Decision needed: pure `aioboto3`, or `boto3` + `asyncio.to_thread()` wrapper? Affects the S3 adapter implementation only.

2. **CAS cache location:** `$SOOTHE_HOME/data/cache/blobs/` (shared across runs) or per-workspace? Shared is better for dedup but needs concurrency handling. The design doc (§8) shows `/agent-cache/blobs/` — confirm this maps to `$SOOTHE_HOME/data/cache/`.

3. **WorkspaceStateStore vs StrangeLoop checkpoint:** The design doc (§48, RFC-803) notes these are distinct layers. Confirm the state store schema doesn't need to cross-reference StrangeLoop loop checkpoints for the MVP.

4. **`soothe-cli` interaction:** CLI commands that trigger workspace operations go through WebSocket (§48). What RPCs does the CLI need? Likely: `workspace_status`, `workspace_list_checkpoints`, `workspace_restore_checkpoint`. These are daemon RPCs, not direct imports.
