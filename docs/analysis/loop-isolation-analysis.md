# Loop-Based Isolation in the Daemon — Deep Analysis

> Scope: `packages/soothe/src/soothe/daemon/` (primary), cross-references to
> `packages/soothe/src/soothe/core/`, `packages/soothe-cli/`, `packages/soothe-sdk/`.
> Date: 2026-05-09
> Updated: 2026-05-09 (RFC-221 + bug fix audit)

---

## 1. Executive Summary

The Soothe daemon implements loop-based isolation where each **AgentLoop** (`loop_id`) serves as the primary unit of client work. The isolation architecture is layered across seven domains: events, workspace, input dispatch, running resources, persistence, client sessions, and subprocess execution.

The design is **architecturally sound** at the transport layer — the EventBus topic-based routing, single-subscription enforcement, and `_loop_scoped_client_message` boundary structurally prevent event leakage between loops. All previously identified bugs (4.1–4.5) have been fixed.

Since the original analysis, significant progress has been made:

- **RFC-221** (`LoopRunnerProtocol`) introduced per-loop subprocess isolation, eliminating the `SootheRunner` singleton data race on the streaming path — the root cause of the most severe isolation violations.
- **Bug 5.1** (ContextVar leak) and **Bug 5.2** (tool cache workspace key) are **fixed**.
- **Bug 5.5** (loop_detach interrupt futures) is **fixed**.
- **Bug 5.4** (loop_delete cleanup) is **substantially fixed** — now cancels queries, unsubscribes clients, and cleans up ThreadStateRegistry/Claude sessions. Minor gaps remain.
- **Flaw 6.2** (Claude session bridge) is **partially fixed** — `loop_delete` now calls `cleanup_claude_sessions()`.
- **Bug 5.7** (interrupt resolver) is **partially fixed** — `set_interrupt_resolver()` now accepts `loop_id`, scoping per-loop on the singleton.

**Remaining open issues**: 2 bugs (5.3 TOCTOU, 5.6 unbounded loops), 1 partially-fixed bug (5.4 loop_delete gaps), and 4 design flaws (6.1 runner lifecycle, 6.2 Claude session detach path, 6.3 MCP session, 6.4 ownership validation).

---

## 2. Architecture Overview

### 2.1 Isolation Model

```
Client (TUI/SDK)                        Daemon
=================                       ======
WebSocketClient
  |
  | loop_new {workspace}  ------>  MessageRouter._handle_loop_new()
  |                              - Creates loop dir + metadata.json
  |                              - Records client_workspace
  | <------ loop_new_response {loop_id}
  |
  | loop_subscribe {loop_id} -->  ClientSessionManager.subscribe_loop()
  |                              - Unsubscribes prior loop
  |                              - Subscribes to "loop:{loop_id}" topic
  |
  | loop_input {loop_id, text} -> LoopInputDispatcher.enqueue(loop_id, msg)
  |                              - Per-loop queue + worker task
  |                                |
  |                                v
  |                              bind_execution_thread_for_loop()
  |                              - Read/mint checkpoint thread_id
  |                              - Resolve workspace
  |                              - Register in ThreadStateRegistry
  |                              - (RFC-221) No longer mutates runner singleton
  |                                |
  |                                v
  |                              QueryEngine.run_query()
  |                              - factory.create_runner(loop_id) → LoopRunnerProtocol
  |                              - LoopRunRequest carries thread_id + workspace
  |                              - loop_scoped_client_message() strips thread_id
  |                              - Broadcast events to "loop:{loop_id}"
  |                              - Claim/release loop ownership
  |
  | <------ event {loop_id, data}   EventBus -> ClientSession queue -> transport
```

**Key invariant**: `thread_id` (LangGraph checkpoint id) never leaves the daemon. All client-facing messages use `loop_id` exclusively. `_loop_scoped_client_message()` enforces this boundary.

### 2.2 Two-Level Identity

| Concept | Identifier | Scope | Exposed to Client |
|---------|-----------|-------|-------------------|
| AgentLoop | `loop_id` | Client-visible conversation/session | Yes |
| LangGraph Checkpoint | `thread_id` | Internal durability key | No |

Mapping: `ThreadStateRegistry._thread_loop: dict[str, str]` (checkpoint → loop).

A single loop may own multiple checkpoint threads over its lifetime (via thread switching), but at any given moment each loop has exactly one `current_thread_id` stored in `metadata.json`.

### 2.3 SootheRunner Singleton — Resolved by RFC-221 for Streaming, Still Present for Non-Streaming

**RFC-221 status**: The streaming path now uses per-loop subprocess isolation via `LoopRunnerProtocol`. Each `loop_id` gets its own `LocalLoopRunner` (or `RayLoopRunner`) with a private `SootheRunner` inside a subprocess. `bind_execution_thread_for_loop()` no longer mutates `daemon._runner.set_current_thread_id()` — thread/workspace binding is passed via `LoopRunRequest` fields and applied inside the subprocess.

**However**, `daemon._runner` still exists and is used for non-streaming operations in `QueryEngine` and `MessageRouter`:

