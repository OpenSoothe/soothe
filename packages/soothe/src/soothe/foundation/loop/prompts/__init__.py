"""Soothe prompt construction module."""

from .builder import PromptBuilder
from .context_xml import (
    build_context_sections_for_complexity,
    build_soothe_environment_section,
    build_soothe_workspace_section,
)
from .plan_ledger_projection import (
    project_loop_messages_for_core_agent,
    project_loop_messages_for_plan,
)
from .system_templates import (
    _DATA_GUIDE,
    _DEFAULT_SYSTEM_PROMPT,
    _FILE_OPS_GUIDE,
    _MEDIUM_SYSTEM_PROMPT,
    _RESEARCH_GUIDE,
    _SHELL_GUIDE,
    _SIMPLE_SYSTEM_PROMPT,
    _SUBAGENT_GUIDE,
    _TOOL_ORCHESTRATION_GUIDE,
    RESPONSE_LANGUAGE_HINT_FRAGMENT,
)
from .user_envelope import (
    build_execute_step_envelope,
    build_plan_context_envelope,
)
from .user_message import (
    UserMessageBuilder,
    flatten_user_message_content,
)

__all__ = [
    "PromptBuilder",
    "RESPONSE_LANGUAGE_HINT_FRAGMENT",
    "UserMessageBuilder",
    "_DATA_GUIDE",
    "_DEFAULT_SYSTEM_PROMPT",
    "_FILE_OPS_GUIDE",
    "_MEDIUM_SYSTEM_PROMPT",
    "_RESEARCH_GUIDE",
    "_SHELL_GUIDE",
    "_SIMPLE_SYSTEM_PROMPT",
    "_SUBAGENT_GUIDE",
    "_TOOL_ORCHESTRATION_GUIDE",
    "build_context_sections_for_complexity",
    "build_execute_step_envelope",
    "build_plan_context_envelope",
    "build_soothe_environment_section",
    "build_soothe_workspace_section",
    "flatten_user_message_content",
    "project_loop_messages_for_core_agent",
    "project_loop_messages_for_plan",
]
