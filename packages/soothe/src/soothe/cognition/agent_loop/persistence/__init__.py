"""AgentLoop checkpoint persistence backend.

This module provides persistence infrastructure for AgentLoop checkpoints
with thread/loop isolation and dual backend support (SQLite/PostgreSQL).

RFC-409: AgentLoop Persistence Backend Architecture
"""

from soothe.cognition.agent_loop.persistence.manager import AgentLoopCheckpointPersistenceManager

__all__ = ["AgentLoopCheckpointPersistenceManager"]