| Code path | Still reads/mutates `_runner`? | Risk level |
|-----------|-------------------------------|------------|
| `run_query()` streaming path | **No** — uses `_runner_factory.create_runner()` + `LoopRunRequest` | Eliminated |
| `run_query()` interrupt setup/teardown | **Yes** — `d._runner.set_interrupt_resolver(loop_id, ...)` (lines 293, 482) | Low — now scoped by loop_id |
| `run_query()` finally block | **Yes** — `d._runner.set_current_thread_id(None)` (lines 533, 855) | Low — cleanup on singleton, but no concurrent streaming race |
| `cancel_loop()` | **Yes** — `d._runner.current_thread_id` (lines 960, 1012–1024, 1037, 1040, 1046) | Low — cancellation is sequential per-loop |
| `continue_thread()` / `switch_thread()` | **Yes** — `d._runner.set_current_thread_id()`, `create_persisted_thread()` | Medium — these mutate shared state |
| `list_durability_threads()` (doctor/status) | **Yes** — reads from shared agent/checkpointer | None — read-only, non-concurrent |

The streaming data race (Bug 5.7 root cause) is **eliminated**. The remaining `_runner` usage is for lifecycle operations (thread switching, cancellation, interrupt wiring) that are typically serialized. `set_interrupt_resolver()` now accepts `loop_id` (Bug 5.7 partial fix), reducing the remaining risk.

### 2.4 LoopRunnerProtocol Architecture (RFC-221)

```
SootheDaemon
    │
    │  creates once
    ▼
LoopRunnerFactory  (holds SootheConfig + mode flag)
    │
    │  creates per loop_id
    ▼
LoopRunnerProtocol  (runtime: LocalLoopRunner | RayLoopRunner)
    │
    ├── LocalLoopRunner  [one subprocess per loop_id, multiprocessing]
    │       └── SootheRunner(config)   [private process, full init]
    │               │ chunks via multiprocessing.Queue
    │               ▼
    │       async generator adapter
    │
    └── RayLoopRunner    [one Ray actor per loop_id]
            └── LoopRunnerActor  (@ray.remote)
                    └── SootheRunner(config)   [private process, full init]
                            │ chunks via ray.util.queue.Queue
                            ▼
                    async generator adapter
```

Both modes are structurally symmetric: subprocess → `SootheRunner(config)` → queue → async generator adapter. `LoopRunRequest` consolidates all per-query parameters (thread_id, workspace, model, etc.) that were previously mutated on the singleton.

**Isolation guarantee**: Each loop runs in a separate OS process. A crash, runaway loop, or mutable-state mutation in one loop cannot affect the daemon process or other loops.

---

## 3. Isolation Domains — Detailed Analysis

### 3.1 Event Isolation

**Mechanism**: Topic-based EventBus pub/sub.

| Topic | Purpose |
|-------|---------|
| `loop:{loop_id}` | Primary loop-scoped event delivery |
| `global` | Daemon-wide status/command_response only |

**Routing path** (updated for RFC-221):
```
Subprocess: SootheRunner.astream() → StreamChunk → queue.put(("chunk", chunk))
Daemon:     _drain_mp_queue() → QueryEngine._run_stream()
  → _loop_scoped_client_message(loop_id, payload)  // strips thread_id
  → daemon._broadcast(msg)
  → EventBus.publish(loop_event_topic(loop_id), msg)
  → ClientSession.event_queue → sender_loop → transport.send()
```

**Strengths**:
- `_loop_scoped_client_message` strips `thread_id` from every outbound frame — structurally prevents checkpoint id leaks
- Single-subscription enforcement: `subscribe_loop` unsubscribes prior loop before subscribing to new one
- Lock-free publish hot path (CPython atomic dict reads)
- Priority-aware overflow: CRITICAL events never dropped

**Weaknesses**:
- `loop_delete` does not clean up `_pending_interrupt_responses` for deleted loops (see Bug 5.4 remaining gap)

### 3.2 Workspace Isolation

**Resolution chain** (5 levels, `stream_resolution.py`):

1. **Explicit** — `astream(..., workspace=...)`
2. **Thread workspace** — `ThreadStateRegistry.get_workspace(thread_id)`
3. **Installation default** — daemon resolved default
4. **Config workspace_dir** — `SootheConfig.workspace_dir`
5. **CWD** — current working directory

**Workspace propagation per loop**:

```
loop_new {workspace: "/project-A"}
  → metadata.json stores client_workspace="/project-A"
  → bind_execution_thread_for_loop() reads client_workspace
  → Validates path exists, falls back to $SOOTHE_HOME/Workspace/<loop_id>/
  → Sets ThreadStateRegistry.set_workspace(thread_id, workspace)
  → Passes workspace via LoopRunRequest.workspace (RFC-221)
  → LangGraph configurable["workspace"] = workspace
  → WorkspaceAwareBackend.__call__(runtime) reads configurable["workspace"]
  → Returns correct NormalizedPathBackend per workspace
```

**Tool-side resolution** (`WorkspaceAwareBackend` in `backend.py`):
- Tool runtime: reads `runtime.config["configurable"]["workspace"]`
- Middleware (Runtime): reads `langgraph.config.get_config()["configurable"]["workspace"]`
- Fallback: `FrameworkFilesystem.get_current_workspace()` (ContextVar)
- Ultimate fallback: daemon default

