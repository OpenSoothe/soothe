# Agent Runner Protocol and Ray Distribution

**Status:** Draft  
**Date:** 2026-05-09

## Overview

This document designs a unified agent runner interface (`LoopRunnerProtocol`) that decouples `QueryEngine` from the execution mode of a loop. The same interface supports:

- **Local mode**: runs `SootheRunner` in a subprocess per `loop_id` via Python `multiprocessing`, providing process-level fault isolation with no extra dependencies
- **Ray mode**: runs `SootheRunner` inside a Ray actor per `loop_id`, providing process-level fault isolation on a Ray cluster

Both modes are subprocess-based. The primary motivation is **isolation**: a crashed or runaway loop must not affect the daemon or other loops.

---

## Goals

- Single callsite in `QueryEngine`: `async for chunk in runner.run(request)`
- Local mode uses only Python stdlib (`multiprocessing`) — no Ray required
- Both modes give each loop its own OS process; a crash surfaces as a handled error, not a daemon crash
- Both modes construct `SootheRunner` fresh inside the subprocess — no shared mutable state
- Ray is a soft dependency: imported only in the Ray-specific module, guarded at daemon startup

---

## SootheRunner Singleton Problem

The current daemon creates exactly one `SootheRunner` in `server.py:192`. Several fields on that singleton are mutable and loop-specific:

| Field | Risk |
|---|---|
| `_current_thread_id` | Last writer wins — Loop B's `bind_execution_thread_for_loop()` overwrites Loop A's |
| `_current_plan` | Stale plan from a previous or concurrent loop |
| `_interrupt_resolver` | Loop A's HITL resolver blocks or intercepts Loop B's input |
| `_artifact_store` | Artifacts attributed to the wrong loop |

`bind_execution_thread_for_loop()` (`loop_isolation.py:95`) calls `daemon._runner.set_current_thread_id(thread_id)` synchronously — a plain assignment with no locking. Under concurrent execution this is a data race.

**Fix:** one subprocess per `loop_id` in both local and Ray modes. Each subprocess constructs its own `SootheRunner(config)` — the mutable fields above are never shared across loops. The `daemon._runner` singleton is removed entirely.

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

Both modes are structurally symmetric: subprocess + queue bridge + async generator adapter. The only difference is the subprocess runtime (Python `multiprocessing` vs Ray actor).

---

## Components

### `LoopRunnerProtocol` — `soothe/protocols/runner.py`

The structural interface all runners satisfy. Consumers depend only on this.

```python
@dataclass
class LoopRunRequest:
    thread_id: str
    loop_id: str
    workspace: str
    query: str
    config: SootheConfig
    # ... other fields currently passed to SootheRunner.astream()

class LoopRunnerProtocol(Protocol):
    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]: ...
    async def cancel(self) -> None: ...
```

`LoopRunRequest` consolidates all parameters currently passed ad-hoc into `SootheRunner.astream()`.

---

### `LocalLoopRunner` — `core/runner/local_runner.py`

Spawns a **`multiprocessing.Process`** per loop. The subprocess runs `_loop_worker(config, request, queue)` — a top-level function that constructs `SootheRunner(config)`, calls `astream()` via `asyncio.run()`, and pushes each `StreamChunk` into a `multiprocessing.Queue`. Pushes a sentinel on clean completion, or an exception wrapper on error.

The parent side wraps the queue drain in an async generator via `asyncio.get_event_loop().run_in_executor()` (non-blocking queue polling). `cancel()` calls `process.terminate()` followed by `process.join(timeout=5)`, then `process.kill()` as a hard fallback.

```
LocalLoopRunner.run(request)
  → spawn multiprocessing.Process(_loop_worker, config, request, queue)
  → async for chunk in _drain_mp_queue(queue):
        yield chunk
```

---

### `LoopRunnerActor` — `core/runner/ray_actor.py`

A `@ray.remote` class that hosts a `SootheRunner` inside a Ray worker process. Constructs `SootheRunner(config)` at actor init. Pushes chunks into a `ray.util.queue.Queue` passed by the caller. Pushes sentinel on completion, exception wrapper on error.

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

---

### `RayLoopRunner` — `core/runner/ray_runner.py`

Manages the actor lifecycle for one `loop_id`. Created fresh per loop.

- `run(request)`: creates `LoopRunnerActor`, creates `ray.util.queue.Queue`, calls `actor.run.remote(request, queue)`, returns `_drain_ray_queue(queue)` as an async generator.
- `cancel()`: calls `actor.cancel.remote()`, waits briefly, then `ray.kill(actor)` after 5s.
- `_drain_ray_queue(queue)`: async generator that yields chunks until sentinel or `RayActorError`.

Ray imports are at the top of this file only — never transitively imported by local-mode paths.

---

### `LoopRunnerFactory` — `core/runner/factory.py`

```python
class LoopRunnerFactory:
    def __init__(self, config: SootheConfig):
        self._config = config

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol:
        if self._config.distributed:
            from soothe.core.runner.ray_runner import RayLoopRunner
            return RayLoopRunner(loop_id, self._config)
        return LocalLoopRunner(loop_id, self._config)
```

