"""Core LLM adaptation module for Soothe.

This module consolidates all LLM-related adaptation and compatibility handling:

1. **LLM Tracing**: Request/response logging for direct model calls
2. **Provider Compatibility**: Wrappers for limited OpenAI-compatible providers
3. **Structured Output**: Format conversions for providers with limited API support

Architecture:
- `tracing.py`: LLMTracingWrapper for non-CoreAgent model calls
- `wrappers.py`: LimitedProviderModelWrapper, JsonSchemaModelWrapper for compatibility
"""

from __future__ import annotations

from soothe.core.llm.tracing import LLMTracingWrapper
from soothe.core.llm.wrappers import (
    JsonSchemaModelWrapper,
    LimitedProviderModelWrapper,
)

__all__ = [
    "LLMTracingWrapper",
    "JsonSchemaModelWrapper",
    "LimitedProviderModelWrapper",
]
