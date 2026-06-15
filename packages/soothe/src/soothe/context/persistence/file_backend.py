"""File-based persistence backend for the Context Engine (RFC-624)."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from soothe.context.models import GoalStepDAG, GoalStepDAGSnapshot

logger = logging.getLogger(__name__)


class FileContextPersistence:
    """File-based persistence under SOOTHE_HOME/data/context_engine/{loop_id}/.

    Stores:
    - ``goal_step_dag.json`` — serialized GoalStepDAG
    - ``ledger.json`` — serialized message ledger

    All file I/O runs via ``asyncio.to_thread`` to avoid blocking the event loop.
    """

    def __init__(self, loop_id: str, soothe_home: Path) -> None:
        self._dir = soothe_home / "data" / "context_engine" / loop_id
        self._dag_path = self._dir / "goal_step_dag.json"
        self._ledger_path = self._dir / "ledger.json"

    async def save_dag(self, dag: GoalStepDAG) -> None:
        snapshot = dag.snapshot()
        data = snapshot.model_dump(mode="json")
        json_str = json.dumps(data, indent=2, default=str)

        def _write() -> None:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._dag_path.with_suffix(".tmp")
            tmp.write_text(json_str, encoding="utf-8")
            tmp.replace(self._dag_path)

        try:
            await asyncio.to_thread(_write)
        except Exception:
            logger.warning("[CE] Failed to save DAG to file", exc_info=True)

    async def load_dag(self) -> GoalStepDAG | None:
        def _read() -> str | None:
            if not self._dag_path.is_file():
                return None
            return self._dag_path.read_text(encoding="utf-8")

        try:
            json_str = await asyncio.to_thread(_read)
        except Exception:
            logger.warning("[CE] Failed to load DAG from file", exc_info=True)
            return None

        if json_str is None:
            return None

        try:
            data = json.loads(json_str)
            snapshot = GoalStepDAGSnapshot.model_validate(data)
            dag = GoalStepDAG()
            dag.restore_from_snapshot(snapshot)
            return dag
        except Exception:
            logger.warning("[CE] Failed to parse DAG snapshot", exc_info=True)
            return None

    async def save_ledger(self, messages: list[dict[str, Any]]) -> None:
        json_str = json.dumps(messages, indent=2, default=str)

        def _write() -> None:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._ledger_path.with_suffix(".tmp")
            tmp.write_text(json_str, encoding="utf-8")
            tmp.replace(self._ledger_path)

        try:
            await asyncio.to_thread(_write)
        except Exception:
            logger.warning("[CE] Failed to save ledger to file", exc_info=True)

    async def load_ledger(self) -> list[dict[str, Any]]:
        def _read() -> str | None:
            if not self._ledger_path.is_file():
                return None
            return self._ledger_path.read_text(encoding="utf-8")

        try:
            json_str = await asyncio.to_thread(_read)
        except Exception:
            logger.warning("[CE] Failed to load ledger from file", exc_info=True)
            return []

        if json_str is None:
            return []

        try:
            return json.loads(json_str)
        except Exception:
            logger.warning("[CE] Failed to parse ledger JSON", exc_info=True)
            return []

    async def clear(self) -> None:
        def _clear() -> None:
            for path in (self._dag_path, self._ledger_path):
                if path.is_file():
                    path.unlink()
            if self._dir.is_dir():
                try:
                    self._dir.rmdir()
                except OSError:
                    pass

        try:
            await asyncio.to_thread(_clear)
        except Exception:
            logger.warning("[CE] Failed to clear CE files", exc_info=True)
