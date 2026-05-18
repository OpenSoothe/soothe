"""LLM adaptation utilities for Soothe.

This module consolidates LLM-related adaptation and compatibility handling:

1. **Provider Compatibility**: Wrappers for limited OpenAI-compatible providers
2. **Structured Output**: Format conversions for providers with limited API support

Architecture:
- `wrappers.py`: LimitedProviderModelWrapper, JsonSchemaModelWrapper for compatibility
"""

from __future__ import annotations

from soothe.utils.llm.schema_wire import (
    DEFAULT_DIRECT_LLM_SCHEMA_NAME,
    build_json_schema_response_format,
    resolve_schema_name,
    validate_response_schema,
)
from soothe.utils.llm.structured_invoke import (
    StructuredOutputError,
    invoke_structured_chat,
    normalize_structured_result,
    post_validate_structured_dict,
)
from soothe.utils.llm.wrappers import (
    JsonSchemaModelWrapper,
    LimitedProviderModelWrapper,
)

__all__ = [
    "DEFAULT_DIRECT_LLM_SCHEMA_NAME",
    "JsonSchemaModelWrapper",
    "LimitedProviderModelWrapper",
    "StructuredOutputError",
    "build_json_schema_response_format",
    "invoke_structured_chat",
    "normalize_structured_result",
    "post_validate_structured_dict",
    "resolve_schema_name",
    "validate_response_schema",
]
