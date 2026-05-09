# IG-410: Loop Runner Protocol and Subprocess Isolation

**IG**: 410  
**RFC**: RFC-221  
**Title**: LoopRunnerProtocol — Subprocess-Isolated Agent Loop Execution  
**Status**: Draft  
**Created**: 2026-05-09

---

## Overview

Implements RFC-221. Replaces the `SootheRunner` singleton in the daemon with a per-`loop_id` subprocess model. Each loop runs in its own OS process, eliminating the data race on `_current_thread_id` / `_current_plan` / `_interrupt_resolver` / `_artifact_store`. Two execution modes: `LocalLoopRunner` (Python `multiprocessing`) and `RayLoopRunner` (Ray actor).

---

## Coding Plan

### Step 1 — Add `distributed` flag to `DaemonConfig`

**File**: `packages/soothe/src/soothe/config/daemon_config.py`

Add field:
```python
distributed: bool = Field(
    default=False,
    description="Run each loop in an isolated subprocess. Set SOOTHE_DISTRIBUTED=true to enable.",
)
```

Wire env var override in `packages/soothe/src/soothe/config/env.py` (or wherever env overrides are applied):
```python
if os.environ.get("SOOTHE_DISTRIBUTED", "").lower() in ("1", "true", "yes"):
    config.daemon.distributed = True
```

---

### Step 2 — `soothe/protocols/runner.py` (new file)

**File**: `packages/soothe/src/soothe/protocols/runner.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from soothe.core.runner._runner_shared import StreamChunk


@dataclass
class LoopRunRequest:
    """All parameters needed to run one agent loop in a subprocess."""
    loop_id: str
    thread_id: str
    workspace: str | None
    user_input: str
    autonomous: bool = False
    max_iterations: int | None = None
    preferred_subagent: str | None = None
    model: str | None = None
    model_params: dict[str, Any] = field(default_factory=dict)


class LoopRunnerProtocol(Protocol):
    """Structural interface for all loop runner implementations."""

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Execute the loop; yield StreamChunks until completion."""
        ...

    async def cancel(self) -> None:
        """Request cancellation of the running loop."""
        ...
```

**File**: `packages/soothe/src/soothe/protocols/__init__.py`

Add to imports and `__all__`:
```python
from soothe.protocols.runner import LoopRunRequest, LoopRunnerProtocol

# in __all__:
"LoopRunRequest",
"LoopRunnerProtocol",
```

---

### Step 3 — `core/runner/local_runner.py` (new file)

**File**: `packages/soothe/src/soothe/core/runner/local_runner.py`

```python
from __future__ import annotations

import asyncio
import multiprocessing
import multiprocessing.queues
from typing import Any, AsyncIterator

from soothe.config.settings import SootheConfig
from soothe.core.runner._runner_shared import StreamChunk
from soothe.protocols.runner import LoopRunRequest, LoopRunnerProtocol


class SubprocessLoopError(RuntimeError):
    """Raised when the loop subprocess exits with a non-zero code."""


def _loop_worker(
    config: SootheConfig,
    request: LoopRunRequest,
    queue: multiprocessing.Queue,  # type: ignore[type-arg]
) -> None:
    """Top-level worker function (must be picklable). Runs inside subprocess."""
    import asyncio
    from soothe.core.runner import SootheRunner

    async def _run() -> None:
        runner = SootheRunner(config)
        try:
            async for chunk in runner.astream(
                request.user_input,
                thread_id=request.thread_id,
                workspace=request.workspace,
                autonomous=request.autonomous,
                max_iterations=request.max_iterations,
                preferred_subagent=request.preferred_subagent,
            ):
                queue.put(("chunk", chunk))
        except Exception as exc:
            queue.put(("error", exc))
            return
        queue.put(("done", None))

    asyncio.run(_run())


class LocalLoopRunner:
    """Runs a loop in a multiprocessing subprocess. One instance per loop_id."""

    def __init__(self, loop_id: str, config: SootheConfig) -> None:
        self._loop_id = loop_id
        self._config = config
        self._process: multiprocessing.Process | None = None

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        ctx = multiprocessing.get_context("spawn")
        queue: multiprocessing.Queue = ctx.Queue()  # type: ignore[type-arg]
        self._process = ctx.Process(
            target=_loop_worker,
            args=(self._config, request, queue),
            daemon=True,
        )
        self._process.start()

        loop = asyncio.get_event_loop()

        def _get_next() -> Any:
            return queue.get(timeout=1.0)

        while True:
            try:
                kind, payload = await loop.run_in_executor(None, _get_next)
            except Exception:
                # queue.get timed out — check process health
                if self._process and not self._process.is_alive():
                    exitcode = self._process.exitcode or -1
                    if exitcode != 0:
                        raise SubprocessLoopError(
                            f"Loop subprocess for {self._loop_id} exited with code {exitcode}"
                        )
                    return
                continue

            if kind == "done":
                return
            elif kind == "error":
                raise payload  # re-raise the serialized exception
            else:
                yield payload  # StreamChunk

    async def cancel(self) -> None:
        if self._process and self._process.is_alive():
            self._process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, self._process.join
                    ),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                self._process.kill()
```

