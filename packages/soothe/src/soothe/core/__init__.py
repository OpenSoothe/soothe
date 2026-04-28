"""Core framework logic -- usable without CLI dependencies."""

from typing import Any

__all__ = [
    "INVALID_WORKSPACE_DIRS",
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
        # NEW: Import from persistence package
        from soothe.core.persistence import ConfigDrivenPolicy

        return ConfigDrivenPolicy
    if name == "PromptBuilder":
        from soothe.core.prompts import PromptBuilder

        return PromptBuilder
    if name == "INVALID_WORKSPACE_DIRS":
        from soothe_sdk.utils import INVALID_WORKSPACE_DIRS

        return INVALID_WORKSPACE_DIRS
    if name == "resolve_daemon_workspace":
        # NEW: Import from workspace package
        from soothe.core.workspace import resolve_daemon_workspace

        return resolve_daemon_workspace
    if name == "validate_client_workspace":
        # NEW: Import from workspace package
        from soothe.core.workspace import validate_client_workspace

        return validate_client_workspace
    if name == "ResolvedWorkspace":
        # NEW: Import from workspace package
        from soothe.core.workspace import ResolvedWorkspace

        return ResolvedWorkspace
    if name == "resolve_workspace_for_stream":
        # NEW: Import from workspace package
        from soothe.core.workspace import resolve_workspace_for_stream

        return resolve_workspace_for_stream
    if name == "FrameworkFilesystem":
        # NEW: Import from workspace package
        from soothe.core.workspace import FrameworkFilesystem

        return FrameworkFilesystem

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
