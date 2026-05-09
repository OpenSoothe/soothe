# Loop-Based Isolation in the Daemon — Deep Analysis

> Scope: `packages/soothe/src/soothe/daemon/` (primary), cross-references to
> `packages/soothe/src/soothe/core/`, `packages/soothe-cli/`, `packages/soothe-sdk/`.
> Date: 2026-05-09
> Updated: 2026-05-09 (RFC-221 LoopRunnerProtocol integration)

---

## 1. Executive Summary

The Soothe daemon implements loop-based isolation where each **AgentLoop** (`loop_id`) serves as the primary unit of client work. The isolation architecture is layered across six domains: events, workspace, input dispatch, running resources, persistence, and client sessions.

The design is **architecturally sound** at the transport layer — the EventBus topic-based routing, single-subscription enforcement, and `_loop_scoped_client_message` boundary structurally prevent event leakage between loops. Several previously identified bugs (4.1–4.5) have been fixed.

**RFC-221** (`LoopRunnerProtocol`) has been introduced to address the root cause of the most severe isolation violations: the `SootheRunner` singleton's shared mutable state. Per-loop subprocess isolation (via `LocalLoopRunner` / `RayLoopRunner`) eliminates the data race on `_current_thread_id`, `_interrupt_resolver`, and other per-query fields. The original 7 bugs and 5 design flaws are updated: 4 bugs have reduced severity (5.1, 5.3, 5.6 worsened, 5.7), 1 flaw is partially resolved (6.1), and the highest-priority recommendation (runner singleton migration) is now complete for the streaming path. Remaining gaps stem from the hybrid state where `daemon._runner` is still used for non-streaming lifecycle operations.

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
| `run_query()` interrupt setup/teardown | **Yes** — `d._runner.set_interrupt_resolver()` (lines 293, 482) | Medium — resolver set/cleared on utility singleton |
| `run_query()` finally block | **Yes** — `d._runner.set_current_thread_id(None)` (lines 533, 855) | Low — cleanup on singleton, but no concurrent streaming race |
| `cancel_loop()` | **Yes** — `d._runner.current_thread_id` (lines 960, 1012–1024, 1037, 1040, 1046) | Low — cancellation is sequential per-loop |
| `continue_thread()` / `switch_thread()` | **Yes** — `d._runner.set_current_thread_id()`, `create_persisted_thread()` | Medium — these mutate shared state |
| `list_durability_threads()` (doctor/status) | **Yes** — reads from shared agent/checkpointer | None — read-only, non-concurrent |

The streaming data race (Bug 5.7 root cause) is **eliminated**. The remaining `_runner` usage is for lifecycle operations (thread switching, cancellation, interrupt wiring) that are typically serialized. However, `set_interrupt_resolver()` on the singleton is still a concurrency hazard if two loops hit HITL simultaneously.

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
- Dangling subscriptions after `loop_delete` (see Bug 5.4)
- `loop_detach` does not resolve pending interrupt futures (see Bug 5.5)

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
  → Passes workspace to runner.astream(workspace=...)
  → LangGraph configurable["workspace"] = workspace
  → WorkspaceAwareBackend.__call__(runtime) reads configurable["workspace"]
  → Returns correct NormalizedPathBackend per workspace
