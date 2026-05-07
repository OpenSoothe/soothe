"""Plan evidence validation (RFC-220)."""

from __future__ import annotations

from typing import Any

from soothe.core.agent_loop.state.schemas import AgentDecision, LoopState


def validate_plan_evidence(
    config: Any,
    state: LoopState,
    decision: AgentDecision,
) -> bool:
    """Return True when every step cites allowed evidence ids.

    When ``evidence_ledger`` is empty, validation is a no-op. When non-empty,
    each step must declare non-empty ``evidence_refs`` and each ref must appear
    in the ledger or name a successful prior step id.

    Args:
        config: Runtime configuration (toggle).
        state: Loop state including ledger and prior step results.
        decision: Scoped decision about to execute.

    Returns:
        True if valid or validation disabled / ledger empty.
    """
    if not getattr(config.agent_loop, "loop_orchestrator_evidence_validate", True):
        return True
    if not state.evidence_ledger:
        return True

    ledger_ids = {e.evidence_id for e in state.evidence_ledger}
    prior_ok_steps = {r.step_id for r in state.step_results if r.success}
    allowed = ledger_ids | prior_ok_steps

    for step in decision.steps:
        if not step.evidence_refs:
            return False
        for ref in step.evidence_refs:
            if ref not in allowed:
                return False
    return True
