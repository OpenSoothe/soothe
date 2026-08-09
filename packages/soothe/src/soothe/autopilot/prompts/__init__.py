"""Autopilot LLM prompts (IG-736).

Autopilot-scoped prompt fragments and builders live here, mirroring
``soothe.sloop.prompts``. Systemwide prompts stay in ``soothe.prompts``.

Reasoners and rail evaluators import builders/constants from this package;
they own invoke + parse only.

Raw fragment templates remain available from
``soothe.autopilot.prompts.fragments`` / ``.verify`` when tests need them.
"""

from soothe.autopilot.prompts.consensus import build_consensus_prompt
from soothe.autopilot.prompts.guards import build_guard_messages
from soothe.autopilot.prompts.maturity import build_maturity_prompt
from soothe.autopilot.prompts.roles import (
    SYSTEM_BACKOFF,
    SYSTEM_DAG_HEALTH,
    SYSTEM_GOAL_PLACEMENT,
    SYSTEM_POST_COMPLETION,
)
from soothe.autopilot.prompts.verify import (
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
