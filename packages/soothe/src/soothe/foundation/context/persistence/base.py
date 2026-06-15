"""Persistence protocol for the Context Engine (RFC-624)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from soothe.foundation.context.models import GoalStepDAG


@runtime_checkable
class ContextPersistenceProtocol(Protocol):
    """Backend for GoalStepDAG and ledger durability."""

    async def save_dag(self, dag: GoalStepDAG) -> None:
        """Persist the GoalStepDAG."""
        ...

    async def load_dag(self) -> GoalStepDAG | None:
        """Load the persisted GoalStepDAG, or None if absent."""
        ...

    async def save_ledger(self, messages: list[dict[str, Any]]) -> None:
        """Persist the serialized ledger messages."""
        ...

    async def load_ledger(self) -> list[dict[str, Any]]:
        """Load the persisted ledger messages."""
        ...

    async def clear(self) -> None:
        """Remove all persisted data."""
        ...