---

### Step 4 — `core/runner/ray_actor.py` (new file)

**File**: `packages/soothe/src/soothe/core/runner/ray_actor.py`

```python
from __future__ import annotations

# Ray imports are intentionally top-level here.
# This file must never be imported by local-mode code paths.
import ray
from ray.util.queue import Queue

from soothe.config.settings import SootheConfig
from soothe.protocols.runner import LoopRunRequest


@ray.remote
class LoopRunnerActor:
    """Ray actor hosting one SootheRunner in an isolated worker process."""

    def __init__(self, config: SootheConfig) -> None:
        from soothe.core.runner import SootheRunner
        self._runner = SootheRunner(config)
        self._cancelled = False

    async def run(self, request: LoopRunRequest, queue: Queue) -> None:
        try:
            async for chunk in self._runner.astream(
                request.user_input,
                thread_id=request.thread_id,
                workspace=request.workspace,
                autonomous=request.autonomous,
                max_iterations=request.max_iterations,
                preferred_subagent=request.preferred_subagent,
            ):
                if self._cancelled:
                    break
                await queue.put_async(("chunk", chunk))
        except Exception as exc:
            await queue.put_async(("error", exc))
            return
        await queue.put_async(("done", None))

    async def cancel(self) -> None:
        self._cancelled = True
```

---

### Step 5 — `core/runner/ray_runner.py` (new file)

**File**: `packages/soothe/src/soothe/core/runner/ray_runner.py`

```python
from __future__ import annotations

import asyncio
from typing import AsyncIterator

# Ray imports are intentionally top-level here.
import ray
from ray.util.queue import Queue

from soothe.config.settings import SootheConfig
from soothe.core.runner._runner_shared import StreamChunk
from soothe.protocols.runner import LoopRunRequest


class RayLoopRunner:
    """Manages one LoopRunnerActor per loop_id on a Ray cluster."""

    def __init__(self, loop_id: str, config: SootheConfig) -> None:
        self._loop_id = loop_id
        self._config = config
        self._actor: ray.actor.ActorHandle | None = None

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        from soothe.core.runner.ray_actor import LoopRunnerActor

        self._actor = LoopRunnerActor.remote(self._config)
        queue: Queue = Queue(maxsize=1000)
        self._actor.run.remote(request, queue)

        while True:
            kind, payload = await queue.get_async()
            if kind == "done":
                return
            elif kind == "error":
                raise payload
            else:
                yield payload

    async def cancel(self) -> None:
        if self._actor is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.wrap_future(self._actor.cancel.remote()),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            pass
        ray.kill(self._actor)
        self._actor = None
```

---

### Step 6 — `core/runner/factory.py` (new file)

**File**: `packages/soothe/src/soothe/core/runner/factory.py`

