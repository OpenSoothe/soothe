"""Loop runner protocol definitions (RFC-221)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""


@dataclass
class LoopRunRequest:
    """All parameters needed to run one agent loop in a subprocess.

    Consolidates fields previously passed ad-hoc to ``SootheRunner.astream()``,
    including thread/workspace binding that was mutated on the shared singleton
    via ``bind_execution_thread_for_loop()``.
    """

    loop_id: str
    thread_id: str
    user_input: str
    workspace: str | None = None
    autonomous: bool = False
    max_iterations: int | None = None
    preferred_subagent: str | None = None
    model: str | None = None
    model_params: dict[str, Any] = field(default_factory=dict)
    # Worker pool timeout and cancellation support
    timeout_seconds: float | None = None


class LoopRunnerProtocol(Protocol):
    """Structural interface satisfied by all loop runner implementations.

    Consumers (``QueryEngine``) depend only on this interface. The concrete
    runtime — ``LocalLoopRunner`` (multiprocessing) or ``RayLoopRunner`` (Ray
    actor) — is selected by ``LoopRunnerFactory`` based on daemon config.
    """

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Execute the loop; yield ``StreamChunk`` tuples until completion."""
        ...

    async def cancel(self) -> None:
        """Request cancellation of the running loop."""
        ...


__all__ = ["LoopRunRequest", "LoopRunnerProtocol"]
