# RFC-221: Loop Runner Protocol and Subprocess Isolation

**RFC**: 221
**Title**: LoopRunnerProtocol: Unified Subprocess-Isolated Agent Loop Execution
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-05-09
**Dependencies**: RFC-001, RFC-220, RFC-450, RFC-452

---

## Abstract

This RFC introduces `LoopRunnerProtocol`, a unified interface for executing agent loops in isolated subprocesses. It replaces the current `SootheRunner` singleton pattern — which causes data races under concurrent execution — with a per-`loop_id` subprocess model. Two implementations are specified: `LocalLoopRunner` (Python `multiprocessing`) and `RayLoopRunner` (Ray actor). Both use the same queue-bridge pattern so `QueryEngine` is fully decoupled from the execution mode.

---

## Motivation

### SootheRunner Singleton Problem

The current daemon (`server.py:192`) creates exactly one `SootheRunner` instance shared across all concurrent loops. Several fields on this singleton are mutable and loop-specific:

| Field | Risk |
|---|---|
| `_current_thread_id` | Last writer wins — Loop B's `bind_execution_thread_for_loop()` overwrites Loop A's |
| `_current_plan` | Stale plan from a previous or concurrent loop bleeds into the wrong loop |
| `_interrupt_resolver` | Loop A's HITL resolver intercepts or blocks Loop B's input |
| `_artifact_store` | Artifacts attributed to the wrong loop |

`bind_execution_thread_for_loop()` (`loop_isolation.py:95`) calls `daemon._runner.set_current_thread_id(thread_id)` as a plain synchronous assignment with no locking. This is a data race under concurrent loop execution.

### Goals

1. Each `loop_id` runs in its own OS process — a crash or runaway loop cannot affect the daemon or other loops.
2. Single callsite in `QueryEngine`: `async for chunk in runner.run(request)`.
3. Local mode uses only Python stdlib (`multiprocessing`) — no external dependencies.
4. Ray mode supports distributed execution on a Ray cluster with the same interface.
5. `SootheRunner` internals are unchanged — it runs normally inside each subprocess.
6. Ray is a soft dependency: imported only in the Ray-specific module.

---

## Protocol Interface

Defined in `soothe/protocols/runner.py` (exported from `soothe/protocols/__init__.py`).

```python
@dataclass
class LoopRunRequest:
    thread_id: str
    loop_id: str
    workspace: str
    query: str
    config: SootheConfig
    # additional fields consolidating current SootheRunner.astream() parameters

class LoopRunnerProtocol(Protocol):
    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]: ...
    async def cancel(self) -> None: ...
```

`LoopRunRequest` consolidates all parameters currently passed ad-hoc into `SootheRunner.astream()`, including thread/workspace binding that was previously applied by `bind_execution_thread_for_loop()` via a mutation on the shared singleton.

---

## Architecture

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

Both modes are structurally symmetric: subprocess → `SootheRunner(config)` → queue → async generator adapter. The only difference is the subprocess runtime.

---

## Components

### `LocalLoopRunner` — `core/runner/local_runner.py`

Spawns a `multiprocessing.Process` per loop. The subprocess runs `_loop_worker(config, request, queue)` — a top-level function (required for pickling) that:

1. Constructs `SootheRunner(config)` (full init, in the subprocess)
2. Calls `astream()` via `asyncio.run()`
3. Pushes each `StreamChunk` into a `multiprocessing.Queue`
4. Pushes `None` sentinel on clean completion
5. Pushes a serialized exception on error

The parent wraps queue drain in an async generator using `run_in_executor` for non-blocking polling. `cancel()` calls `process.terminate()` → `process.join(timeout=5)` → `process.kill()`.

```
LocalLoopRunner.run(request)
  → spawn multiprocessing.Process(_loop_worker, config, request, queue)
  → async for chunk in _drain_mp_queue(queue, process):
        yield chunk
```

### `LoopRunnerActor` — `core/runner/ray_actor.py`

