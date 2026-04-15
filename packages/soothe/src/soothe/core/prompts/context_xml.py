"""RFC-104 dynamic context as nested XML (shared cache-aligned prefix)."""

from __future__ import annotations

import json
import os
import platform as platform_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from soothe.config import SootheConfig

RFC104_CONTEXT_XML_VERSION = "1"


def _xml_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_attr(value: object) -> str:
    return _xml_text(value).replace('"', "&quot;")


def build_soothe_environment_section(*, model: str) -> str:
    """Build nested ENVIRONMENT XML block (RFC-207: removed SOOTHE_ prefix).

    Args:
        model: Resolved default model id (e.g. from ``config.resolve_model`` for the default role).

    Returns:
        Single XML section string.
    """
    from soothe.config.models import get_knowledge_cutoff

    platform_name = platform_module.system()
    shell = os.environ.get("SHELL", "unknown")
    os_version = platform_module.platform()
    cutoff = get_knowledge_cutoff(model)
    inner = "\n".join(
        [
            f"<platform>{_xml_text(platform_name)}</platform>",
            f"<shell>{_xml_text(shell)}</shell>",
            f"<os_version>{_xml_text(os_version)}</os_version>",
            f"<model>{_xml_text(model)}</model>",
            f"<knowledge_cutoff>{_xml_text(cutoff)}</knowledge_cutoff>",
        ]
    )
    ver = RFC104_CONTEXT_XML_VERSION
    return f'<ENVIRONMENT version="{_xml_attr(ver)}">\n{inner}\n</ENVIRONMENT>'


def _safe_list_dir_names(root: Path, *, max_entries: int) -> str | None:
    try:
        names = sorted(p.name for p in root.iterdir() if not p.name.startswith("."))
    except OSError:
        return None
    if not names:
        return None
    preview = names[:max_entries]
    joined = ", ".join(preview)
    if len(names) > max_entries:
        joined += ", …"
    return joined


def _readme_excerpt(root: Path, *, max_chars: int) -> str | None:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        path = root / name
        if path.is_file():
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            excerpt = raw[:max_chars].strip()
            return excerpt or None
    return None


def build_soothe_workspace_section(
    workspace: Path | None,
    git_status: dict[str, Any] | None,
    *,
    include_layout_preview: bool = False,
    max_layout_entries: int = 40,
    include_readme_excerpt: bool = False,
    readme_max_chars: int = 500,
) -> str:
    """Build nested WORKSPACE XML block (RFC-207: removed SOOTHE_ prefix).

    Args:
        workspace: Project root; when None, the process current working directory is used.
        git_status: Optional dict from ``get_git_status`` (None if not a git repo).
        include_layout_preview: When True, add capped top-level name list.
        max_layout_entries: Cap for layout preview.
        include_readme_excerpt: When True, add short README snippet if present.
        readme_max_chars: Max characters for README excerpt.

    Returns:
        Single XML section string.
    """
    root = workspace or Path.cwd()
    cwd = str(root.resolve())
    is_git = git_status is not None
    present = "true" if is_git else "false"

    lines: list[str] = [
        f"<root>{_xml_text(cwd)}</root>",
        f'<vcs present="{present}">',
    ]
    if git_status:
        lines.append(f"  <branch>{_xml_text(git_status.get('branch', 'unknown'))}</branch>")
        lines.append(
            f"  <main_branch>{_xml_text(git_status.get('main_branch', 'main'))}</main_branch>"
        )
        status = git_status.get("status", "")
        if status:
            lines.append(f"  <status>{_xml_text(status)}</status>")
        commits = git_status.get("recent_commits", "")
        if commits:
            lines.append(f"  <recent_commits>{_xml_text(commits)}</recent_commits>")
    lines.append("</vcs>")

    if include_layout_preview and root.is_dir():
        preview = _safe_list_dir_names(root, max_entries=max_layout_entries)
        if preview:
            lines.append(
                f'<layout_preview max_entries="{max_layout_entries}">{_xml_text(preview)}</layout_preview>'
            )

    if include_readme_excerpt and root.is_dir():
        excerpt = _readme_excerpt(root, max_chars=readme_max_chars)
        if excerpt:
            lines.append(f"<readme_excerpt>{_xml_text(excerpt)}</readme_excerpt>")

    inner = "\n".join(lines)
    ver = RFC104_CONTEXT_XML_VERSION
    return f'<WORKSPACE version="{_xml_attr(ver)}">\n{inner}\n</WORKSPACE>'