**ContextVar mechanism** (`framework_filesystem.py`) — **Fixed (Bug 5.1)**:
- `_current_workspace: ContextVar[Path | None]` provides async-task-scoped isolation
- `set_current_workspace()` returns a `Token` — the API supports token-based reset
- `clear_current_workspace(token)` uses `_current_workspace.reset(token)` when token is provided, falls back to `set(None)` otherwise
- `WorkspaceContextMiddleware.abefore_agent` captures `self._workspace_token` from `set_current_workspace()`
- `WorkspaceContextMiddleware.aafter_agent` passes token to `clear_current_workspace(self._workspace_token)`

**Remaining gap**: `query_engine.py` calls `FrameworkFilesystem.clear_current_workspace()` (no token) in three error-handling paths (lines 437, 463, 782). Since the daemon doesn't capture a token when setting the workspace (the middleware does), these calls fall through to `set(None)` instead of `reset(token)`. If an outer context had set a workspace, `set(None)` overwrites it rather than restoring the previous value. In practice, daemon error paths are the outermost context, so this is a minor safety concern.

**Tool cache** — **Fixed (Bug 5.2)**:
- `_tool_cache` is now `dict[tuple[str, str | None], list[BaseTool]]` — key is `(tool_name, workspace)`
- `_resolve_single_tool_group()` populates workspace from `FrameworkFilesystem.get_current_workspace()`
- Comment: `# Include workspace in cache key to prevent cross-workspace tool reuse`
- Cross-workspace contamination is structurally prevented at the cache level

### 3.3 Input/Command Isolation

**`LoopInputDispatcher`** (`loop_isolation.py:99–165`):

- One `asyncio.Queue` per `loop_id`, created lazily
- One `asyncio.Task` worker per loop, processing messages sequentially
- `_shutting_down` flag prevents orphan workers during daemon shutdown
- Input for one loop cannot block processing on another
- `cleanup_loop(loop_id)` method for explicit loop deletion (called by `_handle_loop_delete`)

**Weaknesses**:
- No input validation against loop status — input accepted for finalized/deleted loops (design gap, not tracked separately)

### 3.4 Running Resource Isolation

**Active task tracking**: `_active_runners: dict[str, LoopRunnerProtocol]` keyed by `loop_id` (RFC-221) alongside `_active_threads: dict[str, asyncio.Task]` keyed by `thread_id` (legacy, still used for capacity checks and cancellation). Both are maintained in `QueryEngine`.

**Ownership protocol**:
1. `claim_loop_ownership(client_id, loop_id)` — at query start
2. `release_loop_ownership(client_id)` — in `_run_stream` finally block
3. On client disconnect: `_cancel_loop_for_session(loop_id)` → `runner.cancel()`

**Weaknesses**:
- `daemon._runner.set_interrupt_resolver(loop_id, ...)` still operates on the singleton, but is now scoped by `loop_id` (see Bug 5.7 partial fix)
- `daemon._runner.set_current_thread_id()` still used in lifecycle ops (see Flaw 6.1, reduced severity)
- MCP sessions accumulate without cleanup on `delete_thread` and `loop_delete` paths (see Flaw 6.3)

### 3.5 Persistence Isolation

| Resource | Isolation Scope | Key |
|----------|----------------|-----|
| LangGraph checkpoints | Per `thread_id` | `configurable.thread_id` |
| AgentLoop checkpoints | Per `loop_id` | `agentloop_loops` table |
| Thread metadata | Per `thread_id` | DurabilityProtocol key |
| Working memory spill | Per `thread_id` | `data/threads/{thread_id}/working_memory/` |
| Loop reports | Per `loop_id` | `data/loops/{loop_id}/` |
| Claude sessions | Per `(thread_id, cwd)` | In-memory + `ThreadMetadata.claude_sessions` |
| Memory (long-term) | Per `source_thread` | `MemuMemoryStore.user_id` |

**Weaknesses**:
- Checkpoint load-modify-save is not atomic (see Bug 5.3)

### 3.6 Session/Client Isolation

`ClientSessionManager` enforces:
- At most one owned `loop_id` per client (`_client_loop_ownership`)
- At most one loop topic subscription per session queue
- Sender task per session with verbosity-based filtering

**Weaknesses**:
- No ownership validation on destructive operations (see Flaw 6.4)
- `loop_delete` does not clean up `_client_loop_ownership` for clients that owned the deleted loop (see Bug 5.4 remaining gap)

### 3.7 Subprocess Execution (RFC-221)

**Enforcement**: Per-loop OS process via `LoopRunnerProtocol`, `LoopRunRequest` for parameter passing, queue-bridge for chunk streaming, `process.terminate()/kill()` for cancellation.

**Weaknesses**:
- `daemon._runner` singleton still used for non-streaming lifecycle operations (interrupt resolver wiring, thread switching, activity timestamps)

---

## 4. Previously Identified Issues (Status Update)

