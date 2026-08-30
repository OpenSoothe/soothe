"""Autopilot LLM prompts.

Autopilot-scoped prompt fragments and builders live here. Shared CoreAgent
and StrangeLoop prompt construction lives in `soothe.prompts`.

Reasoners and rail evaluators import builders/constants from this package;
they own invoke + parse only.

Raw fragment templates remain available from
`soothe_autopilot.prompts.fragments` / `.verify` when tests need them.
"""

from soothe_autopilot.prompts.consensus import build_consensus_prompt
from soothe_autopilot.prompts.guards import build_guard_messages
from soothe_autopilot.prompts.maturity import build_maturity_prompt
from soothe_autopilot.prompts.roles import (
    SYSTEM_BACKOFF,
    SYSTEM_DAG_HEALTH,
    SYSTEM_GOAL_PLACEMENT,
    SYSTEM_POST_COMPLETION,
)
from soothe_autopilot.prompts.verify import (
    format_goals_detail,
    format_step_progress,
    render_backoff_prompt,
    render_dag_health_prompt,
    render_goal_placement_prompt,
    render_post_completion_prompt,
)

__all__ = [
    "SYSTEM_BACKOFF",
    "SYSTEM_DAG_HEALTH",
    "SYSTEM_GOAL_PLACEMENT",
    "SYSTEM_POST_COMPLETION",
    "build_consensus_prompt",
    "build_guard_messages",
    "build_maturity_prompt",
    "format_goals_detail",
    "format_step_progress",
    "render_backoff_prompt",
    "render_dag_health_prompt",
    "render_goal_placement_prompt",
    "render_post_completion_prompt",
]
