"""Vector store implementations for VectorStoreProtocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.protocols.vector_store import VectorStoreProtocol


def create_vector_store(
    provider: str,
    collection: str,
    config: dict[str, Any] | None = None,
) -> VectorStoreProtocol:
    """Factory for vector store backends.

    Args:
        provider: Backend name (``pgvector``, ``weaviate``, ``sqlite_vec``).
        collection: Collection / table name.
        config: Provider-specific configuration.

    Returns:
        A VectorStoreProtocol implementation.

    Raises:
        ValueError: If the provider is unknown.
    """
    config = config or {}

    if provider == "pgvector":
        from soothe.backends.vector_store.pgvector import PGVectorStore

        return PGVectorStore(collection=collection, **config)

    if provider == "weaviate":
        from soothe.backends.vector_store.weaviate import WeaviateVectorStore

        return WeaviateVectorStore(collection=collection, **config)

    if provider == "sqlite_vec":
        from soothe.backends.vector_store.sqlite_vec import SQLiteVecStore

        return SQLiteVecStore(collection=collection, **config)

    msg = (
        f"Unknown vector store provider: {provider!r}. "
        "Supported: 'pgvector', 'weaviate', 'sqlite_vec'"
    )
    raise ValueError(msg)
