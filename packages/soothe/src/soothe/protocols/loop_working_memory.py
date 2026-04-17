"""LoopWorkingMemoryProtocol — agentic Plan-Execute scratchpad (RFC-203)."""

from __future__ import annotations

from typing import Protocol


class LoopWorkingMemoryProtocol(Protocol):
    """Bounded working memory for Layer 2 Plan prompts; optional workspace spill."""

    def clear(self) -> None:
        """Reset for a new goal."""
        ...

    def record_step_result(
        self,
        *,
        step_id: str,
        description: str,
        output: str | None,
        error: str | None,
        success: bool,
        workspace: str | None,
        thread_id: str,
    ) -> None:
        """Record one Act step outcome."""
        ...

    def render_for_reason(self, *, max_chars: int | None = None) -> str:
        """Return text for Reason prompt injection."""
        ...
