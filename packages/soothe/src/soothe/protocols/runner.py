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
    # Intent hint to bypass LLM classification
    intent_hint: str | None = None
    # When True, the worker sets up an interrupt resolver that forwards
    # pending interrupts back to the daemon for interactive HITL resolution.
    interactive: bool = False


@dataclass
class InterruptPending:
    """Marker yielded by a loop runner when the worker hits an HITL interrupt.

    The daemon creates an ``asyncio.Future`` keyed by ``loop_id``, waits for
    the client to send ``resume_interrupts``, then forwards the payload back
    to the worker via ``forward_interrupt_resume``.
    """

    loop_id: str
    pending_interrupts: dict[str, Any]


class LoopRunnerProtocol(Protocol):
    """Structural interface satisfied by all loop runner implementations.

    Consumers (``QueryEngine``) depend only on this interface. The concrete
    runtime — ``LocalLoopRunner`` (multiprocessing) or ``RayLoopRunner`` (Ray
    actor) — is selected by ``soothe_daemon.runner.LoopRunnerFactory`` based
    on ``SootheDaemonConfig``.
    """

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk | InterruptPending]:
        """Execute the loop; yield ``StreamChunk`` tuples until completion.

        When the worker hits an HITL interrupt and the request is interactive,
        yields an ``InterruptPending`` marker. The consumer must call
        ``forward_interrupt_resume`` with the resolved payload so the worker
        can continue.
        """
        ...

    async def cancel(self) -> None:
        """Request cancellation of the running loop."""
        ...

    async def forward_interrupt_resume(self, loop_id: str, payload: dict[str, Any]) -> None:
        """Deliver an interrupt resume payload to the worker handling ``loop_id``."""
        ...


__all__ = ["InterruptPending", "LoopRunRequest", "LoopRunnerProtocol"]
