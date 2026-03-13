"""In-memory VectorStore fallback when no external provider is configured."""

from __future__ import annotations

import math
from typing import Any

from soothe.protocols.vector_store import VectorRecord


class InMemoryVectorStore:
    """Simple in-memory vector store implementing VectorStoreProtocol.

    Intended as a lightweight fallback when ``vector_store_provider`` is
    ``none``.  Not suitable for production workloads.

    Args:
        collection: Collection name (for logging/identification only).
    """

    def __init__(self, collection: str = "default") -> None:
        self._collection = collection
        self._records: dict[str, tuple[list[float], dict[str, Any]]] = {}

    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None:
        """No-op for in-memory store."""

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert or overwrite vectors."""
        payloads = payloads or [{} for _ in vectors]
        ids = ids or [str(i) for i in range(len(vectors))]
        for vid, vec, pay in zip(ids, vectors, payloads):
            self._records[vid] = (vec, pay)

    async def search(
        self,
        query: str,
        vector: list[float],
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorRecord]:
        """Brute-force cosine similarity search."""
        scored: list[tuple[str, float, dict[str, Any]]] = []
        for rid, (vec, pay) in self._records.items():
            score = self._cosine_similarity(vector, vec)
            scored.append((rid, score, pay))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [VectorRecord(id=rid, score=score, payload=pay) for rid, score, pay in scored[:limit]]

    async def delete(self, record_id: str) -> None:
        """Delete a record by ID."""
        self._records.pop(record_id, None)

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Update a record's vector and/or payload."""
        if record_id not in self._records:
            return
        old_vec, old_pay = self._records[record_id]
        self._records[record_id] = (
            vector if vector is not None else old_vec,
            payload if payload is not None else old_pay,
        )

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a single record."""
        if record_id not in self._records:
            return None
        _, pay = self._records[record_id]
        return VectorRecord(id=record_id, payload=pay)

    async def list_records(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[VectorRecord]:
        """List all records."""
        results = [VectorRecord(id=rid, payload=pay) for rid, (_, pay) in self._records.items()]
        if limit:
            results = results[:limit]
        return results

    async def delete_collection(self) -> None:
        """Clear all data."""
        self._records.clear()

    async def reset(self) -> None:
        """Clear all data."""
        self._records.clear()

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
