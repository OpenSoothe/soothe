"""Job maturity assessment prompt assembly (IG-736)."""

from __future__ import annotations

from soothe.autopilot.prompts.fragments import (
    MATURITY_ASSESS_CLOSING,
    MATURITY_ASSESS_INSTRUCTIONS,
)

__all__ = ["build_maturity_prompt"]

_NO_CONTRACT_NOTE = (
    "\nNo explicit GOAL.md / verification_rules. Infer success criteria "
    "from the job root description and completed child goals; be "
    "conservative about acceptance_met."
)


def build_maturity_prompt(
    *,
    verification_rules: str,
    goal_md: str,
    dag_summary: str,
    workspace_inventory: str,
    qa_response: str,
) -> str:
    """Build the job maturity assessment prompt.

    Args:
        verification_rules: Optional operator criteria from job_create.
        goal_md: Optional GOAL.md body.
        dag_summary: Job DAG summary text.
        workspace_inventory: Shallow workspace listing.
        qa_response: Latest QA/verify response excerpt.

    Returns:
        Assembled prompt (instructions + evidence envelope + closing).
    """
    parts = [MATURITY_ASSESS_INSTRUCTIONS]
    if verification_rules.strip():
        parts.append(f"\nverification_rules:\n{verification_rules.strip()}")
    if goal_md.strip():
        parts.append(f"\nGOAL.md:\n{goal_md.strip()}")
    if not verification_rules.strip() and not goal_md.strip():
        parts.append(_NO_CONTRACT_NOTE)
    if dag_summary.strip():
        parts.append(f"\nJob DAG:\n{dag_summary.strip()}")
    if workspace_inventory.strip():
        parts.append(f"\nWorkspace inventory (shallow):\n{workspace_inventory.strip()}")
    if qa_response.strip():
        parts.append(f"\nLatest QA/verify response:\n{qa_response.strip()}")
    parts.append(f"\n{MATURITY_ASSESS_CLOSING}")
    return "\n".join(parts)