```python
from __future__ import annotations

from soothe.config.settings import SootheConfig
from soothe.protocols.runner import LoopRunnerProtocol


class LoopRunnerFactory:
    """Creates per-loop runner instances based on daemon config."""

    def __init__(self, config: SootheConfig) -> None:
        self._config = config
        if config.daemon.distributed:
            try:
                import ray  # noqa: F401
            except ImportError as exc:
                raise ImportError(
                    "Ray is required for distributed mode. "
                    "Install with: pip install ray"
                ) from exc

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol:
        if self._config.daemon.distributed:
            from soothe.core.runner.ray_runner import RayLoopRunner
            return RayLoopRunner(loop_id, self._config)
        from soothe.core.runner.local_runner import LocalLoopRunner
        return LocalLoopRunner(loop_id, self._config)
```

---

### Step 7 — Update `core/runner/__init__.py`

**File**: `packages/soothe/src/soothe/core/runner/__init__.py`

Add exports at the bottom of the existing `__all__` / import block:
```python
from soothe.core.runner.factory import LoopRunnerFactory
from soothe.core.runner.local_runner import LocalLoopRunner, SubprocessLoopError

__all__ = [
    ...,   # existing exports
    "LoopRunnerFactory",
    "LocalLoopRunner",
    "SubprocessLoopError",
]
```

Do NOT import `RayLoopRunner` or `LoopRunnerActor` here — they import Ray at module level.

---

### Step 8 — Update `daemon/server.py`

**File**: `packages/soothe/src/soothe/daemon/server.py`

Replace the `SootheRunner` singleton creation (~line 195):

```python
# BEFORE:
self._runner = await asyncio.to_thread(SootheRunner, self._config)
# ...
self._thread_executor = ThreadExecutor(self._runner, max_concurrent_threads=max_concurrent)

# AFTER:
from soothe.core.runner.factory import LoopRunnerFactory
self._runner_factory = LoopRunnerFactory(self._config)
self._runner = None   # removed; kept as None for transition period
# ThreadExecutor receives None runner; multithreaded path is deprecated in RFC-221 scope
self._thread_executor = None  # disabled; LoopRunnerFactory handles all execution
```

> **Note**: `ThreadExecutor` multi-threaded path currently wraps `SootheRunner`. With RFC-221, `run_query_multithreaded` is rerouted through `LoopRunnerFactory` the same as `run_query`. `ThreadExecutor` can be removed in a follow-up; set to `None` here to force `run_query` to take the new path (the `if d._thread_executor:` guard at line 59 will be skipped).

---

### Step 9 — Refactor `daemon/query_engine.py`

**File**: `packages/soothe/src/soothe/daemon/query_engine.py`

#### 9a. Add `_active_runners` dict

In `__init__` or the first use location, add:
```python
# Replaces _active_threads for loop-scoped runner tracking
# _active_threads remains for asyncio Task capacity tracking
```

`_active_runners: dict[str, LoopRunnerProtocol]` keyed by `loop_id`. Keep `_active_threads: dict[str, asyncio.Task]` keyed by `thread_id` for asyncio task capacity tracking (unchanged).

#### 9b. Replace `d._runner.astream(...)` in `_run_stream`

```python
# BEFORE:
async for chunk in d._runner.astream(effective_text, **stream_kwargs):

# AFTER:
from soothe.protocols.runner import LoopRunRequest
run_request = LoopRunRequest(
    loop_id=effective_loop_id or "",
    thread_id=thread_id,
    workspace=stream_kwargs.get("workspace"),
    user_input=effective_text,
    autonomous=stream_kwargs.get("autonomous", False),
    max_iterations=stream_kwargs.get("max_iterations"),
    preferred_subagent=stream_kwargs.get("preferred_subagent"),
    model=model,
    model_params=model_params or {},
)
runner = d._runner_factory.create_runner(effective_loop_id or thread_id)
d._active_runners[effective_loop_id or thread_id] = runner
try:
    async for chunk in runner.run(run_request):
        ...  # existing chunk processing unchanged
finally:
    d._active_runners.pop(effective_loop_id or thread_id, None)
```

