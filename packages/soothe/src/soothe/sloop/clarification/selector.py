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
    degrade_to_manual_on_failure: bool = True,
    autopilot_retry_on_fail: bool = True,
    tool_approval_pipeline: ToolApprovalPipeline | None = None,
    manual_allow_rules: bool = False,
    # Backward-compat alias (deprecated).
    degrade_low_confidence: bool | None = None,
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
            :class:`AutoClarificationPolicy`. Invoked when veritas fails and
            a human is wired (TUI auto→manual upgrade).
        force_manual_origins: Origins that skip veritas and use the interactive
            relay (or defer when no human is attached).
        degrade_to_manual_on_failure: When True, route *all* veritas failures
            to the interactive fallback (TUI only). Ignored for manual mode.
        autopilot_retry_on_fail: When True and no human is attached, veritas
            failures return a synthetic retry answer so the LLM tries a
            different action instead of parking the goal.
        tool_approval_pipeline: Optional pipeline for deterministic
            tool-approval evaluation. In auto mode, deny →
            safety → allow stages resolve most `tool_approval` interrupts
            without an LLM (veritas remains the final guard). In manual mode
            it pre-filters the human relay: deny/safety always auto-reject,
            allow rules auto-approve only when `manual_allow_rules` is set.
        manual_allow_rules: Manual mode only — let allow rules auto-approve
            `tool_approval` actions instead of asking the human
            (`tool_approval.manual_scope: ambiguous_only`).
        degrade_low_confidence: Deprecated alias for
            `degrade_to_manual_on_failure`. When set, overrides the new flag.

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
        if degrade_low_confidence is not None:
            degrade_to_manual_on_failure = degrade_low_confidence
        return AutoClarificationPolicy(
            veritas_answer,
            min_confidence=min_confidence,
            interactive_fallback=interactive_fallback,
            force_manual_origins=force_manual_origins,
            degrade_to_manual_on_failure=degrade_to_manual_on_failure,
            autopilot_retry_on_fail=autopilot_retry_on_fail,
            tool_approval_pipeline=tool_approval_pipeline,
        )
    msg = f"unknown clarification mode: {mode!r}"
    raise ValueError(msg)


__all__ = ["ClarificationMode", "build_default_clarification_policy"]