def build_soothe_thread_section(thread_context: dict[str, Any]) -> str:
    """Build SOOTHE_THREAD XML block from runner thread dict."""
    thread_id = thread_context.get("thread_id", "unknown")
    goals = thread_context.get("active_goals", [])
    turns = thread_context.get("conversation_turns", 0)
    plan = thread_context.get("current_plan")

    parts: list[str] = [
        f"<thread_id>{_xml_text(thread_id)}</thread_id>",
        f"<conversation_turns>{int(turns)}</conversation_turns>",
    ]
    if goals:
        goals_preview = goals[:5]
        parts.append(f"<active_goals>{_xml_text(json.dumps(goals_preview))}</active_goals>")
    if plan:
        parts.append(f"<current_plan>{_xml_text(preview_first(str(plan), 100))}</current_plan>")
    inner = "\n".join(parts)
    ver = RFC104_CONTEXT_XML_VERSION
    return f'<SOOTHE_THREAD version="{_xml_attr(ver)}">\n{inner}\n</SOOTHE_THREAD>'


def build_soothe_protocols_section(protocol_summary: dict[str, Any]) -> str:
    """Build SOOTHE_PROTOCOLS XML block, or empty string when nothing is active."""
    entries: list[str] = []
    proto_names = ["memory", "planner", "policy"]
    for proto_name in proto_names:
        proto_info = protocol_summary.get(proto_name)
        if not proto_info:
            continue
        proto_type = proto_info.get("type", "unknown")
        stats = proto_info.get("stats", "")
        stat_attr = f' stats="{_xml_attr(stats)}"' if stats else ""
        entries.append(
            f'<protocol id="{_xml_attr(proto_name)}" type="{_xml_attr(proto_type)}"{stat_attr}/>'
        )
    if not entries:
        return ""
    inner = "\n".join(entries)
    ver = RFC104_CONTEXT_XML_VERSION
    return f'<SOOTHE_PROTOCOLS version="{_xml_attr(ver)}">\n{inner}\n</SOOTHE_PROTOCOLS>'


def build_shared_environment_workspace_prefix(
    config: SootheConfig,
    workspace: str | None,
    git_status: dict[str, Any] | None,
    *,
    include_workspace_extras: bool = False,
) -> str:
    """ENVIRONMENT + WORKSPACE prefix for planners and Reason prompts."""
    model = config.resolve_model("default")
    env = build_soothe_environment_section(model=model)
    ws_path = Path(workspace).expanduser().resolve() if workspace else None
    ws = build_soothe_workspace_section(
        ws_path,
        git_status,
        include_layout_preview=include_workspace_extras,
        include_readme_excerpt=include_workspace_extras,
    )
    return f"{env}\n\n{ws}\n"


def build_context_sections_for_complexity(
    *,
    config: SootheConfig,
    complexity: Literal["chitchat", "medium", "complex"],
    state: dict[str, Any],
    include_workspace_extras: bool = False,
) -> list[str]:
    """Ordered XML blocks for system prompt (excludes static base prompt and date line)."""
    if complexity == "chitchat":
        return []
    model = config.resolve_model("default")
    sections: list[str] = [build_soothe_environment_section(model=model)]
    workspace_raw = state.get("workspace")
    workspace_path = Path(str(workspace_raw)).expanduser().resolve() if workspace_raw else None
    sections.append(
        build_soothe_workspace_section(
            workspace_path,
            state.get("git_status"),
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