#### 9c. Update `cancel_loop`

```python
# After cancelling asyncio tasks (existing logic), also cancel runner:
runner = d._active_runners.get(lidq)
if runner is not None:
    await runner.cancel()
    d._active_runners.pop(lidq, None)
```

#### 9d. Remove `d._runner.set_current_thread_id(None)` calls

These appear in the `except asyncio.CancelledError` block and `cancel_loop`. Remove them — per-loop runners own their own `SootheRunner` internally.

---

### Step 10 — Simplify `daemon/loop_isolation.py`

**File**: `packages/soothe/src/soothe/daemon/loop_isolation.py`

In `bind_execution_thread_for_loop()`, remove:
```python
# REMOVE this line:
daemon._runner.set_current_thread_id(thread_id)
```

The function still resolves and returns `thread_id` — that value is passed into `LoopRunRequest.thread_id` by the caller before invoking `runner.run(request)`.

---

## Tests

### Unit tests

**File**: `packages/soothe/tests/unit/runner/test_local_loop_runner.py`

```python
from unittest.mock import MagicMock, patch
import pytest
from soothe.core.runner.local_runner import LocalLoopRunner, SubprocessLoopError
from soothe.protocols.runner import LoopRunRequest

@pytest.mark.asyncio
async def test_local_runner_yields_chunks():
    """Chunks pushed by _loop_worker arrive from run()."""
    ...  # mock multiprocessing.Process and Queue; inject (chunk, payload) then (done, None)

@pytest.mark.asyncio
async def test_local_runner_raises_on_nonzero_exit():
    """SubprocessLoopError raised when process exits non-zero."""
    ...

@pytest.mark.asyncio
async def test_cancel_terminates_process():
    """cancel() calls process.terminate()."""
    ...
```

**File**: `packages/soothe/tests/unit/runner/test_loop_runner_factory.py`

```python
def test_factory_returns_local_runner_when_not_distributed():
    config = make_config(distributed=False)
    factory = LoopRunnerFactory(config)
    runner = factory.create_runner("loop-1")
    assert isinstance(runner, LocalLoopRunner)

def test_factory_raises_on_missing_ray():
    config = make_config(distributed=True)
    with patch.dict("sys.modules", {"ray": None}):
        with pytest.raises(ImportError, match="pip install ray"):
            LoopRunnerFactory(config)
```

### Integration tests

**File**: `packages/soothe/tests/integration/runner/test_local_runner_integration.py`

```python
@pytest.mark.asyncio
async def test_two_concurrent_loops_have_separate_pids():
    """Two LocalLoopRunners spawn processes with different PIDs."""
    ...  # stub SootheRunner, run two loops concurrently, collect PIDs from chunks

@pytest.mark.asyncio
async def test_subprocess_crash_raises_subprocess_loop_error():
    """Killing subprocess mid-stream raises SubprocessLoopError."""
    ...
```

---

## File Checklist

| File | Action |
|---|---|
| `soothe/protocols/runner.py` | Create |
| `soothe/protocols/__init__.py` | Add exports |
| `core/runner/local_runner.py` | Create |
| `core/runner/ray_actor.py` | Create |
| `core/runner/ray_runner.py` | Create |
| `core/runner/factory.py` | Create |
| `core/runner/__init__.py` | Add exports |
| `config/daemon_config.py` | Add `distributed` field |
| `config/env.py` | Add `SOOTHE_DISTRIBUTED` override |
| `daemon/server.py` | Replace `SootheRunner` singleton with `LoopRunnerFactory` |
| `daemon/query_engine.py` | Replace `d._runner.astream()` with `runner.run(request)`; add `_active_runners` |
| `daemon/loop_isolation.py` | Remove `set_current_thread_id()` call |
| `tests/unit/runner/test_local_loop_runner.py` | Create |
| `tests/unit/runner/test_loop_runner_factory.py` | Create |
| `tests/integration/runner/test_local_runner_integration.py` | Create |
