"""Completion, consensus, maturity, and DAG health verification."""

from __future__ import annotations

from typing import Any

__all__ = [
    "ConsensusEvaluationError",
    "ConsensusVerdict",
    "GoalBackoffReasoner",
    "GoalDAGVerifier",
    "JobMaturityAssessor",
    "JobMaturitySnapshot",
    "acceptance_contract_brief",
    "evaluate_goal_completion",
    "latch_acceptance_met",
    "load_goal_md_excerpt",
    "maturity_wire_fields",
]

_LAZY: dict[str, tuple[str, str]] = {
    "ConsensusEvaluationError": (".consensus", "ConsensusEvaluationError"),
    "ConsensusVerdict": (".consensus", "ConsensusVerdict"),
    "evaluate_goal_completion": (".consensus", "evaluate_goal_completion"),
    "GoalBackoffReasoner": (".backoff_reasoner", "GoalBackoffReasoner"),
    "GoalDAGVerifier": (".goal_dag_verifier", "GoalDAGVerifier"),
    "JobMaturityAssessor": (".maturity", "JobMaturityAssessor"),
    "JobMaturitySnapshot": (".maturity", "JobMaturitySnapshot"),
    "acceptance_contract_brief": (".maturity", "acceptance_contract_brief"),
    "latch_acceptance_met": (".maturity", "latch_acceptance_met"),
    "load_goal_md_excerpt": (".maturity", "load_goal_md_excerpt"),
    "maturity_wire_fields": (".maturity", "maturity_wire_fields"),
}


def __getattr__(name: str) -> Any:
    """Lazy-load verify symbols to avoid import cycles with monitor."""
    target = _LAZY.get(name)
    if target is None:
        error_msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(error_msg)
    module_name, attr = target
    from importlib import import_module

    mod = import_module(module_name, __name__)
    return getattr(mod, attr)
