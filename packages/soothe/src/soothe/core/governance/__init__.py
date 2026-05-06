"""Governance package — operation security and configuration-driven policy.

This package provides:
- Workspace filesystem path validation and banned command matching
- Configuration-driven permission policy with named profiles

Usage:
    from soothe.core.governance import (
        WorkspaceToolOperationSecurity,
        ConfigDrivenPolicy,
        STANDARD_PROFILE,
        READONLY_PROFILE,
        PRIVILEGED_PROFILE,
    )
"""

from __future__ import annotations

from .config_policy import (
    DEFAULT_PROFILES,
    PRIVILEGED_PROFILE,
    READONLY_PROFILE,
    STANDARD_PROFILE,
    ConfigDrivenPolicy,
)
from .operation_security import WorkspaceToolOperationSecurity

__all__ = [
    "WorkspaceToolOperationSecurity",
    "ConfigDrivenPolicy",
    "STANDARD_PROFILE",
    "READONLY_PROFILE",
    "PRIVILEGED_PROFILE",
    "DEFAULT_PROFILES",
]
