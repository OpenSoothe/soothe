"""StrangeLoop checkpoint persistence backend.

This module provides persistence infrastructure for StrangeLoop checkpoints
with thread/loop isolation and dual backend support (SQLite/PostgreSQL).

RFC-215: StrangeLoop Persistence Backend Architecture
"""

from soothe.foundation.loop.state.persistence.manager import (
    StrangeLoopCheckpointPersistenceManager,
)

__all__ = ["StrangeLoopCheckpointPersistenceManager"]
