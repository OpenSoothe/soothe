"""Host wrappers for shared RFC-104 prompt context XML builders."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from soothe_nano.prompts.context_xml import (
    RFC104_CONTEXT_XML_VERSION,
    build_soothe_environment_section,
    build_soothe_protocols_section,
    build_soothe_thread_section,
    build_soothe_workspace_section,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig


def build_shared_environment_workspace_prefix(
    config: SootheConfig,
    workspace: str | None,
    *,
    include_workspace_extras: bool = False,
) -> str:
    """ENVIRONMENT + WORKSPACE prefix for planners and Reason prompts."""
    model = config.resolve_model("default")
    env = build_soothe_environment_section(model=model)
    ws_path = Path(workspace).expanduser().resolve() if workspace else None
    ws = build_soothe_workspace_section(
        ws_path,
        include_layout_preview=include_workspace_extras,
        include_readme_excerpt=include_workspace_extras,
    )
    return f"{env}\n\n{ws}\n"


def build_context_sections_for_complexity(
    *,
    config: SootheConfig,
    complexity: Literal["minimal", "simple", "medium", "complex"],
    state: dict[str, Any],
    include_workspace_extras: bool = False,
) -> list[str]:
    """Ordered XML blocks for system prompt (excludes static base prompt and date line)."""
    if complexity == "minimal":
        return []
    model = config.resolve_model("default")
    sections: list[str] = [build_soothe_environment_section(model=model)]
    workspace_raw = state.get("workspace")
    workspace_path = Path(str(workspace_raw)).expanduser().resolve() if workspace_raw else None
    sections.append(
        build_soothe_workspace_section(
            workspace_path,
            include_layout_preview=include_workspace_extras,
            include_readme_excerpt=include_workspace_extras,
        )
    )
    if complexity == "complex":
        thread_context = state.get("thread_context") or {}
        if thread_context:
            sections.append(build_soothe_thread_section(thread_context))
        protocol_summary = state.get("protocol_summary") or {}
        proto = build_soothe_protocols_section(protocol_summary)
        if proto:
            sections.append(proto)
    return sections


__all__ = [
    "RFC104_CONTEXT_XML_VERSION",
    "build_context_sections_for_complexity",
    "build_shared_environment_workspace_prefix",
    "build_soothe_environment_section",
    "build_soothe_protocols_section",
    "build_soothe_thread_section",
    "build_soothe_workspace_section",
]
