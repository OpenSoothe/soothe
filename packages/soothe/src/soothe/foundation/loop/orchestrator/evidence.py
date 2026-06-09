"""Plan evidence validation (RFC-220)."""

from __future__ import annotations

from typing import Any

from soothe.foundation.loop.state.schemas import AgentDecision, LoopState


def validate_plan_evidence(
    config: Any,
    state: LoopState,
    decision: AgentDecision,
) -> bool:
    """Return True when plan evidence validation passes.

    Per-step ``evidence_refs`` were removed from ``StepAction``; this hook remains
    for orchestrator topology and future ledger rules. When
    ``loop_orchestrator_evidence_validate`` is enabled, validation is currently a no-op.

    Args:
        config: Runtime configuration (toggle).
        state: Loop state including ledger and prior step results.
        decision: Scoped decision about to execute.

    Returns:
        True if valid or validation disabled.
    """
    del state, decision  # reserved for future ledger checks
    if not getattr(config.agent.loop, "loop_orchestrator_evidence_validate", True):
        return True
    return True