```

**Tool-side resolution** (`WorkspaceAwareBackend` in `backend.py`):
- Tool runtime: reads `runtime.config["configurable"]["workspace"]`
- Middleware (Runtime): reads `langgraph.config.get_config()["configurable"]["workspace"]`
- Fallback: `FrameworkFilesystem.get_current_workspace()` (ContextVar)
- Ultimate fallback: daemon default

**ContextVar mechanism** (`framework_filesystem.py`):
- `_current_workspace: ContextVar[Path | None]` provides async-task-scoped isolation
- `WorkspaceContextMiddleware.abefore_agent` → `set_current_workspace(workspace)`
- `WorkspaceContextMiddleware.aafter_agent` → `clear_current_workspace()`

**Weaknesses**:
- ContextVar uses `set()` not token-based reset — exception paths can leak (see Bug 5.1)
- Tool cache returns instances built with a different workspace (see Bug 5.2)

### 3.3 Input/Command Isolation

**`LoopInputDispatcher`** (`loop_isolation.py:99–165`):

- One `asyncio.Queue` per `loop_id`, created lazily
- One `asyncio.Task` worker per loop, processing messages sequentially
- `_shutting_down` flag prevents orphan workers during daemon shutdown
- Input for one loop cannot block processing on another

**Weaknesses**:
- No input validation against loop status — input accepted for finalized/deleted loops (design gap, not tracked separately)

### 3.4 Running Resource Isolation

**Active task tracking**: `_active_runners: dict[str, LoopRunnerProtocol]` keyed by `loop_id` (RFC-221 change from `_active_threads` keyed by `thread_id`). Each runner manages its own subprocess lifecycle.

**Ownership protocol**:
1. `claim_loop_ownership(client_id, loop_id)` — at query start
2. `release_loop_ownership(client_id)` — in `_run_stream` finally block
3. On client disconnect: `_cancel_loop_for_session(loop_id)` → `runner.cancel()`

**Weaknesses**:
- `daemon._runner.set_interrupt_resolver()` still operates on the singleton (see Bug 5.7, reduced severity)
- `daemon._runner.set_current_thread_id()` still used in lifecycle ops (see Flaw 6.1, reduced severity)
- MCP sessions accumulate without cleanup (see Flaw 6.3)
- Tool cache workspace leakage (see Bug 5.2)

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
- `loop_delete` does not unsubscribe clients (see Bug 5.4)
- No ownership validation on destructive operations (see Flaw 6.4)

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

**RFC-221 Resolutions**: The following issues identified in the original analysis are now structurally resolved by per-loop subprocess isolation:

| Issue | Resolution |
|-------|-----------|
| Runner `_current_thread_id` data race (Flaw 6.1, core) | Each subprocess has its own `SootheRunner`; `bind_execution_thread_for_loop()` no longer mutates the singleton |
| Runner `_interrupt_resolver` cross-loop clobber (Bug 5.7, streaming path) | Subprocess-local resolver cannot be clobbered by another loop |
| Runner `_current_plan` / `_artifact_store` cross-loop bleed | Each subprocess has its own mutable state |
| `_active_threads` keyed by thread_id (Flaw 6.1, tracking) | Replaced by `_active_runners` keyed by loop_id |
| Cross-loop ContextVar contamination (Bug 5.1, cross-loop) | Each subprocess has its own ContextVar scope |
| Cross-loop tool cache contamination (Bug 5.2, cross-loop) | Each subprocess starts with an empty tool cache |

---

## 5. New Bugs

### Bug 5.1 — Workspace ContextVar Leak on Exception Paths (HIGH → MEDIUM)

**Location**: `framework_filesystem.py:164–192`, `workspace_context.py:68–110`

**Root cause**: `FrameworkFilesystem.set_current_workspace()` uses `ContextVar.set()` instead of the token-based `set()` + `reset(token)` pattern. The `WorkspaceContextMiddleware.aafter_agent` callback calls `clear_current_workspace()`, but if the agent execution raises an exception that bypasses `aafter_agent`, or if the middleware's after-hook is not invoked for certain error paths, the ContextVar retains the previous loop's workspace.

**RFC-221 impact**: Reduced severity. Each loop runs in its own subprocess with its own Python interpreter and its own ContextVar scope. A leaked ContextVar in subprocess A cannot affect subprocess B. The leak can still cause issues within a single subprocess if it processes multiple queries sequentially (e.g., after a loop reset), but cross-loop contamination is structurally prevented.

**Contrast**: `model_override.py:23–40` correctly uses token-based reset:
```python
token = _stream_model_override.set(override)
# ... execution ...
_stream_model_override.reset(token)  # guaranteed rollback
```

**Impact**: In a daemon serving multiple loops concurrently, tools in a subsequent loop could read the previous loop's workspace path from the ContextVar, causing file operations to target the wrong directory.

**Fix**: Use token-based ContextVar management:
```python
class FrameworkFilesystem:
    @classmethod
    def set_current_workspace(cls, workspace: Path | str) -> Any:
        ws_path = Path(workspace) if isinstance(workspace, str) else workspace
        return _current_workspace.set(ws_path)

    @classmethod
    def clear_current_workspace(cls, token: Any = None) -> None:
        if token is not None:
            _current_workspace.reset(token)
        else:
            _current_workspace.set(None)  # backward compat
