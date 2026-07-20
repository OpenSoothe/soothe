"""Unified LLM utilities module.

This module consolidates all LLM calling and adaptation logic with:
- LLMFactory: Model creation with automatic provider adaptation
- Structured output: Method fallback chain for thinking models
- Provider wrappers: Compatibility for limited OpenAI providers
- Token observability: Langfuse-compatible token tracking

Architecture (RFC-627):
- `types.py`: ProviderType enum, ModelRole alias
- `registry.py`: Provider lookup and credential resolution
- `factory.py`: LLMFactory class (model creation + caching)
- `structured.py`: Structured output helpers with fallback chain
- `wrappers.py`: OpenAICompatModelWrapper, JsonSchemaModelWrapper
- `schema_wire.py`: JSON Schema wire helpers
- `observability.py`: Token/streaming observability

Usage:
    from soothe_nano.utils.llm import LLMFactory, invoke_structured_chat

    factory = LLMFactory(config)
    model = factory.create_chat_model("default")
    result = await invoke_structured_chat(model, messages, json_schema=my_schema)
"""

from __future__ import annotations

from soothe_nano.utils.llm.factory import LLMFactory
from soothe_nano.utils.llm.observability import (
    SootheLLMTokenUsageCallbackHandler,
    SootheTokenUsageChatModel,
    extract_token_counts_from_llm_result,
    get_llm_token_usage_callback_handler,
)
from soothe_nano.utils.llm.registry import ProviderRegistry
from soothe_nano.utils.llm.schema_wire import (
    DEFAULT_DIRECT_LLM_SCHEMA_NAME,
    build_json_schema_response_format,
    resolve_schema_name,
    validate_response_schema,
)
from soothe_nano.utils.llm.structured import (
    StructuredOutputError,
    ensure_json_keyword_in_messages,
    invoke_structured_chat,
    invoke_structured_chat_typed,
    messages_contain_json_keyword,
    normalize_structured_result,
    post_validate_structured_dict,
    wrap_json_keyword_safe,
)
from soothe_nano.utils.llm.types import ModelRole, ProviderType
from soothe_nano.utils.llm.wrappers import (
    JsonSchemaModelWrapper,
    OpenAICompatModelWrapper,
)

__all__ = [
    # Factory
    "LLMFactory",
    "ProviderRegistry",
    "ProviderType",
    "ModelRole",
    # Structured output
    "invoke_structured_chat",
    "invoke_structured_chat_typed",
    "StructuredOutputError",
    "ensure_json_keyword_in_messages",
    "messages_contain_json_keyword",
    "normalize_structured_result",
    "post_validate_structured_dict",
    "wrap_json_keyword_safe",
    # Wrappers (advanced use)
    "OpenAICompatModelWrapper",
    "JsonSchemaModelWrapper",
    # Observability
    "SootheTokenUsageChatModel",
    "SootheLLMTokenUsageCallbackHandler",
    "get_llm_token_usage_callback_handler",
    "extract_token_counts_from_llm_result",
    # Schema helpers
    "DEFAULT_DIRECT_LLM_SCHEMA_NAME",
    "build_json_schema_response_format",
    "resolve_schema_name",
    "validate_response_schema",
]
