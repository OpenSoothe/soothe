"""MemU LLM adapter compatibility layer."""

from __future__ import annotations

import logging
from typing import Any

from .llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

################################################################################
# MemU agent compatibility
################################################################################


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