```

Then `WorkspaceContextMiddleware.abefore_agent` captures the token and passes it to `aafter_agent`.

---

### Bug 5.2 — Tool Cache Returns Workspace-Wrong Instances (HIGH)

**Location**: `tool_cache.py:18`, `resolver_tools.py:212–215`

**Root cause**: The tool cache is a global `_tool_cache: dict[str, list[BaseTool]]` keyed only by tool group name — no workspace, loop_id, or config key. When `resolve_tools` first resolves a tool group with workspace `/project-A`, the cached instances embed that workspace path. When a second loop with workspace `/project-B` requests the same tool group, it receives the `/project-A` instances.

```python
# resolver_tools.py:212
cached = get_cached_tools(name)
if cached is not None:
    return cached  # ← returns tools built for a different workspace!
```

**RFC-221 impact**: Reduced in practice — each subprocess has its own tool cache. A new subprocess for loop B starts with an empty cache and resolves tools for its own workspace. The cross-loop cache contamination only occurs if a subprocess is reused across loops (which RFC-221 does not do — each loop gets a fresh subprocess). However, the bug still exists within a single subprocess if the tool resolution is called multiple times with different workspaces.

**Impact**: Filesystem tools like `SootheFilesystemMiddleware` and `ExecutionToolkit` are constructed with `workspace_root` at creation time. Once cached, these tools operate against the wrong workspace when reused. With RFC-221's per-process model, cross-loop contamination is structurally prevented, but within-process sequential misuse is still possible.

**Mitigation**: The `WorkspaceAwareBackend` factory (backend.py) provides per-invocation workspace resolution for filesystem operations at runtime, partially mitigating this. However, tools that cache their own workspace reference (e.g., `ExecutionToolkit.workspace_root`) bypass this factory and use the stale cached value.

**Fix**: Include workspace in the cache key:
```python
_tool_cache: dict[tuple[str, str], list[BaseTool]] = {}
# Key: (tool_group_name, workspace_path)
```
Or, invalidate the cache when the workspace changes.

---

### Bug 5.3 — Checkpoint Load-Modify-Save TOCTOU Race (HIGH → MEDIUM)

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

### Bug 5.4 — Dangling Subscriptions After loop_delete (HIGH)

**Location**: `message_router.py:1050–1087`

**Root cause**: `_handle_loop_delete` removes the filesystem directory and SQLite rows for a loop, but does NOT:
1. Call `_session_manager.unsubscribe_loop()` for clients subscribed to the deleted loop
2. Cancel any running query for the loop
3. Clean up in-memory state (`_memory_claude_sessions`, `ThreadStateRegistry` entries)
4. Clear `LoopInputDispatcher` queues/workers for the loop

Clients remain subscribed to a now-nonexistent loop topic. They hold session state and event queues that will never receive events but also never get cleaned up. If the same `loop_id` is ever reused (unlikely with UUID7 but theoretically possible after manual cleanup), these stale subscriptions would receive events intended for the new loop.

**Impact**: Resource leak (event queues, sender tasks, session entries) plus a theoretical cross-loop event delivery risk if loop_ids are reused.

**Fix**: In `_handle_loop_delete`, before deleting filesystem data:
```python
# Cancel running queries
await self._query_engine.cancel_loop(loop_id)
# Unsubscribe all clients from this loop's topic
for client_id in list(self._session_manager._sessions):
    session = self._session_manager._sessions.get(client_id)
    if session and loop_id in session.subscriptions:
        await self._session_manager.unsubscribe_loop(client_id, loop_id)
# Remove from loop input dispatcher
# Clean up ThreadStateRegistry entries
# Clean up _memory_claude_sessions
```

---

### Bug 5.5 — loop_detach Leaves Interrupt Futures Pending (MEDIUM)

**Location**: `message_router.py:1187–1252`

**Root cause**: `_handle_loop_detach` unsubscribes the client and marks the loop as `detached`, but does not resolve or cancel `daemon._pending_interrupt_responses` for the loop. If the loop was paused on a HITL interrupt when the client detached, the interrupt future remains pending indefinitely. The loop's `AgentLoop.run_with_progress()` is blocked on `await future`, preventing the loop from ever completing or being cleaned up.

**Impact**: A detached loop with an active interrupt never completes, holding its `AgentLoopStateManager` connections and resources forever.

**Fix**: In `_handle_loop_detach`, resolve any pending interrupt future for the loop with a cancellation payload:
```python
pending = d._pending_interrupt_responses.pop(loop_id, None)
if pending and not pending.done():
    pending.set_result({"action": "cancel", "reason": "client_detached"})
