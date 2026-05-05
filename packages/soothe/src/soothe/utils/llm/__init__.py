"""LLM adaptation utilities for Soothe.

This module consolidates LLM-related adaptation and compatibility handling:

1. **Provider Compatibility**: Wrappers for limited OpenAI-compatible providers
2. **Structured Output**: Format conversions for providers with limited API support

Architecture:
- `wrappers.py`: LimitedProviderModelWrapper, JsonSchemaModelWrapper for compatibility
"""

from __future__ import annotations

from soothe.utils.llm.wrappers import (
    JsonSchemaModelWrapper,
    LimitedProviderModelWrapper,
)

__all__ = [
    "JsonSchemaModelWrapper",
    "LimitedProviderModelWrapper",
]
