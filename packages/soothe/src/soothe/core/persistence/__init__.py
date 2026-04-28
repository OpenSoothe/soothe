"""Persistence and policy package - artifact storage and configuration-driven policy.

This package provides:
- Run artifact management for checkpoints, reports, manifests
- Configuration-driven policy with permission profiles
- Policy profiles for standard, readonly, and privileged access

Architecture:
- artifact_store.py: Run artifact directory management
- config_policy.py: ConfigDrivenPolicy implementation

Usage:
    from soothe.core.persistence import (
        RunArtifactStore,
        RunManifest,
        ArtifactEntry,
        ConfigDrivenPolicy,
        STANDARD_PROFILE,
        READONLY_PROFILE,
        PRIVILEGED_PROFILE,
    )
"""

from __future__ import annotations

# Artifact store
from .artifact_store import (
    ArtifactEntry,
    RunArtifactStore,
    RunManifest,
)

# Config-driven policy
from .config_policy import (
    DEFAULT_PROFILES,
    PRIVILEGED_PROFILE,
    READONLY_PROFILE,
    STANDARD_PROFILE,
    ConfigDrivenPolicy,
    _extract_required_permission,  # Internal helper exported for tests
)

__all__ = [
    # Artifact store
    "ArtifactEntry",
    "RunManifest",
    "RunArtifactStore",
    # Policy
    "ConfigDrivenPolicy",
    "STANDARD_PROFILE",
    "READONLY_PROFILE",
    "PRIVILEGED_PROFILE",
    "DEFAULT_PROFILES",
    # Internal helpers (exported for tests)
    "_extract_required_permission",
]
