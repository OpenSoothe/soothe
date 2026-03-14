"""VectorStoreProtocol -- async vector database abstraction (RFC-0002 Module 8)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class VectorRecord(BaseModel):
    """A stored vector record with metadata.

    Args:
        id: Unique record identifier.
        score: Similarity score from search (None for non-search results).
        payload: Arbitrary metadata stored alongside the vector.
    """

    id: str
    score: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Async protocol for vector database operations.

    All methods are async. Implementations must handle connection
    lifecycle internally (lazy connect, connection pooling, etc.).
    """

    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None:
        """Create or ensure a collection exists.

        Args:
            vector_size: Dimensionality of vectors in this collection.
            distance: Distance metric (``cosine``, ``l2``, ``ip``).
        """
        ...

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors with optional payloads and IDs.

        Args:
            vectors: List of embedding vectors.
            payloads: Per-vector metadata dicts. Must match length of vectors.
            ids: Per-vector IDs. Auto-generated if not provided.
        """
        ...

    async def search(
        self,
        query: str,
        vector: list[float],
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorRecord]:
        """Search for nearest neighbours.

        Args:
            query: The original text query (for hybrid search implementations).
            vector: Query embedding vector.
            limit: Maximum results to return.
            filters: Metadata filter conditions.

        Returns:
            Records ordered by descending similarity.
        """
        ...

    async def delete(self, record_id: str) -> None:
        """Delete a record by ID.

        Args:
            record_id: The record to delete.
        """
        ...

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Update a record's vector and/or payload.

        Args:
            record_id: The record to update.
            vector: New embedding vector (None to keep existing).
            payload: New metadata (None to keep existing).
        """
        ...

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a single record by ID.

        Args:
            record_id: The record to retrieve.

        Returns:
            The record, or None if not found.
        """
        ...

    async def list_records(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[VectorRecord]:
        """List records matching optional filters.

        Args:
            filters: Metadata filter conditions.
            limit: Maximum records to return. None for all.

        Returns:
            Matching records.
        """
        ...

    async def delete_collection(self) -> None:
        """Delete the entire collection and its data."""
        ...

    async def reset(self) -> None:
        """Clear all records from the collection without deleting it."""
        ...

    async def close(self) -> None:
        """Close connections and release resources.

        Should be called during shutdown to cleanly close connection pools
        and background tasks.
        """
        ...