`config.distributed` is driven by a `SOOTHE_DISTRIBUTED=true` env var. If `distributed=True` and Ray is not installed, `ImportError` is raised at daemon startup with a clear message.

Daemon startup: `SootheDaemon` constructs `LoopRunnerFactory(config)` and passes it to `QueryEngine`. The `daemon._runner` singleton is removed.

---

## QueryEngine Changes

`QueryEngine` (`daemon/query_engine.py`) is updated:

1. Constructor receives `LoopRunnerFactory` instead of `SootheRunner`
2. `_active_threads: dict[str, asyncio.Task]` → `_active_runners: dict[str, LoopRunnerProtocol]`
3. `run_query()` calls `factory.create_runner(loop_id)`, stores the runner, iterates `runner.run(request)`
4. `cancel_loop()` calls `runner.cancel()` instead of `task.cancel()`
5. `run_query_multithreaded()` follows the same pattern; the `ThreadExecutor` layer is unchanged

`loop_isolation.py` is simplified: `bind_execution_thread_for_loop()` no longer calls `daemon._runner.set_current_thread_id()` — thread/workspace binding is passed directly in `LoopRunRequest` and applied inside the subprocess at `SootheRunner` construction time.

---

## Data Flow

**Local mode:**
```
QueryEngine.run_query(loop_id, request)
  → factory.create_runner(loop_id)        → LocalLoopRunner
  → runner.run(request)
      → spawn multiprocessing.Process(_loop_worker, config, request, queue)
      → async for chunk in _drain_mp_queue(queue):
            yield chunk                    [back to QueryEngine]
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
            yield chunk                    [back to QueryEngine]
  → QueryEngine broadcasts chunk to clients
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Local subprocess crash | `_drain_mp_queue` detects dead process (exit code ≠ 0) → raises `SubprocessLoopError` → `QueryEngine` treats as loop failure, broadcasts error event |
| Ray actor process crash | `RayActorError` surfaces from `_drain_ray_queue` → same handling as above |
| `cancel()` called (local) | `process.terminate()` → `process.join(timeout=5)` → `process.kill()` |
| `cancel()` called (Ray) | `actor.cancel.remote()` → `ray.kill(actor)` after 5s |
| Ray not installed, `distributed=True` | `ImportError` at daemon startup: "Ray is required for distributed mode. Install with: pip install ray" |
| Queue overflow (local) | `multiprocessing.Queue` is unbounded by default; subprocess applies natural backpressure via blocking `put()` |
| Queue overflow (Ray) | Queue sized at 1000; actor applies backpressure via `queue.put_async()` |

---

## New Files

| File | Purpose |
|---|---|
| `soothe/protocols/runner.py` | `LoopRunnerProtocol`, `LoopRunRequest` |
| `core/runner/local_runner.py` | `LocalLoopRunner`, `_loop_worker`, `_drain_mp_queue` |
| `core/runner/ray_actor.py` | `LoopRunnerActor` (`@ray.remote`) |
| `core/runner/ray_runner.py` | `RayLoopRunner`, `_drain_ray_queue` |
| `core/runner/factory.py` | `LoopRunnerFactory` |

**Modified:**
- `soothe/protocols/__init__.py` — export `LoopRunnerProtocol`, `LoopRunRequest`
- `core/runner/__init__.py` — export runner implementations; `SootheRunner` gains no new parameters
- `daemon/server.py` — replace `SootheRunner` singleton with `LoopRunnerFactory(config)`
- `daemon/query_engine.py` — accept `LoopRunnerFactory`, use `_active_runners`
- `daemon/loop_isolation.py` — remove `set_current_thread_id()` call; pass binding via `LoopRunRequest`

---

## Testing Strategy

**Unit tests (no Ray, no subprocess):**
- `LocalLoopRunner`: mock `multiprocessing.Process` and `Queue`; assert worker is spawned and chunks drain correctly
- `RayLoopRunner`: mock `ray.remote`, `Queue`, and `ray.kill`; test cancel timeout path
- `LoopRunnerFactory.create_runner()`: assert `LocalLoopRunner` returned when `distributed=False`, `RayLoopRunner` when `True`

**Integration tests (local mode):**
- Spawn a real `LocalLoopRunner` with a stub `SootheRunner` (lightweight config), run end-to-end, assert chunks arrive
- Kill the subprocess mid-stream, assert `SubprocessLoopError` surfaces to `QueryEngine`
- Run two loops concurrently, assert they are in separate PIDs and chunks are correctly attributed

**Integration tests (Ray mode):**
- Pytest fixture calls `ray.init(num_cpus=2)` / `ray.shutdown()` around the test session
- Spawn a real `LoopRunnerActor` with a stub `SootheRunner`, assert chunks arrive via queue
- Kill the actor mid-stream, assert `RayActorError` surfaces correctly

**Existing tests:** `SootheRunner` direct tests are unchanged. `QueryEngine` tests are updated to inject a `LoopRunnerFactory` mock.

---

## Out of Scope

- Distributed `ConcurrencyController` (remains asyncio-based within each actor)
- Actor placement / resource constraints (Ray defaults used; tunable via `RunnerConfig` later)
- Checkpoint sharing across actors (each actor manages its own `AgentLoopStateManager`; shared persistence layer is unchanged)
