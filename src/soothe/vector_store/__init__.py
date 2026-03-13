"""Vector store implementations for VectorStoreProtocol."""

from __future__ import annotations

from typing import Any

from soothe.protocols.vector_store import VectorStoreProtocol


def create_vector_store(
    provider: str,
    collection: str,
    config: dict[str, Any] | None = None,
) -> VectorStoreProtocol:
    """Factory for vector store backends.

    Args:
        provider: Backend name (``pgvector``, ``weaviate``, ``in_memory``, or ``none``).
        collection: Collection / table name.
        config: Provider-specific configuration.

    Returns:
        A VectorStoreProtocol implementation.

    Raises:
        ValueError: If the provider is unknown.
    """
    config = config or {}

    if provider in ("in_memory", "none"):
        from soothe.vector_store.in_memory import InMemoryVectorStore

        return InMemoryVectorStore(collection=collection)

    if provider == "pgvector":
        from soothe.vector_store.pgvector import PGVectorStore

        return PGVectorStore(collection=collection, **config)

    if provider == "weaviate":
        from soothe.vector_store.weaviate import WeaviateVectorStore

        return WeaviateVectorStore(collection=collection, **config)

    msg = f"Unknown vector store provider: {provider!r}. Use 'pgvector', 'weaviate', 'in_memory', or 'none'."
    raise ValueError(msg)