```

---

### Bug 5.6 — Unbounded Loop Creation / No Rate Limiting (HIGH → CRITICAL)

**Location**: `message_router.py:1254–1341`

**Root cause**: `_handle_loop_new` creates a new loop with no rate limiting, capacity check, or maximum count enforcement. Each loop, when activated:
- Creates a filesystem directory
- Creates 4+ SQLite table rows
- Creates an `AgentLoopStateManager` with its own SQLite connection pool (5 reader + 1 writer = 6 connections per loop)
- Eventually creates `LoopInputDispatcher` queue + worker task

With `max_concurrent_threads=100`, 100 concurrent loops would open 600 SQLite connections to the same database file. SQLite's WAL mode allows concurrent readers but the writer is serialized — heavy concurrent write load causes `timeout=30` errors (manager.py:189).

**RFC-221 impact**: More severe. Each loop now spawns an OS subprocess via `LocalLoopRunner`. 100 concurrent loops means 100 subprocesses, each with its own `SootheRunner` (full init, agent graph, checkpointer connections). Resource consumption per loop is significantly higher than the pre-RFC-221 shared-runner model.

**Impact**: A single client can exhaust daemon resources (PIDs, file descriptors, SQLite connections, memory) by creating loops in a tight loop. With per-loop subprocesses, the blast radius is larger — each subprocess adds ~50MB+ memory overhead.

**Fix**: Add a `max_total_loops` config option and enforce it in `_handle_loop_new`:
```python
max_loops = d._config.daemon.max_total_loops  # default: 50
existing = count_loops_on_disk()
if existing >= max_loops:
    return error_response("DAEMON_LOOP_LIMIT", f"Maximum {max_loops} loops reached")
```

---

### Bug 5.7 — Runner._interrupt_resolver Still on Singleton (MEDIUM → LOW)

**Location**: `runner/__init__.py:187`, `query_engine.py:289–290`, `query_engine.py:456–457`

**Root cause**: `SootheRunner._interrupt_resolver` is a single instance field on `daemon._runner`. When `run_query` sets it:
```python
d._runner.set_interrupt_resolver(interrupt_resolver)  # line 293
```
...a concurrent loop's `set_interrupt_resolver(None)` in its finally block (line 482) can clear the first loop's resolver.

**RFC-221 impact**: The streaming path now runs inside per-loop subprocesses. Each subprocess has its own `SootheRunner` instance with its own `_interrupt_resolver`. The subprocess-local resolver is set inside `_loop_worker()` and cannot be clobbered by another loop. However, `query_engine.py` still wires the resolver on `daemon._runner` (the utility singleton in the daemon process) for HITL continuation dispatch. If two loops both hit HITL simultaneously, the second `set_interrupt_resolver()` call overwrites the first on the singleton.

**Current severity**: Low in practice — HITL interrupts are rare and typically serialized by the input dispatcher. The subprocess isolation eliminates the data race for the streaming execution itself; only the daemon-side resolver dispatch is affected.

**Fix**: Move interrupt resolver wiring into `LoopRunRequest` or key it by `loop_id` on the singleton:
```python
class SootheRunner:
    def __init__(self):
        self._interrupt_resolvers: dict[str, Callable] = {}  # keyed by loop_id

    def set_interrupt_resolver(self, loop_id: str, resolver):
        self._interrupt_resolvers[loop_id] = resolver

    def get_interrupt_resolver(self, loop_id: str):
        return self._interrupt_resolvers.get(loop_id)
