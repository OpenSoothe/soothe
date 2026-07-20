"""Skills discovery and invocation for Soothe agent runtime."""

from soothe_nano.skills.builtins import get_built_in_skills_paths, is_builtin_skill_directory
from soothe_nano.skills.catalog import (
    SkillInvocationEnvelope,
    build_skill_context_text,
    build_skill_invocation_envelope,
    format_slash_skill_invoke_line,
    parse_slash_skill_user_line,
    read_skill_markdown,
    resolve_skill_directory,
    try_expand_slash_skill_user_line,
    wire_entries_for_agent_config,
)

__all__ = [
    "SkillInvocationEnvelope",
    "build_skill_context_text",
    "build_skill_invocation_envelope",
    "format_slash_skill_invoke_line",
    "get_built_in_skills_paths",
    "is_builtin_skill_directory",
    "parse_slash_skill_user_line",
    "read_skill_markdown",
    "resolve_skill_directory",
    "try_expand_slash_skill_user_line",
    "wire_entries_for_agent_config",
]
