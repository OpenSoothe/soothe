"""Recognize structured ``ask_user`` interrupts emitted by CoreAgent."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from soothe.foundation.sloop.clarification.protocol import (
    ClarificationOrigin,
    ClarificationRequest,
    LoopStateView,
)


class ClarificationDetector:
    """Detect structured ``ask_user`` interrupts from a LangGraph stream.

    Plain-text questions in assistant messages are intentionally *not* detected.
    Code paths that want a clarification must emit a structured
    ``interrupt({"type": "ask_user", "questions": [...]})``; otherwise the
    relay does not engage and the model's text is treated as a normal turn.
    """

    def from_interrupt(
        self,
        value: Any,
        *,
        interrupt_id: str,
        origin_node: ClarificationOrigin,
        loop_state: LoopStateView,
    ) -> ClarificationRequest | None:
        """Return a request if ``value`` is a structured ``ask_user`` interrupt."""
        if not isinstance(value, Mapping):
            return None
        if value.get("type") != "ask_user":
            return None
        questions = self._extract_questions(value)
        if not questions:
            return None
        return ClarificationRequest(
            questions=questions,
            origin_node=origin_node,
            origin_interrupt_id=interrupt_id,
            loop_state=loop_state,
        )

    @staticmethod
    def _extract_questions(value: Mapping[str, Any]) -> tuple[str, ...]:
        raw = value.get("questions")
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            cleaned = tuple(str(q).strip() for q in raw if str(q).strip())
            if cleaned:
                return cleaned
        single = value.get("question")
        if isinstance(single, str) and single.strip():
            return (single.strip(),)
        return ()
