"""Custom embeddings wrapper for DashScope API using official SDK."""

from __future__ import annotations

from typing import Any

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel

# HTTP status code for successful responses
HTTP_OK = 200


class DashScopeEmbeddings(BaseModel, Embeddings):
    """DashScope embeddings wrapper using the official DashScope SDK.

    This wrapper uses the dashscope package to ensure proper API compatibility
    with DashScope's text-embedding models.

    Args:
        model: DashScope embedding model name (default: text-embedding-v4).
        api_key: DashScope API key (optional, uses environment variable if not provided).
        dimension: Output embedding dimension (default: 1536). text-embedding-v3/v4 support configurable dimensions.
    """

    model: str = "text-embedding-v4"
    api_key: str | None = None
    dimension: int = 1536
    _client: Any = None

    class Config:
        """Pydantic config for arbitrary field types."""

        arbitrary_types_allowed = True

    def __init__(self, **kwargs: Any) -> None:
        """Initialize DashScope embeddings.

        Args:
            **kwargs: Configuration parameters including model, api_key, and dimension.
        """
        super().__init__(**kwargs)

        # Import and configure dashscope
        import dashscope
        from dashscope import TextEmbedding

        # Set API key if provided
        if self.api_key:
            dashscope.api_key = self.api_key

        self._client = TextEmbedding

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents using DashScope API.

        Args:
            texts: List of document texts to embed.

        Returns:
            List of embedding vectors.
        """
        # Validate and sanitize texts
        sanitized_texts = []
        for text in texts:
            sanitized_text = text
            if not isinstance(sanitized_text, str):
                sanitized_text = str(sanitized_text) if sanitized_text is not None else " "
            if not sanitized_text or not sanitized_text.strip():
                sanitized_text = " "
            sanitized_texts.append(sanitized_text)

        # DashScope has a limit on batch size (max 10)
        batch_size = 10
        all_embeddings = []

        for i in range(0, len(sanitized_texts), batch_size):
            batch = sanitized_texts[i : i + batch_size]

            # Build parameters with dimension support
            params = {
                "model": self.model,
                "input": batch,
            }

            # Add dimension parameter if model supports it (v3/v4)
            if self.dimension and self.model.startswith("text-embedding-v"):
                params["dimension"] = self.dimension

            response = self._client.call(**params)

            if response.status_code != HTTP_OK:
                error_msg = f"DashScope embedding API failed: {response.code} - {response.message}"
                raise RuntimeError(error_msg)

            # Extract embeddings from response
            all_embeddings.extend(item["embedding"] for item in response.output["embeddings"])

        return all_embeddings

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Asynchronously embed a list of documents.

        Note: DashScope SDK doesn't have native async support, so this falls back
        to synchronous call.

        Args:
            texts: List of document texts to embed.

        Returns:
            List of embedding vectors.
        """
        # DashScope doesn't have async support, use sync version
        return self.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text.

        Args:
            text: Query text to embed.

        Returns:
            Embedding vector for the query.
        """
        if not isinstance(text, str):
            text = str(text) if text is not None else " "
        if not text or not text.strip():
            text = " "

        # Build parameters with dimension support
        params = {
            "model": self.model,
            "input": [text],
        }

        # Add dimension parameter if model supports it (v3/v4)
        if self.dimension and self.model.startswith("text-embedding-v"):
            params["dimension"] = self.dimension

        response = self._client.call(**params)

        if response.status_code != HTTP_OK:
            error_msg = f"DashScope embedding API failed: {response.code} - {response.message}"
            raise RuntimeError(error_msg)

        return response.output["embeddings"][0]["embedding"]

    async def aembed_query(self, text: str) -> list[float]:
        """Asynchronously embed a single query text.

        Note: DashScope SDK doesn't have native async support, so this falls back
        to synchronous call.

        Args:
            text: Query text to embed.

        Returns:
            Embedding vector for the query.
        """
        # DashScope doesn't have async support, use sync version
        return self.embed_query(text)
