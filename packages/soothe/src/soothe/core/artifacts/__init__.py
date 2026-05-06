"""Artifacts package — run artifact storage and management.

This package provides:
- Run artifact management for checkpoints, reports, manifests
- Structured run output directory at $SOOTHE_HOME/data/threads/{thread_id}/

Usage:
    from soothe.core.artifacts import (
        RunArtifactStore,
        RunManifest,
        ArtifactEntry,
    )
"""

from __future__ import annotations

from .artifact_store import (
    ArtifactEntry,
    RunArtifactStore,
    RunManifest,
)

__all__ = [
    "ArtifactEntry",
    "RunManifest",
    "RunArtifactStore",
]
