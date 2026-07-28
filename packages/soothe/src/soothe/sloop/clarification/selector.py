"""Build the default clarification policy based on runtime mode (RFC-622)."""

from __future__ import annotations

from typing import Literal

from soothe.sloop.clarification.auto import AutoClarificationPolicy, VeritasAnswerFn
from soothe.sloop.clarification.interactive import (
    EmitFn,
    InteractiveClarificationPolicy,
)
from soothe.sloop.clarification.protocol import ClarificationPolicy

ClarificationMode = Literal["manual", "auto"]


def build_default_clarification_policy(
    mode: ClarificationMode,
    *,
    veritas_answer: VeritasAnswerFn | None = None,
    emit: EmitFn | None = None,
    min_confidence: float = 0.4,
    interactive_fallback: ClarificationPolicy | None = None,
    force_manual_origins: tuple[str, ...] | list[str] | None = None,
) -> ClarificationPolicy:
    """Return the appropriate policy for the runtime mode.

    Args:
        mode: ``"manual"`` for TUI relay, ``"auto"`` for veritas.
        veritas_answer: Required when ``mode == "auto"``. Callable that
            takes a :class:`ClarificationRequest` and returns a
            :class:`~soothe.subagents.veritas.schemas.VeritasAnswerSchema`.
        emit: Optional emit function for ``InteractiveClarificationPolicy``.
        min_confidence: Threshold for auto policy.
        interactive_fallback: Optional policy injected into
            :class:`AutoClarificationPolicy` (RFC-623). Invoked when veritas
            itself fails (``DeferKind == "structured_output_failed"``) and a
            human is wired. Ignored for manual mode.
        force_manual_origins: Origins that skip veritas and use the interactive
            relay (or defer when no human is attached).

    Raises:
        ValueError: if ``mode == "auto"`` but ``veritas_answer`` is not provided.
    """
    if mode == "manual":
        return InteractiveClarificationPolicy(emit=emit)
    if mode == "auto":
        if veritas_answer is None:
            msg = "auto mode requires veritas_answer callable"
            raise ValueError(msg)
        return AutoClarificationPolicy(
            veritas_answer,
            min_confidence=min_confidence,
            interactive_fallback=interactive_fallback,
            force_manual_origins=force_manual_origins,
        )
    msg = f"unknown clarification mode: {mode!r}"
    raise ValueError(msg)


__all__ = ["ClarificationMode", "build_default_clarification_policy"]
