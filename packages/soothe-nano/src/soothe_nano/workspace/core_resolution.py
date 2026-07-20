"""Unified workspace resolution core with pluggable precedence (RFC-621).

Provides a single ``resolve_workspace()`` function that each resolution chain
calls with the appropriate precedence level.  Existing public functions
(``resolve_loop_workspace``, ``resolve_workspace_for_stream``,
``resolve_workspace_for_tool_execution``) become thin wrappers.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from soothe_nano.workspace.stream_resolution import ResolvedWorkspace


class WorkspacePrecedence(Enum):
    """Which precedence chain to use for workspace resolution."""

    LOOP = "loop"
    STREAM = "stream"
    TOOL_EXECUTION = "tool"


def resolve_workspace(
    precedence: WorkspacePrecedence,
    **sources: Any,
) -> ResolvedWorkspace:
    """Resolve workspace using the specified precedence chain.

    Args:
        precedence: Which precedence chain to apply.
        **sources: Keyword arguments matching the source fields for that chain.

    Returns:
        ``ResolvedWorkspace`` with absolute ``path`` and ``source`` label.
    """
    if precedence == WorkspacePrecedence.LOOP:
        return _resolve_loop(**sources)
    if precedence == WorkspacePrecedence.STREAM:
        return _resolve_stream(**sources)
    if precedence == WorkspacePrecedence.TOOL_EXECUTION:
        return _resolve_tool_execution(**sources)

    msg = f"Unknown precedence: {precedence}"
    raise ValueError(msg)


def _resolve_loop(
    *,
    loop_id: str,
    client_workspace: str | Path | None = None,
    user_id: str | None = None,
    client_workspace_id: str | None = None,
    soothe_home: Path | None = None,
    create: bool = True,
    workspace_mapping: dict[str, Any] | None = None,
) -> ResolvedWorkspace:
    """LOOP precedence: client_workspace > persisted > daemon fallback."""
    from soothe_nano.workspace.loop_workspace import (
        resolve_client_workspace_on_host,
        resolve_loop_workspace,
    )
    from soothe_nano.workspace.resolution import resolve_daemon_workspace

    client_ws = str(client_workspace).strip() if client_workspace else None
    try:
        path = resolve_loop_workspace(
            loop_id=loop_id,
            client_workspace=client_ws,
            user_id=user_id,
            client_workspace_id=client_workspace_id,
            soothe_home=soothe_home,
            create=create,
            workspace_mapping=workspace_mapping,
        )
    except ValueError:
        path = resolve_daemon_workspace()
        return ResolvedWorkspace(path=str(path), source="daemon_fallback")

    if client_ws:
        if (
            resolve_client_workspace_on_host(client_ws, workspace_mapping=workspace_mapping)
            is not None
        ):
            return ResolvedWorkspace(path=str(path), source="client_workspace")
        return ResolvedWorkspace(path=str(path), source="persisted")

    return ResolvedWorkspace(path=str(path), source="persisted")


def _resolve_stream(
    *,
    explicit: str | Path | None = None,
    thread_workspace: str | Path | None = None,
    installation_default: str | Path | None = None,
) -> ResolvedWorkspace:
    """STREAM precedence: explicit > thread > daemon_default > cwd."""
    from soothe_nano.workspace.stream_resolution import resolve_workspace_for_stream

    return resolve_workspace_for_stream(
        explicit=explicit,
        thread_workspace=thread_workspace,
        installation_default=installation_default,
    )


def _resolve_tool_execution(
    *,
    runtime: Any | None = None,
    config: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    fallback: str | Path | None = None,
    use_langgraph_config: bool = True,
) -> ResolvedWorkspace:
    """TOOL_EXECUTION precedence: config > state > messages > ContextVar > fallback."""
    from soothe_nano.workspace.runtime_resolution import resolve_workspace_for_tool_execution

    path = resolve_workspace_for_tool_execution(
        runtime=runtime,
        config=config,
        state=state,
        fallback=fallback,
        use_langgraph_config=use_langgraph_config,
    )
    if path is not None:
        return ResolvedWorkspace(path=str(path), source="tool_execution")

    # No workspace found — return cwd as last resort
    return ResolvedWorkspace(path=str(Path.cwd().resolve()), source="cwd")
