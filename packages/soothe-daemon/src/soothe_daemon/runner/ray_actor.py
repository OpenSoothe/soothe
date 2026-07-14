"""Ray actor hosting SootheRunner in an isolated worker process (RFC-221).

WARNING: This file imports Ray at module level. It must NEVER be imported
by local-mode code paths. Only ``RayLoopRunner`` (ray_runner.py) imports it,
and only when ``SootheDaemonConfig.distributed.enabled=True``.
"""

from __future__ import annotations

import ray
from ray.util.queue import Queue
from soothe.protocols.runner import LoopRunRequest


@ray.remote
class LoopRunnerActor:
    """Ray actor that hosts one ``SootheRunner`` in a Ray worker process.

    Constructed once per loop via ``LoopRunnerActor.remote(config)``.
    Streams chunks into a caller-supplied ``ray.util.queue.Queue``.
    """

    def __init__(self, config: object) -> None:
        # Import deferred so the actor process initialises its own SootheRunner.
        from soothe.runner import SootheRunner

        self._runner = SootheRunner(config)  # type: ignore[arg-type]
        self._cancelled = False

    async def run(self, request: LoopRunRequest, queue: Queue) -> None:
        """Stream chunks from ``SootheRunner.astream()`` into ``queue``."""
        from soothe.runner.worker_logging import configure_loop_runner_worker_logging

        configure_loop_runner_worker_logging(self._runner.config, request.loop_id)

        try:
            from soothe.middleware._stream_turn_overrides import stream_turn_overrides

            with stream_turn_overrides(
                model=request.model,
                model_params=request.model_params or None,
                router_profile=request.router_profile,
            ):
                async for chunk in self._runner.astream(
                    request.user_input,
                    thread_id=request.thread_id,
                    workspace=request.resolve_workspace_path(),
                    max_iterations=request.max_iterations,
                    preferred_subagent=request.preferred_subagent,
                    client_loop_id=request.loop_id,
                    autopilot_job=request.autopilot_job,  # RFC-222 revised
                    clarification_mode=request.clarification_mode,
                    clarification_answer=request.clarification_answer,
                    clarification_answers=request.clarification_answers,
                ):
                    if self._cancelled:
                        break
                    await queue.put_async(("chunk", chunk))
        except Exception as exc:  # noqa: BLE001
            await queue.put_async(("error", exc))
            return
        await queue.put_async(("done", None))

    async def cancel(self) -> None:
        """Signal cooperative cancellation; checked between chunks in ``run()``."""
        self._cancelled = True


__all__ = ["LoopRunnerActor"]
