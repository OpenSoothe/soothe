"""Public workspace resolution API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from soothe_nano.workspace.workspace_policy import resolve_workspace_for_tool_execution

ResolvedWorkspaceSource = Literal["explicit", "thread", "daemon_default", "cwd", "tool_execution"]


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    """Absolute workspace path and which precedence level supplied it."""

    path: str
    source: ResolvedWorkspaceSource


class WorkspacePrecedence(Enum):
    """Which precedence chain to use for workspace resolution."""

    STREAM = "stream"
    TOOL_EXECUTION = "tool"


def _normalize_candidate(raw: str | Path | None) -> Path | None:
    if raw is None:
        return None
    if isinstance(raw, Path):
        text = str(raw).strip()
        if not text:
            return None
        return raw.expanduser().resolve()
    text = str(raw).strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def resolve_workspace_for_stream(
    *,
    explicit: str | Path | None = None,
    thread_workspace: str | Path | None = None,
    installation_default: str | Path | None = None,
) -> ResolvedWorkspace:
    """Pick workspace for one agent stream."""
    if (p := _normalize_candidate(explicit)) is not None:
        return ResolvedWorkspace(path=str(p), source="explicit")
    if (p := _normalize_candidate(thread_workspace)) is not None:
        return ResolvedWorkspace(path=str(p), source="thread")
    if (p := _normalize_candidate(installation_default)) is not None:
        return ResolvedWorkspace(path=str(p), source="daemon_default")
    return ResolvedWorkspace(path=str(Path.cwd().resolve()), source="cwd")


def resolve_workspace(precedence: WorkspacePrecedence, **sources: Any) -> ResolvedWorkspace:
    """Resolve workspace using the requested precedence chain."""
    if precedence == WorkspacePrecedence.STREAM:
        return resolve_workspace_for_stream(
            explicit=sources.get("explicit"),
            thread_workspace=sources.get("thread_workspace"),
            installation_default=sources.get("installation_default"),
        )
    if precedence == WorkspacePrecedence.TOOL_EXECUTION:
        path = resolve_workspace_for_tool_execution(
            runtime=sources.get("runtime"),
            config=sources.get("config"),
            state=sources.get("state"),
            fallback=sources.get("fallback"),
            use_langgraph_config=sources.get("use_langgraph_config", True),
        )
        if path is not None:
            return ResolvedWorkspace(path=str(path), source="tool_execution")
        return ResolvedWorkspace(path=str(Path.cwd().resolve()), source="cwd")
    msg = f"Unknown precedence: {precedence}"
    raise ValueError(msg)
