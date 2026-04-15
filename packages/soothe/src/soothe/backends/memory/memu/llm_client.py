"""LLM client interface for memU memory operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseLLMClient(Protocol):
    """Protocol for LLM clients used by memU."""

    def completion(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Generate completion for messages.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            **kwargs: Additional arguments.

        Returns:
            Generated text.
        """
        ...

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> ChatCompletionResponse:
        """Generate chat completion with optional function calling.

        Args:
            messages: List of message dicts.
            tools: Optional list of tool schemas.
            tool_choice: Tool selection strategy.
            **kwargs: Additional arguments.

        Returns:
            ChatCompletionResponse with content and optional tool calls.
        """
        ...

    def embed(self, text: str) -> list[float]:
        """Generate embedding for text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        ...

    def get_embedding_dimensions(self) -> int:
        """Get embedding vector dimensions.

        Returns:
            Number of dimensions in embedding vectors.
        """
        ...


@dataclass
class FunctionCall:
    """A function call with name and arguments."""

    name: str
    arguments: str  # JSON string


@dataclass
class ToolCall:
    """A tool call from the LLM."""

    id: str
    function: FunctionCall


@dataclass
class ChatCompletionResponse:
    """Response from chat completion with function calling support."""

    success: bool
    content: str
    tool_calls: list[ToolCall]
    error: str | None = None
