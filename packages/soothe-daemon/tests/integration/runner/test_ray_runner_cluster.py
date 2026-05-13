"""Integration tests for Ray loop runner using a multi-node ``Cluster`` (RFC-221).

Uses ``ray.cluster_utils.Cluster`` to start a head node plus worker nodes, then
validates Ray scheduling and ``RayLoopRunner`` queue draining.

**Requirements**: optional ``ray`` package. Tests are skipped when Ray is not
installed.

**Invocation**: marked ``integration`` — run with ``pytest --run-integration``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("ray")

import ray  # noqa: E402

try:
    from ray.cluster_utils import Cluster
except ImportError:  # pragma: no cover - exercised only on old Ray builds
    Cluster = None  # type: ignore[misc, assignment]

from soothe.protocols.runner import LoopRunRequest

pytestmark = pytest.mark.integration


def _make_request(**kwargs: Any) -> LoopRunRequest:
    defaults: dict[str, Any] = dict(
        loop_id="ray-integ-loop-1",
        thread_id="ray-integ-thread-1",
        user_input="hello",
    )
    defaults.update(kwargs)
    return LoopRunRequest(**defaults)


@pytest.fixture
def ray_multi_node_cluster():
    """Start a local multi-node Ray cluster and tear it down reliably."""
    if Cluster is None:
        pytest.skip("ray.cluster_utils.Cluster is not available in this Ray version")

    if ray.is_initialized():
        ray.shutdown()

    cluster = Cluster()
    head_node = cluster.add_node(num_cpus=2)
    cluster.add_node(num_cpus=1)
    cluster.add_node(num_cpus=1)

    address = head_node.address_info["address"]
    ray.init(address=address)

    try:
        yield cluster
    finally:
        if ray.is_initialized():
            ray.shutdown()
        cluster.shutdown()


def test_ray_cluster_multi_node_resources(ray_multi_node_cluster) -> None:
    """Cluster exposes multiple nodes and enough CPUs for parallel tasks."""
    nodes = ray.nodes()
    assert len(nodes) >= 2, f"expected multi-node cluster, got {len(nodes)} nodes"

    resources = ray.cluster_resources()
    cpu_total = resources.get("CPU", 0)
    assert cpu_total >= 2.0, f"expected pooled CPUs across nodes, got {resources}"

    @ray.remote
    def _worker_task() -> str:
        import socket

        return f"ok-{socket.gethostname()}"

    futures = [_worker_task.remote() for _ in range(4)]
    results = ray.get(futures)
    assert len(results) == 4
    assert all(r.startswith("ok-") for r in results)


@pytest.mark.asyncio
async def test_ray_loop_runner_streams_chunks_with_stub_actor(ray_multi_node_cluster) -> None:
    """``RayLoopRunner`` drains ``ray.util.queue.Queue`` from a remote actor.

    The real ``LoopRunnerActor`` builds a full ``SootheRunner``; this test
    substitutes a lightweight stub so no LLM or heavy config is required.
    """

    @ray.remote
    class StubLoopRunnerActor:
        def __init__(self, _config: object) -> None:
            pass

        async def run(self, request: LoopRunRequest, queue: Any) -> None:
            await queue.put_async(("chunk", (("ns",), "messages", f"echo:{request.user_input}")))
            await queue.put_async(("done", None))

        async def cancel(self) -> None:
            pass

    with patch("soothe_daemon.runner.ray_actor.LoopRunnerActor", StubLoopRunnerActor):
        from soothe_daemon.runner.ray_runner import RayLoopRunner

        runner = RayLoopRunner("ray-integ-loop-runner", MagicMock(), MagicMock())
        collected: list[Any] = []
        async for chunk in runner.run(_make_request(user_input="cluster")):
            collected.append(chunk)

    assert collected == [(("ns",), "messages", "echo:cluster")]


@pytest.mark.asyncio
async def test_ray_loop_runner_cancel_releases_blocked_run(ray_multi_node_cluster) -> None:
    """cancel() signals the actor so ``run`` finishes and the driver drains ``done``."""

    @ray.remote
    class HeldStubLoopRunnerActor:
        def __init__(self, _config: object) -> None:
            self._released = asyncio.Event()

        async def run(self, _request: LoopRunRequest, queue: Any) -> None:
            await queue.put_async(("chunk", (("ns",), "messages", "held")))
            await self._released.wait()
            await queue.put_async(("done", None))

        async def cancel(self) -> None:
            self._released.set()

    with patch("soothe_daemon.runner.ray_actor.LoopRunnerActor", HeldStubLoopRunnerActor):
        from soothe_daemon.runner.ray_runner import RayLoopRunner

        runner = RayLoopRunner("ray-integ-cancel", MagicMock(), MagicMock())
        collected: list[Any] = []
        drain_task = asyncio.create_task(_collect(runner.run(_make_request()), collected))
        await asyncio.sleep(0.5)
        await asyncio.wait_for(runner.cancel(), timeout=15.0)
        await asyncio.wait_for(drain_task, timeout=15.0)

    assert collected == [(("ns",), "messages", "held")]


async def _collect(gen: Any, out: list[Any]) -> None:
    async for item in gen:
        out.append(item)
