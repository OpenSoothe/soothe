"""Verify / backoff prompt rendering and DAG format helpers (IG-736)."""

from __future__ import annotations

from soothe_autopilot.prompts.fragments import (
    BACKOFF_REASONING_PROMPT,
    DAG_HEALTH_VERIFICATION_PROMPT,
    GOAL_PLACEMENT_PROMPT,
    POST_COMPLETION_VERIFICATION_PROMPT,
)

__all__ = [
    "BACKOFF_REASONING_PROMPT",
    "DAG_HEALTH_VERIFICATION_PROMPT",
    "GOAL_PLACEMENT_PROMPT",
    "POST_COMPLETION_VERIFICATION_PROMPT",
    "format_goals_detail",
    "format_step_progress",
    "render_backoff_prompt",
    "render_dag_health_prompt",
    "render_goal_placement_prompt",
    "render_post_completion_prompt",
]


def format_goals_detail(goals: list[dict]) -> str:
    """Format goals list for prompt inclusion."""
    lines = []
    for g in goals:
        deps = ", ".join(g.get("depends_on", [])) or "none"
        status = g.get("status", "unknown")
        priority = g.get("priority", 50)
        desc = g.get("description", "")[:80]
        rail = g.get("rail_id") or ""
        rail_bit = f" rail={rail}" if rail else ""
        lines.append(f'  - {g["id"]}: [{status}] pri={priority}{rail_bit} deps=[{deps}] "{desc}"')
    return "\n".join(lines)


def format_step_progress(goals: list[dict]) -> str:
    """Format step progress for prompt inclusion."""
    total_steps = sum(g.get("step_count", 0) for g in goals)
    completed_steps = sum(g.get("completed_steps", 0) for g in goals)
    failed_steps = sum(g.get("failed_steps", 0) for g in goals)
    return f"Total: {total_steps} | Completed: {completed_steps} | Failed: {failed_steps}"


def render_dag_health_prompt(
    *,
    total_goals: int,
    active_count: int,
    pending_count: int,
    completed_count: int,
    failed_count: int,
    goals_detail: str,
    step_progress: str,
) -> str:
    """Render the DAG health verification user prompt."""
    return DAG_HEALTH_VERIFICATION_PROMPT.format(
        total_goals=total_goals,
        active_count=active_count,
        pending_count=pending_count,
        completed_count=completed_count,
        failed_count=failed_count,
        goals_detail=goals_detail,
        step_progress=step_progress,
    )


def render_post_completion_prompt(
    *,
    completed_goal_id: str,
    completed_description: str,
    outcome_summary: str,
    steps_executed: int,
    key_findings: str,
    total_duration_ms: int,
    total_tokens_used: int,
    pending_goals: str,
    active_goals: str,
) -> str:
    """Render the post-completion verification user prompt."""
    return POST_COMPLETION_VERIFICATION_PROMPT.format(
        completed_goal_id=completed_goal_id,
        completed_description=completed_description,
        outcome_summary=outcome_summary,
        steps_executed=steps_executed,
        key_findings=key_findings,
        total_duration_ms=total_duration_ms,
        total_tokens_used=total_tokens_used,
        pending_goals=pending_goals,
        active_goals=active_goals,
    )


def render_goal_placement_prompt(
    *,
    goal_description: str,
    active_count: int,
    pending_count: int,
    recently_completed: str,
    existing_goals: str,
) -> str:
    """Render the goal placement analysis user prompt."""
    return GOAL_PLACEMENT_PROMPT.format(
        goal_description=goal_description,
        active_count=active_count,
        pending_count=pending_count,
        recently_completed=recently_completed,
        existing_goals=existing_goals,
    )


def render_backoff_prompt(
    *,
    goal_id: str,
    goal_description: str,
    goal_dag_state: str,
    dependency_chain: str,
    evidence_source: str,
    structured_metrics: str,
    failure_narrative: str,
) -> str:
    """Render the backoff reasoning user prompt."""
    return BACKOFF_REASONING_PROMPT.format(
        goal_id=goal_id,
        goal_description=goal_description,
        goal_dag_state=goal_dag_state,
        dependency_chain=dependency_chain,
        evidence_source=evidence_source,
        structured_metrics=structured_metrics,
        failure_narrative=failure_narrative,
    )
