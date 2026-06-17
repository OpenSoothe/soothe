"""Shared types and constants for LLM utilities.

This module defines provider type classifications and model role aliases
used across the LLM utilities module for wrapper chain selection and
configuration resolution.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

ModelRole = Literal["default", "fast", "think", "image", "embedding"]
"""Valid purpose-based model roles.

Re-exported from config for API convenience. Maps to router.* fields:

- ``default``: Main orchestrator reasoning (CoreAgent, failure analysis, system context).
- ``fast``: Cheap/fast operations (intent classification, routing, scenario classification,
  explore/tacitus subagents, memory extraction, document/audio tooling).
- ``think``: Stronger reasoning (planning, consensus validation, backoff reasoning).
- ``image``: Vision-capable model (image analysis, daemon vision preflight).
- ``embedding``: Embedding model (MemU vector search, semantic memory).
"""


class ProviderType(Enum):
    """Provider type for wrapper chain selection.

    Maps to ``ModelProviderConfig.provider_type`` in config YAML.
    Determines which compatibility wrappers are applied by LLMFactory.
    """

    OPENAI = "openai"
    """Standard OpenAI API with full compatibility.

    Supports all structured output methods (function_calling, json_schema, json_mode).
    Accepts object and string tool_choice formats.
    """

    LIMITED_OPENAI = "limited_openai"
    """Limited OpenAI-compatible APIs (LMStudio, MLXServer, SGLang, vLLM).

    Providers with partial OpenAI API compatibility:

    - Accept ``json_schema`` response_format but may return empty ``content`` field
    - Return structured JSON in ``reasoning_content`` field (thinking tokens)
    - Only accept string ``tool_choice`` values: ``"none"``, ``"auto"``, ``"required"``
    - Reject object-form ``tool_choice`` (e.g., ``{"type": "function", "name": "..."}``)

    LLMFactory applies ``LimitedProviderModelWrapper`` for compatibility.
    """

    ANTHROPIC = "anthropic"
    """Anthropic Claude API.

    Native API with extended thinking support. Structured output via
    ``json_mode`` and ``json_schema`` methods (function_calling not available).
    """

    OLLAMA = "ollama"
    """Ollama local inference.

    OpenAI-compatible local server. Structured output via ``json_mode``.
    """

    CUSTOM = "custom"
    """Custom/unknown provider type.

    Treated as standard OpenAI-compatible. No special wrappers applied
    beyond token observability.
    """


__all__ = [
    "ModelRole",
    "ProviderType",
]
