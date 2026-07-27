"""Host facade re-exporting shared RFC-104 prompt context XML builders.

Canonical implementations live in :mod:`soothe_nano.prompts.context_xml`.
This module preserves the host import surface (``soothe.prompts.context_xml``)
so host consumers do not reach into nano directly.
"""

from __future__ import annotations

from soothe_nano.prompts.context_xml import (
    build_context_sections_for_complexity,
    build_soothe_environment_section,
    build_soothe_protocols_section,
    build_soothe_thread_section,
    build_soothe_workspace_section,
)

__all__ = [
    "build_context_sections_for_complexity",
    "build_soothe_environment_section",
    "build_soothe_protocols_section",
    "build_soothe_thread_section",
    "build_soothe_workspace_section",
]
