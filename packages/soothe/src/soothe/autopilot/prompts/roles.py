"""Named Autopilot LLM system role strings (IG-736).

Short role prefixes only — rubrics live in ``fragments/``.
"""

from __future__ import annotations

SYSTEM_DAG_HEALTH = (
    "You are an expert at analyzing goal DAGs and identifying optimization opportunities."
)

SYSTEM_POST_COMPLETION = (
    "You are an expert at analyzing goal completion outcomes and determining follow-up actions."
)

SYSTEM_GOAL_PLACEMENT = (
    "You are an expert at analyzing goal placement in existing DAGs for optimal scheduling."
)

SYSTEM_BACKOFF = (
    "You are an expert at analyzing goal execution failures and determining "
    "optimal recovery strategies in goal DAGs."
)

# Prefixed into the consensus HumanMessage (invoke path is single-message today).
CONSENSUS_JUDGE_OPENER = "You are evaluating whether an AI agent has successfully completed a goal."

__all__ = [
    "CONSENSUS_JUDGE_OPENER",
    "SYSTEM_BACKOFF",
    "SYSTEM_DAG_HEALTH",
    "SYSTEM_GOAL_PLACEMENT",
    "SYSTEM_POST_COMPLETION",
]
