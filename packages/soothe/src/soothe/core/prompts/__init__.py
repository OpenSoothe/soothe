"""Soothe prompt construction module."""

from .builder import PromptBuilder
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
)

__all__ = [
    "PromptBuilder",
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
    "build_soothe_environment_section",
    "build_soothe_workspace_section",
]
