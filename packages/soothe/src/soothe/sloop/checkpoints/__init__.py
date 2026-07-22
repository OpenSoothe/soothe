"""StrangeLoop checkpoint persistence backend.

This module provides persistence infrastructure for StrangeLoop checkpoints
with thread/loop isolation and dual backend support (SQLite/PostgreSQL).

RFC-215: StrangeLoop Persistence Backend Architecture
IG-500: ArchiveBackend for loop archival and knowledge transfer.
"""

from soothe.sloop.checkpoints.archive_backend import (
    ArchiveBackend,
    ArchivedGoalMatch,
    ArchiveMetadata,
    GoalSummary,
)
from soothe.sloop.checkpoints.manager import (
    StrangeLoopCheckpointPersistenceManager,
)

__all__ = [
    "ArchiveBackend",
    "ArchiveMetadata",
    "ArchivedGoalMatch",
    "GoalSummary",
    "StrangeLoopCheckpointPersistenceManager",
]
