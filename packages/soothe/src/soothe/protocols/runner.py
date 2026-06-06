"""Loop runner protocol definitions (RFC-221, extended by RFC-222 revised)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from soothe.core.goal_engine.models import GoalDispatchContextBundle

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""


@dataclass(frozen=True)
class GoalDispatchEnvelope:
    """Transient dispatch message for worker goal execution (RFC-222 revised).

    This is a **wire message**, not a persistent entity. Created by the daemon's
    ``AutopilotService`` when dispatching a goal to a subprocess worker, and
    consumed by the worker's ``SootheRunner.astream(autopilot_job=...)`` path.

    **Terminology note (RFC-228):**
    - "Job" in RFC-228/Desktop UX = user-facing term for a **root Goal** (persistent)
    - ``GoalDispatchEnvelope`` here = transient dispatch **message** (not stored)

    Attached to ``LoopRunRequest.autopilot_job`` when present. The worker
    hydrates AgentLoop from ``merged_context`` and executes ``goal_description``,
    ignoring ``LoopRunRequest.user_input``. When ``None``, the worker runs
    solo-mode behavior — today's path, unchanged.

    Attributes:
        goal_id: Daemon's canonical goal id.
        goal_description: Frozen at dispatch time.
        merged_context: Pre-projected hydration bundle from the daemon's
            ``ContextProjector``. Worker treats it as opaque.
        deadline_seconds: Wall-clock budget for this attempt; ``None`` = no cap.
        attempt: 1 on first dispatch, N on retry/backoff.
    """

    goal_id: str
    goal_description: str
    merged_context: GoalDispatchContextBundle
    deadline_seconds: float | None = None
    attempt: int = 1


# Backward-compatible alias for gradual migration (deprecated)
AutopilotJob = GoalDispatchEnvelope
"""Deprecated alias for GoalDispatchEnvelope.

Will be removed in a future release. Use GoalDispatchEnvelope instead.
"""


@dataclass
class LoopRunRequest:
    """All parameters needed to run one agent loop in a subprocess.

    Consolidates fields previously passed ad-hoc to ``SootheRunner.astream()``,
    including thread/workspace binding that was mutated on the shared singleton
    via ``bind_execution_thread_for_loop()``.

    Workspace resolution (``resolve_workspace_path()``):
        - ``client_workspace`` set → use that path directly in the runner.
        - else → ``$SOOTHE_HOME/workspaces/<normalized_user_id>/ws_<hash>`` where
          ``normalized_user_id`` is ``anonymous`` when ``user_id`` is empty, and
          hash uses ``user_id`` (or ``""``) with ``client_workspace_id`` or ``loop_id``.

    RFC-222 revised extension (additive): when ``autopilot_job`` is set, this
    request is dispatched by the daemon's ``AutopilotService``; the worker
    branches to a hydrate-from-bundle path. When ``None``, the worker runs
    today's solo-mode path. The ``LoopRunnerProtocol.run`` signature is
    unchanged.
    """

    loop_id: str
    thread_id: str
    user_input: str
    client_workspace: str | None = None
    user_id: str | None = None
    client_workspace_id: str | None = None
    autonomous: bool = False
    max_iterations: int | None = None
    preferred_subagent: str | None = None
    model: str | None = None
    model_params: dict[str, Any] = field(default_factory=dict)
    # Worker pool timeout and cancellation support
    timeout_seconds: float | None = None
    # Intent hint to bypass LLM classification
    intent_hint: str | None = None
    # RFC-622: per-request clarification mode ("auto" / "manual" / None for daemon default)
    clarification_mode: str | None = None
    # RFC-622: when True, the runner treats ``user_input`` as the answer to the
    # loop's currently pending clarification interrupt and resumes the graph
    # via ``Command(resume=...)`` instead of starting a new turn. The runner
    # verifies via the loop's persisted ``pending_clarification`` state and
    # falls back to a normal turn when no clarification is pending.
    clarification_answer: bool = False
    # RFC-622: per-question answers paired with clarification_answer=True. When
    # provided, the runner resumes the graph with one answer per question
    # instead of broadcasting a single concatenated string. None falls back to
    # treating user_input as a single answer string (broadcast to all questions
    # if there are several).
    clarification_answers: list[str] | None = None
    # RFC-222 revised: set by daemon's AutopilotService for autopilot-dispatched
    # goals. None for solo-mode requests (default).
    autopilot_job: GoalDispatchEnvelope | None = None

    def resolve_workspace_path(self) -> str:
        """Absolute workspace path for ``SootheRunner.astream(workspace=...)``."""
        from soothe.core.workspace.loop_workspace import resolve_loop_workspace

        return str(
            resolve_loop_workspace(
                loop_id=self.loop_id,
                client_workspace=self.client_workspace,
                user_id=self.user_id,
                client_workspace_id=self.client_workspace_id,
            )
        )


class LoopRunnerProtocol(Protocol):
    """Structural interface satisfied by all loop runner implementations.

    Consumers (``QueryEngine``) depend only on this interface. The concrete
    runtime — ``LocalLoopRunner`` (multiprocessing) or ``RayLoopRunner`` (Ray
    actor) — is selected by ``soothe_daemon.runner.LoopRunnerFactory`` based
    on ``SootheDaemonConfig``.
    """

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Execute the loop; yield ``StreamChunk`` tuples until completion."""
        ...

    async def cancel(self) -> None:
        """Request cancellation of the running loop."""
        ...


__all__ = [
    "GoalDispatchEnvelope",
    "AutopilotJob",
    "LoopRunRequest",
    "LoopRunnerProtocol",
    "StreamChunk",
]