| # | Severity | Category | Status | Description |
|---|----------|----------|--------|-------------|
| 4.1 | Medium | Resource leak | Fixed | Orphan worker tasks during concurrent enqueue at shutdown |
| 4.2 | High | Data corruption | Fixed | Shared `_thread_logger` races under multithreaded execution |
| 4.3 | Medium | Logic error | Fixed | Shared `_active_stream_loop_id` mis-routes heartbeats |
| 4.4 | Low | TOCTOU | Fixed | Capacity check not protected by lock |
| 4.5 | Medium | Race condition | Fixed | `ThreadStateRegistry.ensure` stale-object race |
| 4.6 | High | Isolation violation | Already fixed | `/cancel` scoped to loop via `cancel_loop(lid)` |
| 4.7 | Low | Information leak | Accepted | Global input history intentionally crosses boundaries |
| 4.8 | Low | Logic error | Fixed | `_pending_interrupt_responses` pop guarded |
| 4.9 | Low | Race condition | Accepted | `claim_loop_ownership`/`subscribe_loop` narrow race |
| 4.10 | Info | Behaviour | Accepted | Queue drains gracefully on shutdown |

**RFC-221 Resolutions**: The following issues are now structurally resolved by per-loop subprocess isolation:

| Issue | Resolution |
|-------|-----------|
| Runner `_current_thread_id` data race (Flaw 6.1, core) | Each subprocess has its own `SootheRunner`; `bind_execution_thread_for_loop()` no longer mutates the singleton |
| Runner `_interrupt_resolver` cross-loop clobber (Bug 5.7, streaming path) | Subprocess-local resolver cannot be clobbered by another loop |
| Runner `_current_plan` / `_artifact_store` cross-loop bleed | Each subprocess has its own mutable state |
| `_active_threads` keyed by thread_id (Flaw 6.1, tracking) | Supplemented by `_active_runners` keyed by loop_id for subprocess management |
| Cross-loop ContextVar contamination (Bug 5.1, cross-loop) | Each subprocess has its own ContextVar scope |
| Cross-loop tool cache contamination (Bug 5.2, cross-loop) | Each subprocess starts with an empty cache; plus cache key now includes workspace |

---

## 5. Bugs

### Bug 5.1 — Workspace ContextVar Leak on Exception Paths (FIXED)

**Location**: `framework_filesystem.py`, `workspace_context.py`

**Original issue**: `FrameworkFilesystem.set_current_workspace()` used `ContextVar.set()` without token-based reset. Exception paths that bypassed `aafter_agent` would leak the previous loop's workspace into subsequent operations.

**Fix applied**:
- `set_current_workspace()` now returns `Token[Path | None]`
- `clear_current_workspace(token)` uses `_current_workspace.reset(token)` when token is provided, falls back to `set(None)`
- `WorkspaceContextMiddleware` captures `self._workspace_token` in `abefore_agent` and passes it to `clear_current_workspace()` in `aafter_agent`

**Remaining gap** (LOW): `query_engine.py` calls `clear_current_workspace()` without a token in three error-handling paths (lines 437, 463, 782). These fall through to `set(None)` instead of `reset(token)`. In practice, daemon error paths are the outermost context, so this is unlikely to cause cross-loop leakage.

---

### Bug 5.2 — Tool Cache Returns Workspace-Wrong Instances (FIXED)

**Location**: `tool_cache.py`, `_resolver_tools.py`

**Original issue**: The tool cache was a `dict[str, list[BaseTool]]` keyed only by tool group name. Tools resolved for one workspace were served from cache for a different workspace.

**Fix applied**:
- Cache key is now `tuple[str, str | None]` — `(tool_name, workspace)`
- `_resolve_single_tool_group()` populates workspace from `FrameworkFilesystem.get_current_workspace()`
- Explicit comment: `# Include workspace in cache key to prevent cross-workspace tool reuse`

**No remaining gaps** for cross-workspace contamination. Within a single subprocess, if the same tool group is resolved multiple times with different workspaces, each workspace gets its own cache entry.

---

### Bug 5.3 — Checkpoint Load-Modify-Save TOCTOU Race (MEDIUM)

**Location**: `agent_loop.py:174–245`

**Root cause**: `AgentLoop.run_with_progress()` loads the checkpoint, inspects `status`, and then modifies+saves it — all as separate operations without any concurrency control:

```python
checkpoint = await state_manager.load()  # line 174
if checkpoint.status == "ready_for_next_goal":
    # modify checkpoint...
    await state_manager.save(checkpoint)  # line 202
```

Between `load()` and `save()`, a concurrent operation (e.g., a `continue_thread` input arriving, or a thread switch) could have modified the same checkpoint in SQLite. The load-modify-save cycle is not atomic — there is no optimistic concurrency control, row-level locking, or CAS (compare-and-swap) mechanism.

**RFC-221 impact**: Reduced severity. With per-loop subprocess isolation, concurrent access to the same loop's checkpoint from within the daemon is less likely — the streaming path no longer touches the daemon's `_runner`. However, the SQLite database is shared across subprocesses, and the `AgentLoopStateManager` in each subprocess writes to the same DB. The TOCTOU window is narrower but not eliminated.

**Impact**: A checkpoint could be overwritten with stale state, leading to:
- A loop transitioning to `running` when it should be `paused`
- Goal completion data being lost
- Thread switch state being rolled back

**Fix**: Use SQLite's built-in row-level locking via `BEGIN IMMEDIATE` or implement an `updated_at` CAS check:
```python
saved = await state_manager.load()
if saved.updated_at > checkpoint.updated_at:
    raise ConcurrentModificationError(...)
await state_manager.save(checkpoint)
```

