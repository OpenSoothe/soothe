"""Embedding Client for Memory Operations.

This module provides embedding generation capabilities using BaseLLMClient,
replacing the previous multi-provider EmbeddingClient with a simpler approach.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.backends.memory.memu.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Embedding client wrapper for BaseLLMClient.

    This class provides a compatibility layer for the memory system
    to use BaseLLMClient.embed and embed_batch methods.
    """

    def __init__(self, llm_client: BaseLLMClient) -> None:
        """Initialize embedding client with a BaseLLMClient.

        Args:
            llm_client: The LLM client with embed/embed_batch capabilities
        """
        self.llm_client = llm_client
        logger.info(f"EmbeddingClient initialized with LLM client: {type(llm_client).__name__}")

    def embed(self, text: str) -> list[float]:
        """Generate embedding for text using the LLM client.

        Args:
            text: Text to embed

        Returns:
            List of float values representing the embedding vector
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return []

        try:
            return self.llm_client.embed(text)
        except Exception as e:
            logger.exception(f"Failed to generate embedding: {e}")
            raise

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using the LLM client.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            return self.llm_client.embed_batch(texts)
        except Exception as e:
            logger.exception(f"Failed to generate batch embeddings: {e}")
            # Fallback to individual embedding calls
            logger.info("Falling back to individual embed calls")
            embeddings = []
            for text in texts:
                try:
                    embedding = self.embed(text)
                    embeddings.append(embedding)
                except Exception as individual_e:
                    logger.exception(f"Failed to embed text individually: {individual_e}")
                    # Add zero vector as placeholder
                    embeddings.append([0.0] * self.get_embedding_dimension())
            return embeddings

    def get_embedding_dimension(self) -> int:
        """Get the dimension of embeddings produced by this client."""
        try:
            return self.llm_client.get_embedding_dimensions()
        except Exception as e:
            logger.warning(f"Failed to get embedding dimensions from LLM client: {e}")
            return 1536  # Default fallback


def create_embedding_client(llm_client: BaseLLMClient) -> EmbeddingClient:
    """Create an embedding client using the provided LLM client.

    Args:
        llm_client: BaseLLMClient with embedding capabilities

    Returns:
        EmbeddingClient instance
    """
    return EmbeddingClient(llm_client)


def get_default_embedding_client() -> EmbeddingClient | None:
    """Get a default embedding client using environment-based LLM client.

    This function creates an LLM client from environment variables
    and wraps it with EmbeddingClient for compatibility.

    Returns:
        EmbeddingClient if LLM client can be created, None otherwise
    """
    try:
        # Import here to avoid circular imports
        from soothe.backends.memory.memu.llm_adapter import _get_llm_client_memu_compatible

        llm_client = _get_llm_client_memu_compatible()
        if llm_client is None:
            logger.warning("Failed to create LLM client from environment")
            return None

        return create_embedding_client(llm_client)

    except Exception as e:
        logger.warning(f"Failed to create default embedding client: {e}")
        return None