```

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
| `set_interrupt_resolver()` / `set_interrupt_resolver(None)` | query_engine.py:293, 482 | Yes — HITL dispatch |
| `create_persisted_thread()` | query_engine.py:119, 590 | Yes — thread creation |
| `touch_thread_activity_timestamp()` | query_engine.py:209, 507, 677, 826 | Yes — activity tracking |

These operations are largely sequential (per-loop lifecycle) rather than concurrent (simultaneous streaming). The architectural risk is reduced from **High** to **Low**.

**Recommendation**: Complete the migration by moving remaining lifecycle operations behind `LoopRunnerProtocol` or scoping them per-loop. The utility `_runner` should eventually become a read-only reference to the checkpointer/agent for status queries only.

### Flaw 6.2 — Claude Session Bridge Memory Leak (MEDIUM)

**Location**: `session_bridge.py:17–24`

Module-level `_memory_claude_sessions: dict[tuple[str, str], str]` and `_locks: dict[tuple[str, str], asyncio.Lock]` grow without bound. Neither `loop_delete` nor `loop_detach` clears entries for the loop's threads. With long-running daemons processing many loops, this is an unbounded memory leak.

**Recommendation**: Add cleanup hooks:
1. On `loop_delete`, iterate the loop's `thread_ids` from metadata and remove matching entries
2. Add LRU eviction (max 1000 entries) with periodic cleanup
3. Or, key by `loop_id` instead of `(thread_id, cwd)` so batch cleanup is O(1)

### Flaw 6.3 — MCP Session Accumulation (MEDIUM)

**Location**: `manager.py:41`

`ThreadContextManager._mcp_managers: ClassVar[dict[str, MCPSessionManager]]` is a class-level dict that grows with each thread. MCP sessions are only cleaned up on explicit `suspend_thread`/`archive_thread` calls. Loop switching in the TUI does not trigger these calls, so MCP sessions for old loops remain in memory indefinitely.

**Recommendation**: Add a `cleanup_mcp_session_for_loop(loop_id)` method that removes all MCP sessions whose thread_id belongs to the given loop. Call it from `_handle_loop_delete` and optionally from `_handle_loop_detach`.

### Flaw 6.4 — No Loop Ownership Validation on Destructive Operations (MEDIUM)

**Location**: `message_router.py:1006–1087`

`_handle_loop_delete` does not verify that the requesting client owns the loop or is even subscribed to it. Any client with a valid connection can delete any loop by ID. This is an authorization gap — a malicious or buggy client could delete another client's active work.

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
| EventBus topics | Per `loop_id` | `loop:{loop_id}` topic | Low (dangling subs after delete) |
| Client subscriptions | Per session | Single-sub enforcement | Low |
| Workspace (runtime) | Per `loop_id` | LangGraph configurable | Medium (ContextVar leak) |
| Workspace (tools) | Per `loop_id` | WorkspaceAwareBackend | High (tool cache) |
| Input queues | Per `loop_id` | LoopInputDispatcher | Low |
| Loop runners (RFC-221) | Per `loop_id` | LoopRunnerProtocol subprocess | Low |
| Checkpoint storage | Per `thread_id` | LangGraph checkpoint key | Low |
| Loop metadata | Per `loop_id` | Filesystem `metadata.json` | Medium (TOCTOU) |
| Thread registry | Per `thread_id` | ThreadStateRegistry | Low |
| Runner mutable state | **Per loop_id (streaming)** / **Global (lifecycle)** | Subprocess isolation + singleton | **Low** (was High) |
| Tool cache | **Global** | Module-level dict | **High** |
| Claude sessions | Per `(thread_id, cwd)` | In-memory + durability | Medium (no cleanup) |
| MCP sessions | Per `thread_id` | ClassVar dict | Medium (no cleanup) |
| DB connections | Per loop (SQLite) / shared (PostgreSQL) | StateManager.close() | Low |
| Interrupt resolvers | **Per loop (subprocess)** / **Global (dispatch)** | Runner._interrupt_resolver | Low (was Medium) |
| Heartbeat routing | Per `loop_id` | _active_stream_loop_ids set | Low |
| Memory (long-term) | Per `source_thread` | MemuMemoryStore.user_id | Low |

---

## 8. Recommendations — Priority Order (Updated for RFC-221)

RFC-221 resolves the highest-severity class of bugs (streaming data races on the SootheRunner singleton). The remaining priorities are:

| Priority | Fix | Effort | Impact | RFC-221 Impact |
|----------|-----|--------|--------|----------------|
| P0 | Tool cache: include workspace in key or invalidate on workspace change | Small | Eliminates cross-workspace file access | Unaffected — tool cache operates per-process |
| P0 | ContextVar: switch to token-based reset in FrameworkFilesystem | Small | Eliminates workspace leak on exceptions | Reduced — each subprocess has its own ContextVar scope |
| P1 | loop_delete: clean up subscriptions, in-memory state, running queries | Medium | Prevents resource leaks and dangling refs | Unaffected |
| P1 | loop_detach: resolve pending interrupt futures | Small | Prevents stuck loops | Unaffected |
| P1 | Loop creation limit: add max_total_loops config | Small | Prevents resource exhaustion | More urgent — each loop now spawns a subprocess |
| P1 | Remaining `_runner` lifecycle ops: migrate continue/switch/cancel behind LoopRunnerProtocol | Medium | Completes singleton elimination | Next step in RFC-221 migration |
| P2 | interrupt_resolver: scope by loop_id on utility singleton | Small | Fixes HITL dispatch race | Reduced — subprocess isolates execution; only dispatch path affected |
| P2 | loop_delete authorization: add ownership validation | Small | Prevents unauthorized deletion | Unaffected |
| P2 | Claude session bridge: add cleanup on loop lifecycle events | Medium | Prevents memory leak | Unaffected |
| P2 | MCP sessions: add cleanup on loop lifecycle events | Medium | Prevents memory leak | Unaffected |
| P3 | Checkpoint TOCTOU: add CAS or row-level locking | Large | Fixes rare race under high concurrency | Reduced — each subprocess has its own checkpointer access |
| ~~P1~~ | ~~Runner singleton: migrate per-query state to RunnerState~~ | ~~Large~~ | ~~Eliminates class of concurrent races~~ | **Resolved by RFC-221** |

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

---

## Appendix A: Isolation Domain Inventory

For each isolation domain, the enforcement mechanism and known gaps:

### Events
- **Enforcement**: EventBus topics, single-sub enforcement, `_loop_scoped_client_message` boundary
- **Gaps**: Dangling subscriptions after loop_delete, unresolved interrupt futures after detach

### Workspace
- **Enforcement**: LangGraph configurable, WorkspaceAwareBackend factory, 5-level resolution chain, per-subprocess tool cache (RFC-221)
- **Gaps**: ContextVar leak on exceptions (within-subprocess only), tool cache returning workspace-wrong instances (within-subprocess only)

### Input
- **Enforcement**: Per-loop asyncio queues + workers, `_shutting_down` flag
- **Gaps**: No validation against loop status (input accepted for finalized/deleted loops, design gap)

### Running Resources
- **Enforcement**: `_active_runners` keyed by loop_id (RFC-221), per-loop subprocess isolation via `LoopRunnerProtocol`, loop ownership protocol, `runner.cancel()` for scoping
- **Gaps**: `daemon._runner` still used for lifecycle operations (interrupt resolver, thread switching), MCP session accumulation

### Persistence
- **Enforcement**: Per-thread_id checkpoint key, per-loop_id AgentLoop state
- **Gaps**: Checkpoint load-modify-save not atomic

### Client Sessions
- **Enforcement**: Single ownership, single subscription, sender task per session
- **Gaps**: No ownership validation on delete, no client cleanup on loop_delete

### Subprocess Execution (RFC-221)
- **Enforcement**: Per-loop OS process via `LoopRunnerProtocol`, `LoopRunRequest` for parameter passing, queue-bridge for chunk streaming, `process.terminate()/kill()` for cancellation
- **Gaps**: `daemon._runner` singleton still used for non-streaming lifecycle operations (interrupt resolver wiring, thread switching, activity timestamps)

### Memory
- **Enforcement**: Per-source_thread MemuMemoryStore, per-thread_id working memory spill
- **Gaps**: Claude session bridge unbounded growth, MCP session unbounded growth

### Filesystem
- **Enforcement**: WorkspaceAwareBackend per-invocation resolution, NormalizedPathBackend per-workspace
- **Gaps**: Tool cache returns stale instances, ContextVar leak on error paths