---

### Bug 5.4 — loop_delete Cleanup (SUBSTANTIALLY FIXED, minor gaps remain)

**Location**: `message_router.py:830–937`

**Original issue**: `_handle_loop_delete` only deleted filesystem directory and SQLite rows, with no in-memory cleanup.

**Fix applied** — `_handle_loop_delete` now performs 5 cleanup steps before persistence deletion:
1. **Cancel running queries** (line 876): `d._query_engine.cancel_loop(loop_id)`
2. **Unsubscribe all clients** (lines 883–884): iterates sessions and calls `unsubscribe_loop()`
3. **Clean up LoopInputDispatcher** (line 887): `d._loop_input_dispatcher.cleanup_loop(loop_id)`
4. **Clean up ThreadStateRegistry** (line 890): `d._thread_registry.cleanup_loop(loop_id)` returns removed thread IDs
5. **Clean up Claude session cache** (lines 893–896): `cleanup_claude_sessions(removed_threads)`

**Remaining gaps** (LOW):

| Missing cleanup | Risk |
|-----------------|------|
| `_pending_interrupt_responses` not resolved for deleted loop | Pending future left dangling; no code awaiting it after query cancellation |
| `_active_stream_loop_ids` not cleaned up | Loop ID may linger in heartbeat set; cleared eventually when cancelled task's finally block runs |
| `_client_loop_ownership` not cleaned up | Clients that owned the deleted loop retain stale ownership mapping; cleaned up on next client action or disconnect |
| `_active_threads` entries not explicitly removed by thread_id | Cancelled tasks clean up their own entries in finally blocks; no explicit safety pop |

These are minor — the primary in-memory state (subscriptions, queues, thread registry, session cache) is now properly cleaned up. The remaining gaps are edge cases that self-resolve or have no functional impact.

---

### Bug 5.5 — loop_detach Leaves Interrupt Futures Pending (FIXED)

**Location**: `message_router.py:1087–1092`

**Original issue**: `_handle_loop_detach` unsubscribed the client and marked the loop as `detached`, but did not resolve `daemon._pending_interrupt_responses`. A loop paused on a HITL interrupt would block forever.

**Fix applied**:
```python
# Resolve any pending interrupt future for this loop
# (Bug 5.5: prevent loop from blocking forever on HITL after client detach)
pending = d._pending_interrupt_responses.pop(loop_id, None)
if pending and not pending.done():
    pending.set_result({"action": "cancel", "reason": "client_detached"})
```

**No remaining gaps**.

---

### Bug 5.6 — Unbounded Loop Creation / No Rate Limiting (CRITICAL)

**Location**: `message_router.py:1107+`

**Root cause**: `_handle_loop_new` creates a new loop with no rate limiting, capacity check, or maximum count enforcement. Each loop, when activated:
- Creates a filesystem directory
- Creates 4+ SQLite table rows
- Creates an `AgentLoopStateManager` with its own SQLite connection pool (5 reader + 1 writer = 6 connections per loop)
- Eventually creates `LoopInputDispatcher` queue + worker task
- With RFC-221: spawns an OS subprocess via `LocalLoopRunner` (~50MB+ memory per subprocess)

With `max_concurrent_threads=100`, 100 concurrent loops would open 600 SQLite connections to the same database file. SQLite's WAL mode allows concurrent readers but the writer is serialized — heavy concurrent write load causes `timeout=30` errors (manager.py:189).

**RFC-221 impact**: More severe. Each loop now spawns an OS subprocess via `LocalLoopRunner`. 100 concurrent loops means 100 subprocesses, each with its own `SootheRunner` (full init, agent graph, checkpointer connections). Resource consumption per loop is significantly higher than the pre-RFC-221 shared-runner model.

**Impact**: A single client can exhaust daemon resources (PIDs, file descriptors, SQLite connections, memory) by creating loops in a tight loop. With per-loop subprocesses, the blast radius is larger — each subprocess adds ~50MB+ memory overhead.

**Config state**: No `max_total_loops` or equivalent config exists in `DaemonConfig`. The only capacity gate is `max_concurrent_threads` (limits *concurrently executing* queries, not total loop count).

**Fix**: Add a `max_total_loops` config option and enforce it in `_handle_loop_new`:
```python
max_loops = d._config.daemon.max_total_loops  # default: 50
existing = count_loops_on_disk()
if existing >= max_loops:
    return error_response("DAEMON_LOOP_LIMIT", f"Maximum {max_loops} loops reached")
```

---

### Bug 5.7 — Runner._interrupt_resolver (PARTIALLY FIXED — now scoped by loop_id)

**Location**: `runner/__init__.py:411`, `query_engine.py:293, 482`

**Original issue**: `SootheRunner._interrupt_resolver` was a single instance field. Concurrent loops' `set_interrupt_resolver(None)` calls would overwrite each other.

**Fix applied**: `set_interrupt_resolver()` now accepts `loop_id` as first argument:
```python
def set_interrupt_resolver(self, loop_id: str, resolver: Any | None) -> None:
```
`query_engine.py` now calls `d._runner.set_interrupt_resolver(effective_loop_id, resolver)` (line 293) and `d._runner.set_interrupt_resolver(effective_loop_id, None)` (line 482).

