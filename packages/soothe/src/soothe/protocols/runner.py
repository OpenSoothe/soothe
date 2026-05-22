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

    Workspace resolution (``resolve_workspace_path()``):
        - ``client_workspace`` set → use that path directly in the runner.
        - else → ``$SOOTHE_HOME/workspaces/<normalized_user_id>/ws_<hash>`` where
          ``normalized_user_id`` is ``anonymous`` when ``user_id`` is empty, and
          hash uses ``user_id`` (or ``""``) with ``client_workspace_id`` or ``loop_id``.
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


__all__ = ["LoopRunRequest", "LoopRunnerProtocol", "StreamChunk"]
