"""Core framework logic -- usable without CLI dependencies."""

from typing import Any

__all__ = [
    "ConfigDrivenPolicy",
    "CoreAgent",
    "FrameworkFilesystem",
    "PromptBuilder",
    "ResolvedWorkspace",
    "SootheRunner",
    "create_soothe_agent",
    "resolve_daemon_workspace",
    "resolve_workspace_for_stream",
    "validate_client_workspace",
]


def __getattr__(name: str) -> Any:
    """Lazy import core modules to avoid heavy imports at startup."""
    if name == "CoreAgent":
        from soothe.core.agent import CoreAgent

        return CoreAgent
    if name == "create_soothe_agent":
        from soothe.core.agent import create_soothe_agent

        return create_soothe_agent
    if name == "SootheRunner":
        from soothe.core.runner import SootheRunner

        return SootheRunner
    if name == "ConfigDrivenPolicy":
        # Governance: operation security + configuration-driven policy
        from soothe.core.governance import ConfigDrivenPolicy

        return ConfigDrivenPolicy
    if name == "PromptBuilder":
        from soothe.core.prompts import PromptBuilder

        return PromptBuilder
    if name == "resolve_daemon_workspace":
        from soothe.core.workspace.resolution import resolve_daemon_workspace

        return resolve_daemon_workspace
    if name == "validate_client_workspace":
        from soothe.core.workspace.resolution import validate_client_workspace

        return validate_client_workspace
    if name == "ResolvedWorkspace":
        from soothe.core.workspace.stream_resolution import ResolvedWorkspace

        return ResolvedWorkspace
    if name == "resolve_workspace_for_stream":
        from soothe.core.workspace.stream_resolution import resolve_workspace_for_stream

        return resolve_workspace_for_stream
    if name == "FrameworkFilesystem":
        from soothe.core.workspace.framework_filesystem import FrameworkFilesystem

        return FrameworkFilesystem

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
