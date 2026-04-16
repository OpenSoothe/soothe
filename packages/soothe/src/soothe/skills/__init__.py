"""Skills discovery and invocation for Soothe daemon."""

from soothe.skills.builtins import get_built_in_skills_paths
from soothe.skills.catalog import (
    SkillInvocationEnvelope,
    build_skill_invocation_envelope,
    read_skill_markdown,
    resolve_skill_directory,
    wire_entries_for_agent_config,
)

__all__ = [
    "SkillInvocationEnvelope",
    "build_skill_invocation_envelope",
    "get_built_in_skills_paths",
    "read_skill_markdown",
    "resolve_skill_directory",
    "wire_entries_for_agent_config",
]
