"""In-memory persistence backend for the Context Engine (RFC-624)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.context.models import GoalStepDAG, GoalStepDAGSnapshot

logger = logging.getLogger(__name__)


class InMemoryContextPersistence:
    """In-memory persistence for testing and ephemeral runs."""

    def __init__(self) -> None:
        self._dag_snapshot: GoalStepDAGSnapshot | None = None
        self._ledger_data: list[dict[str, Any]] = []

    async def save_dag(self, dag: GoalStepDAG) -> None:
        self._dag_snapshot = dag.snapshot()

    async def load_dag(self) -> GoalStepDAG | None:
        if self._dag_snapshot is None:
            return None
        dag = GoalStepDAG()
        dag.restore_from_snapshot(self._dag_snapshot)
        return dag

    async def save_ledger(self, messages: list[dict[str, Any]]) -> None:
        self._ledger_data = list(messages)

    async def load_ledger(self) -> list[dict[str, Any]]:
        return list(self._ledger_data)

    async def clear(self) -> None:
        self._dag_snapshot = None
        self._ledger_data.clear()