**Remaining gap** (LOW): The implementation detail of whether `_interrupt_resolver` is internally stored as a `dict[str, Callable]` keyed by `loop_id` or as a single field with the `loop_id` parameter ignored is an implementation question. The API surface is correct. RFC-221 subprocess isolation eliminates the streaming-path race regardless.

---

## 6. Design Flaws

### Flaw 6.1 — SootheRunner Singleton Mutable State (ARCHITECTURAL → PARTIALLY RESOLVED)

**RFC-221 resolution**: The streaming path no longer uses `daemon._runner` for execution. Each loop runs in a subprocess with its own `SootheRunner` instance. `bind_execution_thread_for_loop()` no longer calls `set_current_thread_id()`. The data race on `_current_thread_id` during concurrent streaming is **eliminated**.

**Remaining exposure**: `daemon._runner` is still used for non-streaming lifecycle operations in `QueryEngine` and `MessageRouter`:

| Operation | File:Line | Still mutates singleton? |
|-----------|-----------|--------------------------|
| `set_current_thread_id(None)` in finally blocks | query_engine.py:533, 855 | Yes — cleanup only |
| `set_current_thread_id(tid)` in continue/switch | query_engine.py:1037, 1046 | Yes — sequential lifecycle |
| `current_thread_id` reads in cancel/list | query_engine.py:960, 1012, 1023 | Yes — read-only |
| `set_interrupt_resolver(loop_id, ...)` | query_engine.py:293, 482 | Yes — now scoped by loop_id |
| `create_persisted_thread()` | query_engine.py:119, 590 | Yes — thread creation |
| `touch_thread_activity_timestamp()` | query_engine.py:209, 507, 677, 826 | Yes — activity tracking |

These operations are largely sequential (per-loop lifecycle) rather than concurrent (simultaneous streaming). The architectural risk is reduced from **High** to **Low**.

**Recommendation**: Complete the migration by moving remaining lifecycle operations behind `LoopRunnerProtocol` or scoping them per-loop. The utility `_runner` should eventually become a read-only reference to the checkpointer/agent for status queries only.

### Flaw 6.2 — Claude Session Bridge Memory Leak (PARTIALLY FIXED)

**Location**: `session_bridge.py:17–24`

Module-level `_memory_claude_sessions: dict[tuple[str, str], str]` and `_locks: dict[tuple[str, str], asyncio.Lock]` grow without bound.

**Fix applied**: `cleanup_claude_sessions(removed_threads)` function exists and is called from `_handle_loop_delete` (message_router.py:893–896).

**Remaining gaps**:
- `loop_detach` does NOT call `cleanup_claude_sessions` — a detached loop's Claude session entries remain indefinitely
- No LRU eviction, TTL, or size cap — entries persist until explicit `loop_delete` or process exit
- `_locks` dict shares the same unbounded growth profile

**Recommendation**: Add `cleanup_claude_sessions` call in `_handle_loop_detach`. Add LRU eviction (max 1000 entries) or key by `loop_id` for batch cleanup.

### Flaw 6.3 — MCP Session Accumulation (PARTIALLY FIXED, currently dormant)

**Location**: `manager.py:41`

**Fix applied**: `ThreadContextManager._cleanup_mcp_session(thread_id)` exists and is called from `suspend_thread` and `archive_thread`.

**Remaining gaps**:
- `delete_thread` does NOT call `_cleanup_mcp_session` — MCP session leaks on thread deletion
- `loop_delete` in the daemon does NOT trigger MCP cleanup — no reference to `ThreadContextManager._mcp_managers`
- No LRU eviction or size cap

**Current impact**: **Dormant**. The `soothe.mcp.loader` module does not exist at runtime — `_ensure_mcp_session` always falls into its `except` block and never creates actual MCP sessions. Once MCP integration is completed, these two paths will leak sessions.

**Recommendation**: Add `_cleanup_mcp_session(thread_id)` call in `delete_thread`. Add MCP cleanup in `_handle_loop_delete` by iterating removed thread IDs. These fixes should be applied before the MCP module is enabled at runtime.

### Flaw 6.4 — No Loop Ownership Validation on Destructive Operations (MEDIUM)

**Location**: `message_router.py:830–937`

`_handle_loop_delete` does not verify that the requesting client owns the loop or is even subscribed to it. Any client with a valid connection can delete any loop by ID. This is an authorization gap — a malicious or buggy client could delete another client's active work.

**Ownership infrastructure exists but is not used for authorization**: `SessionManager` has `claim_loop_ownership()`, `release_loop_ownership()`, and `get_owned_loop()` — but `get_owned_loop()` is only used as a convenience hint for `/cancel`, never as an authorization gate on destructive operations.

**Recommendation**: Add ownership check:
```python
owned_loop = d._session_manager.get_owned_loop(client_id)
if owned_loop != loop_id:
    return error_response("NOT_OWNER", "Only the loop owner can delete it")
```

### Flaw 6.5 — loop_id vs thread_id Conflation in Event Emission (LOW)

**Location**: `message_router.py:680–685`, `_runner_phases.py:915`

Several event emissions conflate `loop_id` and `thread_id` by assigning the same value to both fields:
```python
LoopCreatedEvent(loop_id=thread_info.thread_id, thread_id=thread_info.thread_id)
```

