"""StrangeLoop prompt construction (envelopes, ledger projection, synthesis).

StrangeLoop-scoped prompts live here; systemwide / shared prompts (identity,
system templates, context XML, project instructions, loader) stay in
``soothe.prompts``.
"""

from .decompose import (
    APPROVED_PLAN_EXECUTE_HINT,
    DECOMPOSE_TASK_TOOL_DESCRIPTION,
    THREAD_POLICY_SYSTEM_ADDENDUM,
    WRITE_TODOS_SYSTEM_ADDENDUM,
    WRITE_TODOS_TOOL_DESCRIPTION,
    do_or_decompose_instruction_lines,
    user_finish_or_split_hint_lines,
)
from .graph_wrapper import (
    GraphCallKind,
    GraphPromptWrapper,
    ProjectionResult,
    _format_dag_context,
    _prior_goals_from_checkpoint,
)
from .plan_ledger_projection import (
    current_goal_has_execute_ledger,
    project_loop_messages_for_core_agent,
    project_loop_messages_for_plan,
    project_loop_messages_for_synthesis,
    projected_ledger_has_goal_completion,
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
    "APPROVED_PLAN_EXECUTE_HINT",
    "DECOMPOSE_TASK_TOOL_DESCRIPTION",
    "EXECUTION_TASK_LABEL",
    "GraphCallKind",
    "GraphPromptWrapper",
    "PRIOR_PROGRESS_MAX_CHARS",
    "PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS",
    "ProjectionResult",
    "THREAD_POLICY_SYSTEM_ADDENDUM",
    "UserMessageBuilder",
    "WRITE_TODOS_SYSTEM_ADDENDUM",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "_format_dag_context",
    "_prior_goals_from_checkpoint",
    "current_goal_has_execute_ledger",
    "do_or_decompose_instruction_lines",
    "flatten_user_message_content",
    "project_loop_messages_for_core_agent",
    "project_loop_messages_for_plan",
    "project_loop_messages_for_synthesis",
    "projected_ledger_has_goal_completion",
    "render_prior_steps_tree",
    "user_finish_or_split_hint_lines",
]
