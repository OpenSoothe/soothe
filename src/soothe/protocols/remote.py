"""RemoteAgentProtocol -- remote agent invocation (RFC-0002 Module 6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@runtime_checkable
class RemoteAgentProtocol(Protocol):
    """Protocol for invoking remote agents via ACP, A2A, or LangGraph.

    Current implementations are accessed through `RemoteAgentProtocol`
    directly. Future remote backends may additionally be wrapped as
    deepagents `CompiledSubAgent` instances for uniform task-tool access.
    """

    async def invoke(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Invoke the remote agent and return the result.

        Args:
            task: The task description.
            context: Optional context to pass to the remote agent.

        Returns:
            The agent's result as text.
        """
        ...

    async def stream(self, task: str, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        """Stream results from the remote agent.

        Args:
            task: The task description.
            context: Optional context to pass to the remote agent.

        Yields:
            Incremental result chunks.
        """
        ...

    async def health_check(self) -> bool:
        """Check if the remote agent is reachable.

        Returns:
            True if the agent responded to a health check.
        """
        ...
