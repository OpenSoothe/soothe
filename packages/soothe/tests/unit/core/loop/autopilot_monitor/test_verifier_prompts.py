"""Tests for autopilot monitor LLM prompt templates."""

from __future__ import annotations

from soothe.autopilot.verifier_prompts import (
    DAG_HEALTH_VERIFICATION_PROMPT,
    GOAL_PLACEMENT_PROMPT,
    POST_COMPLETION_VERIFICATION_PROMPT,
)


def test_goal_placement_prompt_format_includes_json_example() -> None:
    """JSON example braces must not break str.format() (KeyError on 'priority')."""
    prompt = GOAL_PLACEMENT_PROMPT.format(
        goal_description="verify cron dispatch",
        active_count=1,
        pending_count=2,
        recently_completed="none",
        existing_goals='  - g1: [pending] pri=50 deps=[none] "task"',
    )

    assert "verify cron dispatch" in prompt
    assert '"priority": 50' in prompt
    assert "{goal_description}" not in prompt


def test_dag_health_prompt_format_includes_json_example() -> None:
    """DAG health prompt JSON example must survive .format()."""
    prompt = DAG_HEALTH_VERIFICATION_PROMPT.format(
        total_goals=4,
        active_count=1,
        pending_count=2,
        completed_count=1,
        failed_count=0,
        goals_detail="  - g1: [active] pri=50",
        step_progress="Total: 5 | Completed: 2 | Failed: 0",
    )

    assert '"reset_goals"' in prompt
    assert "{total_goals}" not in prompt


def test_post_completion_prompt_format_substitutes_completed_goal_id() -> None:
    """Post-completion prompt keeps completed_goal_id in JSON example."""
    prompt = POST_COMPLETION_VERIFICATION_PROMPT.format(
        completed_goal_id="goal-99",
        completed_description="done",
        outcome_summary="ok",
        steps_executed=3,
        key_findings="none",
        total_duration_ms=1000,
        total_tokens_used=50,
        pending_goals="none",
        active_goals="none",
    )

    assert "goal-99" in prompt
    assert '"depends_on": ["goal-99"]' in prompt