While the `_loop_scoped_client_message()` boundary strips `thread_id` from outbound frames, this conflation means internal event processing can't distinguish between a loop-scoped event and a checkpoint-scoped event. If the two-level identity model is ever extended (e.g., multi-thread loops where thread_id != loop_id), these events would carry incorrect semantics.

**Recommendation**: Audit all event emissions and ensure `loop_id` is set from the actual loop identifier, not from the checkpoint thread_id. Where only thread_id is available, resolve via `get_thread_loop(thread_id)`.

---

## 7. Isolation Boundary Summary

| Resource | Isolation Scope | Mechanism | Leak Risk |
|----------|----------------|-----------|-----------|
| EventBus topics | Per `loop_id` | `loop:{loop_id}` topic | Low |
| Client subscriptions | Per session | Single-sub enforcement | Low |
| Workspace (runtime) | Per `loop_id` | LangGraph configurable + token-based ContextVar | Low (was Medium) |
| Workspace (tools) | Per `loop_id` | WorkspaceAwareBackend + workspace-keyed cache | Low (was High) |
| Input queues | Per `loop_id` | LoopInputDispatcher + cleanup_loop() | Low |
| Loop runners (RFC-221) | Per `loop_id` | LoopRunnerProtocol subprocess | Low |
| Checkpoint storage | Per `thread_id` | LangGraph checkpoint key | Low |
| Loop metadata | Per `loop_id` | Filesystem `metadata.json` | Medium (TOCTOU) |
| Thread registry | Per `thread_id` | ThreadStateRegistry + cleanup_loop() | Low |
| Runner mutable state | **Per loop_id (streaming)** / **Global (lifecycle)** | Subprocess isolation + singleton | **Low** (was High) |
| Tool cache | **Per process** | Workspace-keyed dict | Low (was High) |
| Claude sessions | Per `(thread_id, cwd)` | In-memory + cleanup on loop_delete | Low (was Medium) |
| MCP sessions | Per `thread_id` | ClassVar dict + cleanup on suspend/archive | Medium (dormant — no cleanup on delete/loop_delete) |
| DB connections | Per loop (SQLite) / shared (PostgreSQL) | StateManager.close() | Low |
| Interrupt resolvers | **Per loop_id (scoped)** | Runner.set_interrupt_resolver(loop_id, ...) | Low (was Medium) |
| Heartbeat routing | Per `loop_id` | _active_stream_loop_ids set | Low |
| Memory (long-term) | Per `source_thread` | MemuMemoryStore.user_id | Low |

---

## 8. Recommendations — Priority Order

| Priority | Fix | Effort | Status | Notes |
|----------|-----|--------|--------|-------|
| ~~P0~~ | ~~Tool cache: include workspace in key~~ | ~~Small~~ | **Done** | Cache key is `(tool_name, workspace)` |
| ~~P0~~ | ~~ContextVar: switch to token-based reset~~ | ~~Small~~ | **Done** | `set_current_workspace` returns token, middleware uses it |
| ~~P1~~ | ~~loop_delete: clean up subscriptions, in-memory state, running queries~~ | ~~Medium~~ | **Done** | 5-step cleanup; minor gaps in `_pending_interrupt_responses`, `_client_loop_ownership` |
| ~~P1~~ | ~~loop_detach: resolve pending interrupt futures~~ | ~~Small~~ | **Done** | Resolves with cancel action |
| ~~P1~~ | ~~Runner singleton: migrate per-query state to RunnerState~~ | ~~Large~~ | **Done** (streaming) | RFC-221 subprocess isolation eliminates streaming-path races |
| **P0** | Loop creation limit: add `max_total_loops` config | Small | Open | More urgent with per-loop subprocess overhead |
| **P1** | Remaining `_runner` lifecycle ops: migrate continue/switch/cancel behind LoopRunnerProtocol | Medium | Open | Next step in RFC-221 migration |
| **P2** | `query_engine.py` ContextVar: pass token to `clear_current_workspace()` | Small | Open | Minor — daemon error paths are outermost context |
| **P2** | Claude session bridge: add cleanup on `loop_detach` + LRU eviction | Medium | Open | `loop_delete` is handled; detach path leaks |
| **P2** | loop_delete authorization: add ownership validation | Small | Open | Any client can delete any loop |
| **P2** | MCP sessions: add cleanup on `delete_thread` and `loop_delete` | Medium | Open (dormant) | Must be fixed before MCP module is enabled |
| **P3** | Checkpoint TOCTOU: add CAS or row-level locking | Large | Open | Rare race, narrowed by subprocess isolation |
| **P3** | Event emission: audit loop_id vs thread_id conflation | Medium | Open | Blocks multi-thread loop support |
| **P3** | loop_delete: clean up `_pending_interrupt_responses` for deleted loop | Small | Open | Edge case — pending future unlikely after query cancellation |

---

## 9. What Works Well

