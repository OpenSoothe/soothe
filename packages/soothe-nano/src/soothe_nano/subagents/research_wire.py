"""Shared wire emit helpers for iterative research subagents."""

from __future__ import annotations

import logging
from typing import Any

from soothe_nano.utils.subagent_emit import emit_subagent_wire_event


class ResearchWireEmitter:
    """Emit unified research progress and step wire events."""

    def __init__(
        self,
        *,
        progress_event_type: type[Any],
        step_event_type: type[Any],
        logger: logging.Logger,
    ) -> None:
        self._progress_event_type = progress_event_type
        self._step_event_type = step_event_type
        self._logger = logger

    def progress(
        self,
        phase: str,
        message: str,
        *,
        loop_count: int = 0,
        total_loops: int = 0,
    ) -> None:
        """Emit ``soothe.subagent.<id>.progress``."""
        emit_subagent_wire_event(
            self._progress_event_type(
                phase=phase,
                message=message,
                loop_count=loop_count,
                total_loops=total_loops,
            ).to_dict(),
            self._logger,
        )

    def step(self, tool_name: str, args_preview: str, *, duration_ms: int = 0) -> None:
        """Emit ``soothe.subagent.<id>.step.completed``."""
        emit_subagent_wire_event(
            self._step_event_type(
                tool_name=tool_name,
                args_preview=args_preview,
                duration_ms=duration_ms,
            ).to_dict(),
            self._logger,
        )


__all__ = ["ResearchWireEmitter"]
