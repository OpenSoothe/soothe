"""ContextProtocol -- cognitive context accumulation and projection (RFC-0002 Module 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ContextEntry(BaseModel):
    """A unit of knowledge in the context ledger.

    Args:
        source: Origin identifier (e.g., "tool:web_search", "subagent:research", "user").
        content: The knowledge content.
        timestamp: When this entry was created.
        tags: Categorical tags for filtering.
        importance: Relevance weight from 0.0 to 1.0.
    """

    source: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tags: list[str] = Field(default_factory=list)
    importance: float = 0.5


class ContextProjection(BaseModel):
    """A bounded, purpose-scoped view of the context ledger.

    Args:
        entries: Selected relevant entries within the token budget.
        summary: Optional summary of omitted entries.
        total_entries: Total entries in the full ledger (for awareness).
        token_count: Estimated tokens in this projection.
    """

    entries: list[ContextEntry]
    summary: str | None = None
    total_entries: int
    token_count: int


@runtime_checkable
class ContextProtocol(Protocol):
    """Protocol for cognitive context accumulation and projection.

    The context ledger is unbounded and append-only. Projections are
    bounded views assembled for a specific purpose (orchestrator reasoning
    or subagent briefing).
    """

    async def ingest(self, entry: ContextEntry) -> None:
        """Add a knowledge entry to the context ledger."""
        ...

    async def project(self, query: str, token_budget: int) -> ContextProjection:
        """Project a relevant subset of the ledger within a token budget.

        Args:
            query: The relevance query (typically the current goal).
            token_budget: Maximum tokens for the projection.

        Returns:
            A bounded projection of relevant context.
        """
        ...

    async def project_for_subagent(self, goal: str, token_budget: int) -> ContextProjection:
        """Project a focused briefing for a subagent's specific goal.

        Produces summarized background + detailed entries most relevant
        to the subagent's goal.

        Args:
            goal: The subagent's task description.
            token_budget: Maximum tokens for the briefing.

        Returns:
            A focused projection for the subagent.
        """
        ...

    async def summarize(self, scope: str | None = None) -> str:
        """Produce a condensed summary of the ledger or a scope within it.

        Args:
            scope: Optional filter (e.g., a tag or source prefix).

        Returns:
            A text summary.
        """
        ...

    async def persist(self, thread_id: str) -> None:
        """Persist the ledger for later restoration.

        Args:
            thread_id: The thread to persist under.
        """
        ...

    async def restore(self, thread_id: str) -> bool:
        """Restore a previously persisted ledger.

        Args:
            thread_id: The thread to restore from.

        Returns:
            True if a persisted ledger was found and restored.
        """
        ...