A `@ray.remote` class hosting `SootheRunner` in a Ray worker process. Constructs `SootheRunner(config)` at actor `__init__` (once per actor lifetime). On `run()`, iterates `astream()` and pushes chunks to a `ray.util.queue.Queue` provided by the caller. Supports cooperative cancellation via `_cancelled` flag checked between chunks.

```python
@ray.remote
class LoopRunnerActor:
    def __init__(self, config: SootheConfig):
        self._runner = SootheRunner(config)
        self._cancelled = False

    async def run(self, request: LoopRunRequest, queue: Queue) -> None: ...
    async def cancel(self) -> None:
        self._cancelled = True
```

### `RayLoopRunner` — `core/runner/ray_runner.py`

Manages one `LoopRunnerActor` per `loop_id`. On `run(request)`: creates actor and `ray.util.queue.Queue`, calls `actor.run.remote(request, queue)` (non-blocking), returns `_drain_ray_queue(queue)` as an async generator. On `cancel()`: calls `actor.cancel.remote()`, waits 5s, then `ray.kill(actor)`. Ray imports are top-level in this file only — never transitively imported by local-mode paths.

### `LoopRunnerFactory` — `core/runner/factory.py`

```python
class LoopRunnerFactory:
    def __init__(self, config: SootheConfig):
        self._config = config

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol:
        if self._config.distributed:
            from soothe_daemon.runner.ray_runner import RayLoopRunner
            return RayLoopRunner(loop_id, self._config)
        return LocalLoopRunner(loop_id, self._config)
```

`config.distributed` is driven by `SOOTHE_DISTRIBUTED=true` env var (or equivalent daemon config field). If `distributed=True` and Ray is not installed, `ImportError` is raised at daemon startup with a descriptive message.

---

## Data Flow

**Local mode:**
```
QueryEngine.run_query(loop_id, request)
  → factory.create_runner(loop_id)        → LocalLoopRunner
  → runner.run(request)
      → spawn multiprocessing.Process(_loop_worker, config, request, queue)
      → async for chunk in _drain_mp_queue(queue, process):
            yield chunk
  → QueryEngine broadcasts chunk to clients
```

**Ray mode:**
```
QueryEngine.run_query(loop_id, request)
  → factory.create_runner(loop_id)        → RayLoopRunner
  → runner.run(request)
      → create LoopRunnerActor             [Ray spawns worker process]
      → create ray.util.queue.Queue
      → actor.run.remote(request, queue)   [non-blocking]
      → async for chunk in _drain_ray_queue(queue):
            yield chunk
  → QueryEngine broadcasts chunk to clients
```

---

## QueryEngine Migration

`QueryEngine` (`daemon/query_engine.py`) changes:

1. Constructor receives `LoopRunnerFactory` instead of `SootheRunner`
2. `_active_threads: dict[str, asyncio.Task]` → `_active_runners: dict[str, LoopRunnerProtocol]`
3. `run_query()` calls `factory.create_runner(loop_id)`, stores runner, iterates `runner.run(request)`
4. `cancel_loop()` calls `runner.cancel()` instead of `task.cancel()`
5. `run_query_multithreaded()` follows the same pattern; `ThreadExecutor` layer unchanged

`loop_isolation.py` (`bind_execution_thread_for_loop()`) is simplified: the `daemon._runner.set_current_thread_id(thread_id)` call is removed. Thread and workspace binding is now conveyed via `LoopRunRequest` fields and applied inside the subprocess at `SootheRunner` construction time.

