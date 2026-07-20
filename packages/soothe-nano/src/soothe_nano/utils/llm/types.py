"""Shared types and constants for LLM utilities.

This module defines provider type classifications and model role aliases
used across the LLM utilities module for wrapper chain selection and
configuration resolution.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

ModelRole = Literal["default", "fast", "think", "image", "ocr", "embedding"]
"""Valid purpose-based model roles.

Re-exported from config for API convenience. Maps to router.* fields:

- ``default``: Main orchestrator reasoning (CoreAgent, failure analysis, system context).
- ``fast``: Cheap/fast operations (intent classification, routing, scenario classification,
  deep_research subagents, memory extraction, document/audio tooling).
- ``think``: Stronger reasoning (planning, consensus validation, backoff reasoning).
- ``image``: Vision-capable model (image analysis, daemon vision preflight).
- ``ocr``: Dedicated OCR / document text extraction model.
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

    When ``api_base_url`` points at a non-standard endpoint (local oMLX, LMStudio, vLLM),
    ``LLMFactory`` auto-applies ``OpenAICompatModelWrapper`` for ``reasoning_content``
    and ``tool_choice`` compatibility.
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
