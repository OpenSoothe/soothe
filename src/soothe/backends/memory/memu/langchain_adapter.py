"""Adapter to make LangChain models compatible with memU's BaseLLMClient."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .llm_client import ChatCompletionResponse, FunctionCall, ToolCall

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class LangChainLLMAdapter:
    """Adapts LangChain chat models to BaseLLMClient interface."""

    def __init__(
        self,
        chat_model: BaseChatModel,
        embedding_model: Any = None,
    ) -> None:
        """Initialize adapter with LangChain models.

        Args:
            chat_model: LangChain chat model for completions.
            embedding_model: LangChain embedding model for embeddings.
        """
        self.chat_model = chat_model
        self.embedding_model = embedding_model

    def completion(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Generate completion using LangChain model."""
        lc_messages = self._convert_messages(messages)
        response = self.chat_model.invoke(lc_messages, **kwargs)
        return response.content

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",  # noqa: ARG002
        **kwargs: Any,
    ) -> ChatCompletionResponse:
        """Generate chat completion with function calling."""
        try:
            lc_messages = self._convert_messages(messages)

            # Bind tools if provided
            model = self.chat_model
            if tools:
                lc_tools = self._convert_tools(tools)
                model = model.bind_tools(lc_tools)

            response = model.invoke(lc_messages, **kwargs)

            # Extract tool calls if present
            tool_calls = []
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_calls.extend(
                    ToolCall(
                        id=tc.get("id", ""),
                        function=FunctionCall(
                            name=tc["name"],
                            arguments=json.dumps(tc["args"]),
                        ),
                    )
                    for tc in response.tool_calls
                )

            return ChatCompletionResponse(
                success=True,
                content=response.content or "",
                tool_calls=tool_calls,
                error=None,
            )

        except Exception:
            logger.exception("Chat completion failed")
            return ChatCompletionResponse(
                success=False,
                content="",
                tool_calls=[],
                error="Chat completion failed",
            )

    def simple_chat(self, message: str) -> str:
        """Simple chat method for memory actions.

        Args:
            message: The message to send to the LLM.

        Returns:
            The LLM response as string.
        """
        messages = [{"role": "user", "content": message}]
        response = self.completion(messages)
        return str(response)

    def embed(self, text: str) -> list[float]:
        """Generate embedding using LangChain embedding model."""
        if not self.embedding_model:
            msg = "No embedding model configured"
            raise ValueError(msg)
        return self.embedding_model.embed_query(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if not self.embedding_model:
            msg = "No embedding model configured"
            raise ValueError(msg)
        return self.embedding_model.embed_documents(texts)

    def get_embedding_dimensions(self) -> int:
        """Get embedding dimensions."""
        if not self.embedding_model:
            msg = "No embedding model configured"
            raise ValueError(msg)
        # Common embedding dimensions - can be made configurable
        return 1536  # OpenAI default

    def _convert_messages(self, messages: list[dict[str, str]]) -> list[Any]:
        """Convert dict messages to LangChain message objects."""
        lc_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        return lc_messages

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tool schemas to LangChain format."""
        # LangChain uses the same OpenAI tool format
        return tools
