"""Host prompt construction — systemwide / shared templates only.

StrangeLoop-scoped prompts (loop planner, ledger projection, user envelopes)
live in ``soothe.sloop.prompts`` (migrated in HCD-02). This module retains
only systemwide prompts: CoreAgent system templates, context XML, project
instructions, identity, and the shared fragment loader.

CoreAgent system templates live in ``soothe_nano.prompts``.
"""

from .context_xml import (
    build_context_sections_for_complexity,
    build_soothe_environment_section,
    build_soothe_workspace_section,
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
    EXECUTE_WORKSPACE_RULES_FRAGMENT,
    RESPONSE_LANGUAGE_HINT_FALLBACK,
    build_response_language_hint,
    build_timestamp_xml_footer,
    current_timestamp_iso,
    default_agent_system_prompt_body,
    format_complex_agent_system_prompt_core,
    uses_builtin_agent_system_prompt,
)

__all__ = [
    "EXECUTE_WORKSPACE_RULES_FRAGMENT",
    "RESPONSE_LANGUAGE_HINT_FALLBACK",
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
    "build_response_language_hint",
    "build_soothe_environment_section",
    "build_soothe_workspace_section",
    "build_timestamp_xml_footer",
    "current_timestamp_iso",
    "default_agent_system_prompt_body",
    "format_complex_agent_system_prompt_core",
    "uses_builtin_agent_system_prompt",
]
