"""Soothe prompt construction module."""

from .builder import PromptBuilder
from .context_xml import (
    RFC104_CONTEXT_XML_VERSION,
    build_context_sections_for_complexity,
    build_shared_environment_workspace_prefix,
    build_soothe_environment_section,
    build_soothe_protocols_section,
    build_soothe_thread_section,
    build_soothe_workspace_section,
)

__all__ = [
    "RFC104_CONTEXT_XML_VERSION",
    "PromptBuilder",
    "build_context_sections_for_complexity",
    "build_shared_environment_workspace_prefix",
    "build_soothe_environment_section",
    "build_soothe_protocols_section",
    "build_soothe_thread_section",
    "build_soothe_workspace_section",
]
