"""Custom embeddings wrapper for DashScope OpenAI-compatible API."""

from __future__ import annotations

from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel

# HTTP status code for successful responses
HTTP_OK = 200


class DashScopeOpenAIEmbeddings(BaseModel, Embeddings):
    """DashScope embeddings wrapper for OpenAI-compatible endpoint.

    This wrapper is designed specifically for DashScope's OpenAI-compatible
    API endpoint (https://dashscope.aliyuncs.com/compatible-mode/v1).

    Args:
        model: DashScope embedding model name (default: text-embedding-v4).
        api_key: DashScope API key (optional, uses environment variable if not provided).
        base_url: DashScope OpenAI-compatible base URL.
        dimension: Output embedding dimension (default: 1536). text-embedding-v3/v4 support configurable dimensions.
    """

    model: str = "text-embedding-v4"
    api_key: str | None = None
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dimension: int = 1536

    class Config:
        """Pydantic config for arbitrary field types."""

        arbitrary_types_allowed = True

    def __init__(self, **kwargs: Any) -> None:
        """Initialize DashScope OpenAI-compatible embeddings.

        Args:
            **kwargs: Configuration parameters including model, api_key, base_url, and dimension.
        """
        super().__init__(**kwargs)

        # Ensure we have an API key
        if not self.api_key:
            import os

            self.api_key = os.getenv("DASHSCOPE_API_KEY")

        if not self.api_key:
            raise ValueError(
                "DashScope API key is required. Set DASHSCOPE_API_KEY environment variable or pass api_key parameter."
            )

    def _make_request(self, texts: list[str]) -> list[list[float]]:
        """Make embedding request to DashScope OpenAI-compatible API.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            RuntimeError: If the API request fails.
        """
        # Prepare request payload
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
        }

        # Add dimension parameter if supported
        if self.dimension and self.model.startswith("text-embedding-v"):
            payload["dimensions"] = self.dimension

        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Make request
        url = f"{self.base_url}/embeddings"

        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, json=payload, headers=headers)

        if response.status_code != HTTP_OK:
            error_msg = (
                f"DashScope embedding API failed (status {response.status_code}): {response.text}"
            )
            raise RuntimeError(error_msg)

        # Parse response
        result = response.json()

        # Extract embeddings in order
        return [item["embedding"] for item in result["data"]]

    async def _amake_request(self, texts: list[str]) -> list[list[float]]:
        """Async version of _make_request.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        # Prepare request payload
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
        }

        # Add dimension parameter if supported
        if self.dimension and self.model.startswith("text-embedding-v"):
            payload["dimensions"] = self.dimension

        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Make request
        url = f"{self.base_url}/embeddings"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code != HTTP_OK:
            error_msg = (
                f"DashScope embedding API failed (status {response.status_code}): {response.text}"
            )
            raise RuntimeError(error_msg)

        # Parse response
        result = response.json()

        # Extract embeddings in order
        return [item["embedding"] for item in result["data"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents using DashScope OpenAI-compatible API.

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

        # Process in batches (DashScope recommends max 10 per batch)
        batch_size = 10
        all_embeddings = []

        for i in range(0, len(sanitized_texts), batch_size):
            batch = sanitized_texts[i : i + batch_size]
            embeddings = self._make_request(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Asynchronously embed a list of documents.

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

        # Process in batches (DashScope recommends max 10 per batch)
        batch_size = 10
        all_embeddings = []

        for i in range(0, len(sanitized_texts), batch_size):
            batch = sanitized_texts[i : i + batch_size]
            embeddings = await self._amake_request(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

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

        embeddings = self._make_request([text])
        return embeddings[0]

    async def aembed_query(self, text: str) -> list[float]:
        """Asynchronously embed a single query text.

        Args:
            text: Query text to embed.

        Returns:
            Embedding vector for the query.
        """
        if not isinstance(text, str):
            text = str(text) if text is not None else " "
        if not text or not text.strip():
            text = " "

        embeddings = await self._amake_request([text])
        return embeddings[0]
