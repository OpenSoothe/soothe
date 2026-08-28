"""Build the default clarification policy based on runtime mode."""

from __future__ import annotations

from typing import Literal

from soothe.sloop.clarification.auto import AutoClarificationPolicy, VeritasAnswerFn
from soothe.sloop.clarification.interactive import (
    EmitFn,
    InteractiveClarificationPolicy,
)
from soothe.sloop.clarification.protocol import ClarificationPolicy
from soothe.sloop.clarification.tool_approval_pipeline import ToolApprovalPipeline

ClarificationMode = Literal["manual", "auto"]


def build_default_clarification_policy(
    mode: ClarificationMode,
    *,
    veritas_answer: VeritasAnswerFn | None = None,
    emit: EmitFn | None = None,
    min_confidence: float = 0.4,
    interactive_fallback: ClarificationPolicy | None = None,
    force_manual_origins: tuple[str, ...] | list[str] | None = None,
    degrade_low_confidence: bool = False,
    tool_approval_pipeline: ToolApprovalPipeline | None = None,
    manual_allow_rules: bool = False,
) -> ClarificationPolicy:
    """Return the appropriate policy for the runtime mode.

    Args:
        mode: `"manual"` for TUI relay, `"auto"` for veritas.
        veritas_answer: Required when `mode == "auto"`. Callable that
            takes a :class:`ClarificationRequest` and returns a
            :class:`~soothe.subagents.veritas.schemas.VeritasAnswerSchema`.
        emit: Optional emit function for `InteractiveClarificationPolicy`.
        min_confidence: Threshold for auto policy.
        interactive_fallback: Optional policy injected into
            :class:`AutoClarificationPolicy`. Invoked when veritas
            itself fails (`DeferKind == "structured_output_failed"`) and a
            human is wired. Ignored for manual mode.
        force_manual_origins: Origins that skip veritas and use the interactive
            relay (or defer when no human is attached).
        degrade_low_confidence: When True, route low-confidence veritas
            results to the interactive fallback (auto→manual upgrade) instead
            of a hard defer. Ignored for manual mode.
        tool_approval_pipeline: Optional pipeline for deterministic
            tool-approval evaluation. In auto mode, deny →
            safety → allow stages resolve most `tool_approval` interrupts
            without an LLM (veritas remains the final guard). In manual mode
            it pre-filters the human relay: deny/safety always auto-reject,
            allow rules auto-approve only when `manual_allow_rules` is set.
        manual_allow_rules: Manual mode only — let allow rules auto-approve
            `tool_approval` actions instead of asking the human
            (`tool_approval.manual_scope: ambiguous_only`).

    Raises:
        ValueError: if `mode == "auto"` but `veritas_answer` is not provided.
    """
    if mode == "manual":
        return InteractiveClarificationPolicy(
            emit=emit,
            tool_approval_pipeline=tool_approval_pipeline,
            manual_allow_rules=manual_allow_rules,
        )
    if mode == "auto":
        if veritas_answer is None:
            msg = "auto mode requires veritas_answer callable"
            raise ValueError(msg)
        return AutoClarificationPolicy(
            veritas_answer,
            min_confidence=min_confidence,
            interactive_fallback=interactive_fallback,
            force_manual_origins=force_manual_origins,
            degrade_low_confidence=degrade_low_confidence,
            tool_approval_pipeline=tool_approval_pipeline,
        )
    msg = f"unknown clarification mode: {mode!r}"
    raise ValueError(msg)


__all__ = ["ClarificationMode", "build_default_clarification_policy"]
