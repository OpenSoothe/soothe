"""CoreAgent prompt construction helpers."""

from soothe_nano.prompts.context_xml import (
    build_context_sections_for_complexity,
    build_soothe_environment_section,
    build_soothe_workspace_section,
)
from soothe_nano.prompts.system_templates import (
    _DEFAULT_SYSTEM_PROMPT,
    _MEDIUM_SYSTEM_PROMPT,
    _SIMPLE_SYSTEM_PROMPT,
    _TOOL_ORCHESTRATION_GUIDE,
    RESPONSE_LANGUAGE_HINT_FALLBACK,
    build_response_language_hint,
    default_agent_system_prompt_body,
)

__all__ = [
    "RESPONSE_LANGUAGE_HINT_FALLBACK",
    "_DEFAULT_SYSTEM_PROMPT",
    "_MEDIUM_SYSTEM_PROMPT",
    "_SIMPLE_SYSTEM_PROMPT",
    "_TOOL_ORCHESTRATION_GUIDE",
    "build_response_language_hint",
    "build_context_sections_for_complexity",
    "build_soothe_environment_section",
    "build_soothe_workspace_section",
    "default_agent_system_prompt_body",
]
