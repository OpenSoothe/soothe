"""Unified Interrupt Relay — public API.

Single-interrupt design: only the CoreAgent calls LangGraph `interrupt()`.
The StrangeLoop exits cleanly and is re-invoked when the answer arrives.

Lifecycle:

    capture()               → executor detects interrupt, stores row
    park()                  → emits request, marks CE goal, exits
    submit_answer()         → human/veritas provides answer, unblocks goal
    build_resume_directive() → runner gets graph_input + core_agent_resume
    get_core_agent_resume()  → execute node injects Command(resume=...)
    consume()               → marks row consumed (lifecycle done)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.protocol import (
    ClarificationPolicy,
    LoopStateView,
)
from soothe.sloop.relay.capture import capture_interrupt
from soothe.sloop.relay.park import park_clarification
from soothe.sloop.relay.reconcile import reconcile_clarification
from soothe.sloop.relay.resume import (
    build_resume_directive as _build_resume_directive,
)
from soothe.sloop.relay.resume import (
    consume_clarification,
    get_core_agent_resume,
)
from soothe.sloop.relay.resume import submit_answer as _submit_answer
from soothe.sloop.relay.store import ClarificationStore
from soothe.sloop.relay.telemetry import RelayTelemetry
from soothe.sloop.relay.types import (
    CoreAgentResumeSpec,
    ParkOutcome,
    ReconcileReport,
    RelayGraphProjection,
    RelayHandle,
    ResumeDirective,
    SubmitResult,
    projection_to_state,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.sloop.relay.types import AnswerSource, PolicyMode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelayConfig:
    """Backpressure and circuit-breaker config.

    Attributes:
        max_pending_per_goal: Per-goal FIFO cap.
        max_consecutive_retries: Circuit breaker cap for retry sentinels.
    """

    max_pending_per_goal: int = 3
    max_consecutive_retries: int = 5


class InterruptRelay:
    """Unified interrupt relay between the StrangeLoop and CoreAgent graphs.

    Construct one instance per loop. The store is loop-scoped (same DB file
    shared across loops). The detector is stateless and shared.

    Example:
        relay = InterruptRelay(
            store=resolve_clarification_store(config, loop_id),
            config=RelayConfig(),
        )
        handle = await relay.capture(...)
        outcome = await relay.park(handle, policy=policy)
    """

    def __init__(
        self,
        *,
        store: ClarificationStore,
        config: RelayConfig | None = None,
        detector: ClarificationDetector | None = None,
        telemetry: RelayTelemetry | None = None,
    ) -> None:
        self._store = store
        self._config = config or RelayConfig()
        self._detector = detector or ClarificationDetector()
        self._telemetry = telemetry or RelayTelemetry()
        # The last handle from `capture()` so `park()` can use it.
        # Set by the executor, read by `await_clarification`.
        # Not durable — per-invocation only.
        self.pending_handle: RelayHandle | None = None

    @property
    def store(self) -> ClarificationStore:
        return self._store

    @property
    def telemetry(self) -> RelayTelemetry:
        return self._telemetry

    async def capture(
        self,
        *,
        interrupt_value: Any,
        interrupt_id: str,
        thread_id: str | None,
        step_id: str | None,
        step_description: str | None,
        loop_id: str,
        goal_id: str,
        loop_state: LoopStateView,
        origin_node: str,
        policy_mode: PolicyMode,
    ) -> RelayHandle | None:
        """Detect, persist, and return a handle for a captured interrupt."""
        self._telemetry.increment("capture_attempts")
        handle = await capture_interrupt(
            self._store,
            self._detector,
            interrupt_value=interrupt_value,
            interrupt_id=interrupt_id,
            thread_id=thread_id,
            step_id=step_id,
            step_description=step_description,
            loop_id=loop_id,
            goal_id=goal_id,
            loop_state=loop_state,
            origin_node=origin_node,
            policy_mode=policy_mode,
            max_pending_per_goal=self._config.max_pending_per_goal,
        )
        if handle is not None:
            self._telemetry.increment("capture_ok")
        else:
            self._telemetry.increment("capture_unmanaged")
        return handle

    async def park(
        self,
        handle: RelayHandle,
        *,
        policy: ClarificationPolicy | None,
        ce: Any | None = None,
        emit: Any | None = None,
        plan_path: str | None = None,
        plan_markdown: str | None = None,
    ) -> ParkOutcome:
        """Park a captured clarification for human or auto resolution."""
        self._telemetry.increment("park_attempts")
        outcome = await park_clarification(
            self._store,
            handle,
            policy=policy,
            ce=ce,
            emit=emit,
            plan_path=plan_path,
            plan_markdown=plan_markdown,
            max_consecutive_retries=self._config.max_consecutive_retries,
        )
        self._telemetry.increment(f"park_{outcome.kind}")
        return outcome

    async def submit_answer(
        self,
        *,
        relay_id: str,
        answers: tuple[str, ...] | list[str],
        source: AnswerSource,
        idempotency_key: str | None = None,
        ce: Any | None = None,
        emit: Any | None = None,
    ) -> SubmitResult:
        """Submit an answer to a parked clarification (idempotent)."""
        result = await _submit_answer(
            self._store,
            relay_id=relay_id,
            answers=answers,
            source=source,
            idempotency_key=idempotency_key,
            ce=ce,
            emit=emit,
        )
        self._telemetry.increment(f"submit_{result.status}")
        return result

    async def build_resume_directive(
        self, *, relay_id: str, ce: Any | None = None, checkpointer: Any | None = None
    ) -> ResumeDirective:
        """Build the StrangeLoop re-invoke plan for an answered clarification.

        Raises `RelayStateConflictError` on inconsistency,
        `CoreAgentThreadEvictedError` when the CoreAgent thread's interrupt is gone.
        """
        return await _build_resume_directive(
            self._store,
            relay_id=relay_id,
            ce=ce,
            checkpointer=checkpointer,
        )

    async def reconcile(
        self, *, relay_id: str, ce: Any | None = None, checkpointer: Any | None = None
    ) -> ReconcileReport:
        """Three-way consistency check (relay store, CE, CoreAgent)."""
        return await reconcile_clarification(
            self._store,
            relay_id=relay_id,
            ce=ce,
            checkpointer=checkpointer,
        )

    async def get_core_agent_resume(self, *, relay_id: str) -> CoreAgentResumeSpec | None:
        """Get the CoreAgent `Command(resume=...)` spec for an answered row."""
        return await get_core_agent_resume(self._store, relay_id=relay_id)

    async def consume(self, *, relay_id: str) -> None:
        """Mark a clarification row as consumed (lifecycle complete)."""
        await consume_clarification(self._store, relay_id=relay_id)
        self._telemetry.increment("consumed")

    def project_for_graph(self, handle: RelayHandle) -> RelayGraphProjection:
        """Project a handle into StrangeLoop graph channels."""
        from soothe.sloop.clarification.protocol import request_to_state

        return RelayGraphProjection(
            pending_clarification=request_to_state(handle.request),
            resume_relay_id=handle.relay_id,
            last_clarification_origin=handle.origin,
        )

    @staticmethod
    def projection_to_state(projection: RelayGraphProjection) -> dict[str, Any]:
        """Serialize a projection for LangGraph channel storage."""
        return projection_to_state(projection)


def create_relay(
    config: SootheConfig, loop_id: str, *, relay_config: RelayConfig | None = None
) -> InterruptRelay:
    """Factory: build an `InterruptRelay` from config and `loop_id`."""
    from soothe.sloop.relay.store import resolve_clarification_store

    store = resolve_clarification_store(config, loop_id)
    if relay_config is None:
        cfg = config.agent.clarification
        relay_config = RelayConfig(
            max_pending_per_goal=getattr(cfg, "max_pending_per_goal", 3),
            max_consecutive_retries=getattr(cfg, "max_consecutive_retries", 5),
        )
    return InterruptRelay(
        store=store,
        config=relay_config,
    )


__all__ = [
    "InterruptRelay",
    "RelayConfig",
    "create_relay",
]
