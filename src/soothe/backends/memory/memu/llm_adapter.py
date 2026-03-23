"""MemU LLM adapter compatibility layer."""

from __future__ import annotations

import logging
from typing import Any

from .llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

################################################################################
# MemU agent compatibility
################################################################################


class MemoryLLMAdapter:
    """Adapter to make noesium LLM clients compatible with memory agent system."""

    def __init__(self, llm_client: BaseLLMClient) -> None:
        """Initialize with the original LLM client."""
        self.llm_client = llm_client

    def simple_chat(self, message: str) -> str:
        """Simple chat method that wraps the completion method.

        Args:
            message: The message to send to the LLM.

        Returns:
            str: The LLM response.
        """
        try:
            # Convert single message to messages format
            messages = [{"role": "user", "content": message}]

            # Call the completion method
            response = self.llm_client.completion(messages)

            # Return the response as string
            return str(response)

        except Exception:
            logger.exception("Error in simple_chat")
            raise

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        tools: Any = None,  # noqa: ARG002
        tool_choice: Any = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> Any:
        """Chat completion method for automated memory processing.

        Args:
            messages: List of message dictionaries.
            tools: Optional tools for function calling (unused).
            tool_choice: Tool choice strategy (unused).
            **kwargs: Additional arguments.

        Returns:
            Mock response object for memory agent compatibility.
        """
        try:
            # For now, call the regular completion method
            # In a full implementation, this would handle tool calls properly
            response_text = self.llm_client.completion(messages, **kwargs)

            # Create a mock response object that the memory agent expects
            class MockResponse:
                def __init__(self, content: str, success: bool = True) -> None:
                    self.success = success
                    self.content = content
                    self.tool_calls = []  # No function calling in this simplified version
                    self.error = None if success else "Mock error"

            return MockResponse(str(response_text))

        except Exception:
            logger.exception("Error in chat_completion")

            class MockResponse:
                def __init__(self, error_msg: str) -> None:
                    self.success = False
                    self.content = ""
                    self.tool_calls = []
                    self.error = error_msg

            return MockResponse("Chat completion failed")

    def embed(self, text: str) -> list[float]:
        """Generate embeddings for text using the underlying LLM client.

        Args:
            text: Text to embed.

        Returns:
            List[float]: Embedding vector.
        """
        return self.llm_client.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using the underlying LLM client.

        Args:
            texts: List of texts to embed.

        Returns:
            List[List[float]]: List of embedding vectors.
        """
        return self.llm_client.embed_batch(texts)

    def get_embedding_dimensions(self) -> int:
        """Get the embedding dimensions from the underlying LLM client.

        Returns:
            int: Embedding dimensions.
        """
        return self.llm_client.get_embedding_dimensions()


def _get_llm_client_memu_compatible(**kwargs: Any) -> BaseLLMClient:
    """Get an LLM client with MemU system compatibility.

    This is a placeholder that should not be used directly.
    Use LangChainLLMAdapter instead to wrap LangChain models.

    Args:
        **kwargs: Additional arguments (unused).

    Returns:
        BaseLLMClient: Configured LLM client.

    Raises:
        NotImplementedError: Always, use LangChainLLMAdapter instead.
    """
    msg = "Use LangChainLLMAdapter to wrap LangChain models instead"
    raise NotImplementedError(msg)
