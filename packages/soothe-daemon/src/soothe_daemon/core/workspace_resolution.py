"""Unified workspace path resolution for agent streams (RFC-103, IG-116).

Single precedence chain for ``runner.astream(workspace=...)``, daemon thread
registry, and config so Layer 1/2 and tools always see a concrete directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from soothe_daemon.utils.path import expand_path

ResolvedWorkspaceSource = Literal["explicit", "thread", "daemon_default", "config", "cwd"]


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    """Absolute workspace path and which precedence level supplied it."""

    path: str
    source: ResolvedWorkspaceSource


def _normalize_candidate(raw: str | Path | None) -> Path | None:
    """Return resolved absolute path, or None if missing or blank."""
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
    config_workspace_dir: str | Path | None = None,
) -> ResolvedWorkspace:
    """Pick the workspace directory for a single agent stream.

    Precedence:
        1. ``explicit`` — caller ``astream(..., workspace=...)``
        2. ``thread_workspace`` — per-thread path (daemon registry)
        3. ``installation_default`` — daemon resolved default (e.g. ``_daemon_workspace``)
        4. ``config_workspace_dir`` — ``SootheConfig.workspace_dir`` expanded
        5. Current working directory

    Args:
        explicit: Optional override from the streaming API.
        thread_workspace: Optional path bound to the durability thread.
        installation_default: Daemon-level default when no per-thread path.
        config_workspace_dir: Config ``workspace_dir`` (file path string).

    Returns:
        ResolvedWorkspace with absolute ``path`` and ``source`` label.
    """
    if (p := _normalize_candidate(explicit)) is not None:
        return ResolvedWorkspace(path=str(p), source="explicit")
    if (p := _normalize_candidate(thread_workspace)) is not None:
        return ResolvedWorkspace(path=str(p), source="thread")
    if (p := _normalize_candidate(installation_default)) is not None:
        return ResolvedWorkspace(path=str(p), source="daemon_default")
    if config_workspace_dir and str(config_workspace_dir).strip():
        p = expand_path(config_workspace_dir).resolve()
        return ResolvedWorkspace(path=str(p), source="config")
    return ResolvedWorkspace(path=str(Path.cwd().resolve()), source="cwd")