`server.py` daemon startup: `SootheRunner` singleton construction is replaced with `LoopRunnerFactory(config)`. `daemon._runner` is removed.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Local subprocess crash | `_drain_mp_queue` detects dead process (non-zero exit code) → raises `SubprocessLoopError` → `QueryEngine` broadcasts loop failure event, removes from `_active_runners` |
| Ray actor process crash | `RayActorError` from `_drain_ray_queue` → same handling |
| `cancel()` (local) | `process.terminate()` → `process.join(timeout=5)` → `process.kill()` |
| `cancel()` (Ray) | `actor.cancel.remote()` → `ray.kill(actor)` after 5s |
| Ray not installed, `distributed=True` | `ImportError` at daemon startup with install instructions |
| Queue overflow (local) | `multiprocessing.Queue` unbounded; subprocess applies natural backpressure via blocking `put()` |
| Queue overflow (Ray) | Queue sized at 1000 entries; actor applies backpressure via `queue.put_async()` |

---

## File Manifest

**New files:**

| File | Contents |
|---|---|
| `soothe/protocols/runner.py` | `LoopRunnerProtocol`, `LoopRunRequest` |
| `core/runner/local_runner.py` | `LocalLoopRunner`, `_loop_worker`, `_drain_mp_queue` |
| `core/runner/ray_actor.py` | `LoopRunnerActor` (`@ray.remote`) |
| `core/runner/ray_runner.py` | `RayLoopRunner`, `_drain_ray_queue` |
| `core/runner/factory.py` | `LoopRunnerFactory` |

**Modified files:**

| File | Change |
|---|---|
| `soothe/protocols/__init__.py` | Export `LoopRunnerProtocol`, `LoopRunRequest` |
| `core/runner/__init__.py` | Export `LocalLoopRunner`, `RayLoopRunner`, `LoopRunnerFactory`; `SootheRunner` unchanged |
| `daemon/server.py` | Replace `SootheRunner` singleton with `LoopRunnerFactory(config)` |
| `daemon/query_engine.py` | Accept `LoopRunnerFactory`; use `_active_runners` |
| `daemon/loop_isolation.py` | Remove `set_current_thread_id()` call; pass binding via `LoopRunRequest` |

---

## Testing Strategy

**Unit tests (no Ray, no real subprocess):**
- `LocalLoopRunner`: mock `multiprocessing.Process` and `Queue`; assert worker spawned and chunks drain
- `RayLoopRunner`: mock `ray.remote`, `Queue`, `ray.kill`; test cancel timeout path
- `LoopRunnerFactory`: assert correct type returned per `distributed` flag
- `bind_execution_thread_for_loop()`: assert it no longer mutates `daemon._runner`

**Integration tests (local mode):**
- Real `LocalLoopRunner` with lightweight stub config; assert chunks arrive end-to-end
- Kill subprocess mid-stream; assert `SubprocessLoopError` propagates to `QueryEngine`
- Two concurrent loops; assert separate PIDs, no cross-loop chunk contamination

**Integration tests (Ray mode):**
- Pytest fixture: `ray.init(num_cpus=2)` / `ray.shutdown()`
- Real `LoopRunnerActor` with stub `SootheRunner`; assert chunks arrive via queue
- Kill actor mid-stream; assert `RayActorError` surfaces correctly

**Existing tests:** `SootheRunner` unit tests unchanged. `QueryEngine` tests updated to inject a `LoopRunnerFactory` mock.

---

## Backward Compatibility

- `SootheRunner` public interface is unchanged — it runs normally inside subprocesses
- `daemon.run_query()` external behaviour (streaming, cancellation, error events) is unchanged
- `LoopRunnerProtocol` is additive — existing callers migrated at `QueryEngine` only
- Ray mode is opt-in via `SOOTHE_DISTRIBUTED=true`; default remains local multiprocessing

---

## Out of Scope

- Distributed `ConcurrencyController` — remains asyncio-based within each subprocess
- Ray actor placement and resource constraints — Ray defaults; tunable later via config
- Checkpoint sharing across subprocesses — each subprocess uses the shared persistence backend independently (unchanged)

---

## References

- RFC-001: Core Modules Architecture
- RFC-220: LangGraph Agent Loop Orchestrator
- RFC-450: Daemon Communication Protocol
- RFC-452: Unified Thread Management
