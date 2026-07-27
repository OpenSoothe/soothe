"""StrangeLoop prompt construction (loop planner, envelopes, ledger projection).

Migrated from ``soothe.prompts`` (HCD-02): StrangeLoop-scoped prompts live here;
systemwide / shared prompts (identity, system templates, context XML, project
instructions, loader) stay in ``soothe.prompts``.
"""

from .builder import PromptBuilder
from .plan_ledger_projection import (
    project_continuation_assess_ledger,
    project_loop_messages_for_core_agent,
    project_loop_messages_for_plan,
    project_loop_messages_for_synthesis,
    project_planner_ledger,
    project_planner_ledger_for_assess,
)
from .planner_assembly import (
    PlannerCallKind,
    PlannerProjectionMode,
    goal_preview_text,
    projected_ledger_has_goal_completion,
    resolve_planner_projection_mode,
)
from .user_message import (
    EXECUTION_TASK_LABEL,
    PRIOR_PROGRESS_MAX_CHARS,
    PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS,
    UserMessageBuilder,
    flatten_user_message_content,
    render_prior_steps_tree,
)

__all__ = [
    "EXECUTION_TASK_LABEL",
    "PRIOR_PROGRESS_MAX_CHARS",
    "PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS",
    "PlannerCallKind",
    "PlannerProjectionMode",
    "PromptBuilder",
    "UserMessageBuilder",
    "flatten_user_message_content",
    "goal_preview_text",
    "project_continuation_assess_ledger",
    "project_loop_messages_for_core_agent",
    "project_loop_messages_for_plan",
    "project_loop_messages_for_synthesis",
    "project_planner_ledger",
    "project_planner_ledger_for_assess",
    "projected_ledger_has_goal_completion",
    "render_prior_steps_tree",
    "resolve_planner_projection_mode",
]