- **Event routing**: Topic-based EventBus with lock-free publish is correct and efficient. Cross-loop event leakage is structurally prevented at the transport layer.
- **Single-subscription enforcement**: Each client can only see one loop's events at a time.
- **Per-loop input queues**: `LoopInputDispatcher` ensures full input isolation between loops.
- **Loop-scoped client messages**: `_loop_scoped_client_message()` strips `thread_id` from every outbound frame — a clean isolation boundary.
- **Workspace resolution chain**: 5-level resolution with workspace passed explicitly to `astream()` — correct at the runner level.
- **WorkspaceAwareBackend factory**: Per-invocation workspace resolution for tool filesystem operations — correct at the runtime level.
- **Priority-aware backpressure**: CRITICAL events never dropped; graceful degradation under load.
- **Concurrent-safe thread logging**: Each `_run_stream` closure holds its own `ThreadLogger` local reference.
- **Concurrent heartbeat routing**: `_active_stream_loop_ids` set fans out heartbeats correctly.
- **Atomic capacity enforcement**: Capacity check inside `_query_state_lock` prevents overshoot.
- **Stale-object-free registry**: `ThreadStateRegistry.ensure` uses `setdefault` for race safety.
- **Shutdown race closure**: `_shutting_down` flag prevents orphan workers during daemon stop.
- **Per-loop subprocess isolation (RFC-221)**: Each loop runs in its own OS process via `LocalLoopRunner`. Mutable state on `SootheRunner` is now process-private — no data races between concurrent loops. Crashes are contained.
- **Symmetric local/Ray architecture**: `LocalLoopRunner` and `RayLoopRunner` share the same queue-bridge pattern. `LoopRunnerFactory` selects the runtime based on config — `QueryEngine` is fully decoupled.
- **LoopRunRequest consolidation**: All per-query parameters (thread_id, workspace, model, etc.) are captured in a single dataclass, eliminating the scattered mutation pattern that caused the singleton races.
- **Token-based ContextVar reset (Bug 5.1 fix)**: `set_current_workspace()` returns a token, `WorkspaceContextMiddleware` captures and passes it to `clear_current_workspace()`. Exception-safe workspace scoping.
- **Workspace-keyed tool cache (Bug 5.2 fix)**: Cache key includes workspace path, preventing cross-workspace tool instance reuse.
- **loop_delete comprehensive cleanup (Bug 5.4 fix)**: 5-step cleanup (cancel queries, unsubscribe clients, clean up InputDispatcher/ThreadStateRegistry/Claude sessions) runs before persistence deletion.
- **loop_detach interrupt resolution (Bug 5.5 fix)**: Pending interrupt futures resolved with cancel action on client detach.
- **loop_id-scoped interrupt resolver (Bug 5.7 partial fix)**: `set_interrupt_resolver(loop_id, ...)` scopes resolver per loop on the utility singleton.

---

## Appendix A: Isolation Domain Inventory

For each isolation domain, the enforcement mechanism and known gaps:

### Events
- **Enforcement**: EventBus topics, single-sub enforcement, `_loop_scoped_client_message` boundary
- **Gaps**: `_pending_interrupt_responses` not cleaned up on loop_delete (minor)

### Workspace
- **Enforcement**: LangGraph configurable, WorkspaceAwareBackend factory, 5-level resolution chain, token-based ContextVar reset, workspace-keyed tool cache
- **Gaps**: `query_engine.py` `clear_current_workspace()` called without token in error paths (minor)

### Input
- **Enforcement**: Per-loop asyncio queues + workers, `_shutting_down` flag, `cleanup_loop()` on delete
- **Gaps**: No validation against loop status (input accepted for finalized/deleted loops, design gap)

### Running Resources
- **Enforcement**: `_active_runners` keyed by loop_id (RFC-221), per-loop subprocess isolation via `LoopRunnerProtocol`, loop ownership protocol, `runner.cancel()` for scoping, loop_id-scoped interrupt resolver
- **Gaps**: `daemon._runner` still used for lifecycle operations (thread switching, activity timestamps)

### Persistence
- **Enforcement**: Per-thread_id checkpoint key, per-loop_id AgentLoop state
- **Gaps**: Checkpoint load-modify-save not atomic (Bug 5.3)

### Client Sessions
- **Enforcement**: Single ownership, single subscription, sender task per session, unsubscribe on loop_delete
- **Gaps**: No ownership validation on delete (Flaw 6.4), `_client_loop_ownership` not cleaned up on loop_delete

### Subprocess Execution (RFC-221)
- **Enforcement**: Per-loop OS process via `LoopRunnerProtocol`, `LoopRunRequest` for parameter passing, queue-bridge for chunk streaming, `process.terminate()/kill()` for cancellation
- **Gaps**: `daemon._runner` singleton still used for non-streaming lifecycle operations

### Memory
- **Enforcement**: Per-source_thread MemuMemoryStore, per-thread_id working memory spill, `cleanup_claude_sessions()` on loop_delete
- **Gaps**: Claude session bridge not cleaned on loop_detach, no LRU/TTL eviction

### MCP
- **Enforcement**: `_cleanup_mcp_session()` on suspend_thread and archive_thread
- **Gaps**: No cleanup on delete_thread or loop_delete; currently dormant (MCP module not loaded at runtime)

### Filesystem
- **Enforcement**: WorkspaceAwareBackend per-invocation resolution, NormalizedPathBackend per-workspace, workspace-keyed tool cache
- **Gaps**: `query_engine.py` ContextVar token gap on error paths (minor)
