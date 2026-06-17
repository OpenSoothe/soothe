# IG-627: Unified LLM Utilities Module Implementation

**IG**: 627
**RFC**: RFC-627 — Unified LLM Utilities Module
**Status**: Draft
**Created**: 2026-06-17
**Estimate**: 5-8 days

---

## Implementation Overview

This guide implements RFC-627, consolidating all LLM calling and adaptation logic into `utils/llm/`. Implementation proceeds in dependency order: types → registry → factory → integration → consumers → tests.

---

## Phase 1: Module Structure

### Task 1.1: Create `types.py`

**File**: `packages/soothe/src/soothe/utils/llm/types.py`

```python
"""Shared types and constants for LLM utilities."""

from __future__ import annotations

from enum import Enum
from typing import Literal

ModelRole = Literal["default", "fast", "think", "image", "embedding"]
"""Valid purpose-based model roles (re-export from config for API convenience)."""


class ProviderType(Enum):
    """Provider type for wrapper chain selection.

    Maps to ``ModelProviderConfig.provider_type`` in config YAML.
    """

    OPENAI = "openai"
    """Standard OpenAI API with full compatibility."""

    LIMITED_OPENAI = "limited_openai"
    """Limited OpenAI-compatible APIs (LMStudio, MLXServer, SGLang, vLLM).
    
    Limitations:
    - Accept json_schema response_format but may return empty content field
    - Return structured JSON in reasoning_content field (thinking tokens)
    - Only accept string tool_choice values: "none", "auto", "required"
    """

    ANTHROPIC = "anthropic"
    """Anthropic Claude API."""

    OLLAMA = "ollama"
    """Ollama local inference."""

    CUSTOM = "custom"
    """Custom/unknown provider type."""


__all__ = [
    "ModelRole",
    "ProviderType",
]
```

### Task 1.2: Create `registry.py`

**File**: `packages/soothe/src/soothe/utils/llm/registry.py`

```python
"""Provider configuration lookup and credential resolution."""

from __future__ import annotations

import logging
from typing import Any

from soothe.config.env import _resolve_provider_env
from soothe.config.models import ModelProviderConfig
from soothe.utils.llm.types import ProviderType

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Provider configuration lookup and type detection.

    Holds provider configs and resolves credentials with ${ENV_VAR} expansion.
    Used by LLMFactory to determine wrapper chain and build init_chat_model kwargs.
    """

    def __init__(self, providers: list[ModelProviderConfig]) -> None:
        """Initialize registry with provider configs.

        Args:
            providers: List of ModelProviderConfig from SootheConfig.
        """
        self._providers: dict[str, ModelProviderConfig] = {p.name: p for p in providers}

    def get_provider(self, name: str) -> ModelProviderConfig | None:
        """Lookup provider config by name.

        Args:
            name: Provider name from config.

        Returns:
            Provider config or None if not found.
        """
        return self._providers.get(name)

    def resolve_provider_type(self, name: str) -> ProviderType:
        """Detect provider type from config.

        Args:
            name: Provider name from config.

        Returns:
            ProviderType enum. Returns CUSTOM if provider not found or type unknown.
        """
        provider = self.get_provider(name)
        if provider is None:
            return ProviderType.CUSTOM
        type_str = provider.provider_type
        try:
            return ProviderType(type_str)
        except ValueError:
            logger.warning(
                "Unknown provider_type '%s' for provider '%s', treating as CUSTOM",
                type_str,
                name,
            )
            return ProviderType.CUSTOM

    def get_provider_kwargs(self, name: str) -> tuple[str, dict[str, Any]]:
        """Build init_chat_model kwargs for a provider.

        Resolves ${ENV_VAR} in api_base_url and api_key.
        For LIMITED_OPENAI, returns ("openai", kwargs) since langchain uses OpenAI API.

        Args:
            name: Provider name from config.

        Returns:
            Tuple of (provider_type_for_langchain, kwargs_dict).
            kwargs_dict contains base_url, api_key, use_responses_api=False if custom base_url.
        """
        provider = self.get_provider(name)
        kwargs: dict[str, Any] = {}
        provider_type_str = name  # Default to provider name

        if provider:
            provider_type_str = provider.provider_type
            # LIMITED_OPENAI uses OpenAI API format, but needs special handling
            actual_type = "openai" if provider_type_str == "limited_openai" else provider_type_str

            if provider.api_base_url:
                resolved = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
                if resolved:
                    kwargs["base_url"] = resolved
                    if actual_type == "openai":
                        kwargs["use_responses_api"] = False

            if provider.api_key:
                resolved = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
                if resolved:
                    kwargs["api_key"] = resolved

            return actual_type, kwargs

        return provider_type_str, kwargs


__all__ = [
    "ProviderRegistry",
]
```

### Task 1.3: Create `factory.py`

**File**: `packages/soothe/src/soothe/utils/llm/factory.py`

```python
"""LLM factory with automatic provider adaptation."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from soothe.config.models import ModelRole
from soothe.utils.llm.observability import SootheTokenUsageChatModel
from soothe.utils.llm.registry import ProviderRegistry
from soothe.utils.llm.types import ProviderType
from soothe.utils.llm.wrappers import LimitedProviderModelWrapper

logger = logging.getLogger(__name__)

_model_cache_lock = threading.Lock()


class LLMFactory:
    """Model creation with automatic provider adaptation.

    Decouples model instantiation from SootheConfig, providing:
    - Model caching by spec + params
    - Automatic wrapper chain based on provider type
    - Thread-safe concurrent access

    Usage:
        factory = LLMFactory(config)
        model = factory.create_chat_model("default")
        model = factory.create_chat_model_for_spec("anthropic:claude-sonnet-4-5")
    """

    def __init__(self, config: Any) -> None:
        """Initialize factory with config reference.

        Args:
            config: SootheConfig instance (typed as Any to avoid circular import).
        """
        self._config = config
        self._registry = ProviderRegistry(config.providers)
        self._cache: dict[str, BaseChatModel] = {}
        self._embedding_cache: dict[str, Embeddings] = {}

    def resolve_model(self, role: ModelRole = "default") -> str:
        """Resolve model spec for a role via config router.

        Args:
            role: Purpose role (default, fast, think, image, embedding).

        Returns:
            provider:model string.
        """
        return self._config.resolve_model(role)

    def create_chat_model(self, role: ModelRole = "default") -> BaseChatModel:
        """Create model for router role with caching and wrappers.

        Args:
            role: Purpose role.

        Returns:
            Wrapped BaseChatModel instance.
        """
        spec = self.resolve_model(role)
        return self._create_from_spec(spec, {})

    def create_chat_model_for_spec(
        self,
        spec: str,
        params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Create model from explicit provider:model spec.

        Args:
            spec: provider:model string.
            params: Extra kwargs for init_chat_model.

        Returns:
            Wrapped BaseChatModel instance.
        """
        return self._create_from_spec(spec, params or {})

    def _parse_spec(self, spec: str) -> tuple[str, str]:
        """Parse provider:model spec into components.

        Args:
            spec: provider:model or just model string.

        Returns:
            Tuple of (provider_name, model_name). provider_name empty if not prefixed.
        """
        provider_name, _, model_name = spec.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""
        return provider_name, model_name

    def _cache_key(self, spec: str, params: dict[str, Any]) -> str:
        """Build cache key from spec and params.

        Args:
            spec: provider:model string.
            params: Extra kwargs.

        Returns:
            Cache key string.
        """
        return f"{spec}:streaming:{json.dumps(params, sort_keys=True, default=str)}"

    def _create_from_spec(self, spec: str, params: dict[str, Any]) -> BaseChatModel:
        """Internal: parse spec, resolve provider, create, wrap, cache.

        Args:
            spec: provider:model string.
            params: Extra kwargs.

        Returns:
            Wrapped BaseChatModel instance.
        """
        spec_str = (spec or "").strip()
        if not spec_str:
            raise ValueError("model_spec is required")

        merged_params = dict(params)
        cache_key = self._cache_key(spec_str, merged_params)

        with _model_cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

            provider_name, model_name = self._parse_spec(spec_str)
            provider_type = self._registry.resolve_provider_type(provider_name)
            provider_type_str, kwargs = self._registry.get_provider_kwargs(provider_name)
            merged_kwargs = {**kwargs, **merged_params}

            init_str = f"{provider_type_str}:{model_name}" if provider_name else spec_str
            model = init_chat_model(init_str, streaming=True, stream_usage=True, **merged_kwargs)

            model = self._apply_wrapper_chain(model, provider_type, provider_name)

            self._cache[cache_key] = model
            logger.debug("Created and cached model for spec '%s'", spec_str)

        return model

    def _apply_wrapper_chain(
        self,
        model: BaseChatModel,
        provider_type: ProviderType,
        provider_name: str,
    ) -> BaseChatModel:
        """Apply provider-specific wrappers in order.

        Wrapper chain:
        - LIMITED_OPENAI: LimitedProviderModelWrapper → SootheTokenUsageChatModel
        - All others: SootheTokenUsageChatModel only

        Args:
            model: Raw model from init_chat_model.
            provider_type: Detected provider type.
            provider_name: Provider name for logging.

        Returns:
            Wrapped model.
        """
        if provider_type == ProviderType.LIMITED_OPENAI:
            logger.info(
                "Provider '%s' is limited_openai, applying compatibility wrapper",
                provider_name,
            )
            model = LimitedProviderModelWrapper(model, provider_name)

        # Always apply token observability
        model = SootheTokenUsageChatModel(model)

        return model

    def create_embedding_model(self) -> Embeddings:
        """Create embedding model using 'embedding' role.

        Handles DashScope special cases (OpenAI-compatible vs native).

        Returns:
            Embeddings instance.
        """
        from langchain.embeddings import init_embeddings

        spec = self.resolve_model("embedding")
        provider_name, _, model_name = spec.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""

        cache_key = spec
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        provider_type_str, kwargs = self._registry.get_provider_kwargs(provider_name)
        kwargs.pop("use_responses_api", None)

        # DashScope special handling
        if provider_name == "dashscope":
            base_url = kwargs.get("base_url", "")
            if "compatible-mode" in base_url:
                from soothe.utils.embeddings_dashscope_openai import DashScopeOpenAIEmbeddings

                embedding_kwargs = {k: v for k, v in kwargs.items() if k != "base_url"}
                embeddings = DashScopeOpenAIEmbeddings(
                    model=model_name,
                    dimension=self._config.embedding_dims,
                    base_url=base_url,
                    **embedding_kwargs,
                )
            else:
                from soothe.utils.embeddings_dashscope import DashScopeEmbeddings

                embeddings = DashScopeEmbeddings(
                    model=model_name,
                    dimension=self._config.embedding_dims,
                    **kwargs,
                )
            self._embedding_cache[cache_key] = embeddings
            logger.debug("Created DashScope embedding model for '%s'", spec)
            return embeddings

        init_str = f"{provider_type_str}:{model_name}" if provider_name else spec
        embeddings = init_embeddings(init_str, **kwargs)
        self._embedding_cache[cache_key] = embeddings
        logger.debug("Created embedding model for '%s'", spec)

        return embeddings


__all__ = [
    "LLMFactory",
]
```

### Task 1.4: Move observability module

**Move**: `packages/soothe/src/soothe/utils/observability/llm_token_observability.py`
**To**: `packages/soothe/src/soothe/utils/llm/observability.py`

Keep all existing code unchanged. Update imports in moved file to maintain relative paths.

### Task 1.5: Rename structured_invoke to structured

**Rename**: `packages/soothe/src/soothe/utils/llm/structured_invoke.py`
**To**: `packages/soothe/src/soothe/utils/llm/structured.py`

Keep existing code. Add convenience wrapper:

```python
async def invoke_structured(
    factory: LLMFactory,
    messages: list[Any],
    json_schema: dict[str, Any],
    *,
    role: ModelRole = "default",
    schema_name: str | None = None,
    strict: bool = True,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create model from factory and invoke structured.

    Convenience wrapper combining factory model creation with structured output.

    Args:
        factory: LLMFactory instance.
        messages: Message list for invoke.
        json_schema: Client JSON Schema dict.
        role: Model role to use.
        schema_name: Optional provider schema name.
        strict: Post-validate parsed output.
        config: Optional RunnableConfig.

    Returns:
        Parsed and validated dict.
    """
    chat = factory.create_chat_model(role)
    return await invoke_structured_chat(
        chat,
        messages,
        json_schema=json_schema,
        schema_name=schema_name,
        strict=strict,
        config=config,
    )
```

---

## Phase 2: Integration

### Task 2.1: Update `utils/llm/__init__.py`

**File**: `packages/soothe/src/soothe/utils/llm/__init__.py`

```python
"""Unified LLM utilities module.

This module consolidates all LLM calling and adaptation logic with:
- LLMFactory: Model creation with automatic provider adaptation
- Structured output: Method fallback chain for thinking models
- Provider wrappers: Compatibility for limited OpenAI providers
- Token observability: Langfuse-compatible token tracking

Usage:
    from soothe.utils.llm import LLMFactory, invoke_structured_chat

    factory = LLMFactory(config)
    model = factory.create_chat_model("default")
    result = await invoke_structured_chat(model, messages, json_schema=my_schema)
"""

from __future__ import annotations

from soothe.utils.llm.factory import LLMFactory
from soothe.utils.llm.observability import (
    SootheLLMTokenUsageCallbackHandler,
    SootheTokenUsageChatModel,
    extract_token_counts_from_llm_result,
    get_llm_token_usage_callback_handler,
)
from soothe.utils.llm.registry import ProviderRegistry
from soothe.utils.llm.schema_wire import (
    DEFAULT_DIRECT_LLM_SCHEMA_NAME,
    build_json_schema_response_format,
    resolve_schema_name,
    validate_response_schema,
)
from soothe.utils.llm.structured import (
    StructuredOutputError,
    ensure_json_keyword_in_messages,
    invoke_structured,
    invoke_structured_chat,
    invoke_structured_chat_sync,
    invoke_structured_chat_sync_typed,
    invoke_structured_chat_typed,
    messages_contain_json_keyword,
    normalize_structured_result,
    post_validate_structured_dict,
    wrap_json_keyword_safe,
)
from soothe.utils.llm.types import ModelRole, ProviderType
from soothe.utils.llm.wrappers import (
    JsonSchemaModelWrapper,
    LimitedProviderModelWrapper,
)

__all__ = [
    # Factory
    "LLMFactory",
    "ProviderRegistry",
    "ProviderType",
    "ModelRole",

    # Structured output
    "invoke_structured",
    "invoke_structured_chat",
    "invoke_structured_chat_typed",
    "invoke_structured_chat_sync",
    "invoke_structured_chat_sync_typed",
    "StructuredOutputError",
    "ensure_json_keyword_in_messages",
    "messages_contain_json_keyword",
    "normalize_structured_result",
    "post_validate_structured_dict",
    "wrap_json_keyword_safe",

    # Wrappers
    "LimitedProviderModelWrapper",
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
```

### Task 2.2: Update `SootheConfig` delegation

**File**: `packages/soothe/src/soothe/config/settings.py`

Add `llm_factory` property and delegate existing methods:

```python
class SootheConfig(BaseSettings):
    # ... existing fields ...

    _llm_factory: LLMFactory | None = None

    @property
    def llm_factory(self) -> LLMFactory:
        """Lazy-initialized LLM factory.

        Decouples model creation logic from config schema.
        """
        if self._llm_factory is None:
            from soothe.utils.llm import LLMFactory
            self._llm_factory = LLMFactory(self)
        return self._llm_factory

    # Update existing methods to delegate
    def create_chat_model(self, role: ModelRole = "default") -> BaseChatModel:
        """Create a BaseChatModel for a given role.

        Delegates to llm_factory for backward compatibility.
        """
        return self.llm_factory.create_chat_model(role)

    def create_chat_model_for_spec(
        self,
        model_spec: str,
        *,
        model_params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Create a chat model from an explicit provider:model string.

        Delegates to llm_factory for backward compatibility.
        """
        return self.llm_factory.create_chat_model_for_spec(model_spec, model_params)

    def create_embedding_model(self) -> Embeddings:
        """Create an Embeddings instance using the 'embedding' role.

        Delegates to llm_factory for backward compatibility.
        """
        return self.llm_factory.create_embedding_model()
```

Remove the old `create_chat_model`, `create_chat_model_for_spec`, `create_embedding_model` implementations (they now delegate). Keep `_model_cache`, `_embedding_cache`, `_model_cache_lock` as private fields for transition period, then remove in Phase 3.

### Task 2.3: Update `utils/__init__.py`

**File**: `packages/soothe/src/soothe/utils/__init__.py`

Add re-export for convenience:

```python
from soothe.utils.llm import (
    LLMFactory,
    ProviderType,
    StructuredOutputError,
    invoke_structured_chat,
)

__all__ = [
    # ... existing exports ...
    "LLMFactory",
    "ProviderType",
    "StructuredOutputError",
    "invoke_structured_chat",
]
```

### Task 2.4: Update `utils/observability/__init__.py`

Remove LLM token observability exports (now in `utils/llm`):

```python
# Remove these exports (moved to utils/llm):
# - get_llm_token_usage_callback_handler
# - extract_token_counts_from_llm_result
# - SootheTokenUsageChatModel
```

---

## Phase 3: Consumer Updates

### Task 3.1: Update `subagents/browser_use/implementation.py`

**File**: `packages/soothe/src/soothe/subagents/browser_use/implementation.py`

Replace direct `init_chat_model` with factory:

```python
# Before:
from langchain.chat_models import init_chat_model
model = init_chat_model(model_provider, **llm_kwargs)

# After:
model = config.llm_factory.create_chat_model_for_spec(model_spec, model_params)
```

### Task 3.2: Update `toolkits/_internal/document.py`

**File**: `packages/soothe/src/soothe/toolkits/_internal/document.py`

Replace fallback `ChatOpenAI` with factory:

```python
# Before:
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# After:
if config:
    llm = config.llm_factory.create_chat_model("fast")
else:
    # Still need fallback for standalone usage
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
```

---

## Phase 4: Testing

### Task 4.1: Unit tests for `types.py`

**File**: `packages/soothe/tests/unit/utils/llm/test_types.py`

```python
"""Unit tests for LLM types."""

from soothe.utils.llm.types import ProviderType


class TestProviderType:
    def test_openai_value(self):
        assert ProviderType.OPENAI.value == "openai"

    def test_limited_openai_value(self):
        assert ProviderType.LIMITED_OPENAI.value == "limited_openai"

    def test_anthropic_value(self):
        assert ProviderType.ANTHROPIC.value == "anthropic"

    def test_ollama_value(self):
        assert ProviderType.OLLAMA.value == "ollama"

    def test_custom_value(self):
        assert ProviderType.CUSTOM.value == "custom"

    def test_from_string(self):
        assert ProviderType("openai") == ProviderType.OPENAI
        assert ProviderType("limited_openai") == ProviderType.LIMITED_OPENAI
```

### Task 4.2: Unit tests for `registry.py`

**File**: `packages/soothe/tests/unit/utils/llm/test_registry.py`

```python
"""Unit tests for ProviderRegistry."""

import pytest

from soothe.config.models import ModelProviderConfig
from soothe.utils.llm.registry import ProviderRegistry
from soothe.utils.llm.types import ProviderType


@pytest.fixture
def sample_providers():
    return [
        ModelProviderConfig(name="openai", provider_type="openai", api_key="${OPENAI_KEY}"),
        ModelProviderConfig(name="lmstudio", provider_type="limited_openai", api_base_url="http://localhost:1234/v1"),
        ModelProviderConfig(name="anthropic", provider_type="anthropic", api_key="${ANTHROPIC_KEY}"),
    ]


@pytest.fixture
def registry(sample_providers):
    return ProviderRegistry(sample_providers)


class TestProviderRegistry:
    def test_get_provider_found(self, registry):
        provider = registry.get_provider("openai")
        assert provider is not None
        assert provider.name == "openai"

    def test_get_provider_not_found(self, registry):
        provider = registry.get_provider("unknown")
        assert provider is None

    def test_resolve_provider_type_openai(self, registry):
        assert registry.resolve_provider_type("openai") == ProviderType.OPENAI

    def test_resolve_provider_type_limited_openai(self, registry):
        assert registry.resolve_provider_type("lmstudio") == ProviderType.LIMITED_OPENAI

    def test_resolve_provider_type_anthropic(self, registry):
        assert registry.resolve_provider_type("anthropic") == ProviderType.ANTHROPIC

    def test_resolve_provider_type_unknown_returns_custom(self, registry):
        assert registry.resolve_provider_type("unknown") == ProviderType.CUSTOM

    def test_get_provider_kwargs_openai(self, registry):
        provider_type, kwargs = registry.get_provider_kwargs("openai")
        assert provider_type == "openai"

    def test_get_provider_kwargs_limited_openai_returns_openai(self, registry):
        provider_type, kwargs = registry.get_provider_kwargs("lmstudio")
        assert provider_type == "openai"  # LangChain uses OpenAI API
        assert kwargs["base_url"] == "http://localhost:1234/v1"
        assert kwargs["use_responses_api"] == False
```

### Task 4.3: Unit tests for `factory.py`

**File**: `packages/soothe/tests/unit/utils/llm/test_factory.py`

```python
"""Unit tests for LLMFactory."""

import pytest
from unittest.mock import MagicMock, patch

from soothe.utils.llm.factory import LLMFactory
from soothe.utils.llm.types import ProviderType


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.providers = []
    config.router.default = "openai:gpt-4o-mini"
    config.router.fast = "openai:gpt-4o-mini"
    config.router.think = None
    config.embedding_dims = 1536
    config.resolve_model = lambda role: config.router.default if role == "default" else config.router.default
    return config


class TestLLMFactory:
    def test_resolve_model_default_role(self, mock_config):
        factory = LLMFactory(mock_config)
        spec = factory.resolve_model("default")
        assert spec == "openai:gpt-4o-mini"

    def test_parse_spec_with_provider(self, mock_config):
        factory = LLMFactory(mock_config)
        provider, model = factory._parse_spec("openai:gpt-4o")
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_parse_spec_without_provider(self, mock_config):
        factory = LLMFactory(mock_config)
        provider, model = factory._parse_spec("gpt-4o")
        assert provider == ""
        assert model == "gpt-4o"

    def test_cache_key_includes_params(self, mock_config):
        factory = LLMFactory(mock_config)
        key1 = factory._cache_key("openai:gpt-4o", {"temperature": 0.7})
        key2 = factory._cache_key("openai:gpt-4o", {"temperature": 0.5})
        assert key1 != key2

    def test_wrapper_chain_limited_openai(self, mock_config):
        factory = LLMFactory(mock_config)
        mock_model = MagicMock()

        wrapped = factory._apply_wrapper_chain(mock_model, ProviderType.LIMITED_OPENAI, "lmstudio")

        # Should have LimitedProviderModelWrapper then SootheTokenUsageChatModel
        assert wrapped is not mock_model

    def test_wrapper_chain_openai(self, mock_config):
        factory = LLMFactory(mock_config)
        mock_model = MagicMock()

        wrapped = factory._apply_wrapper_chain(mock_model, ProviderType.OPENAI, "openai")

        # Should have only SootheTokenUsageChatModel
        assert wrapped is not mock_model

    @patch("soothe.utils.llm.factory.init_chat_model")
    def test_create_chat_model_caches(self, mock_init, mock_config):
        mock_model = MagicMock()
        mock_init.return_value = mock_model
        mock_config.providers = []

        factory = LLMFactory(mock_config)
        model1 = factory.create_chat_model("default")
        model2 = factory.create_chat_model("default")

        # Same instance from cache
        assert model1 is model2
        # init_chat_model called only once
        mock_init.assert_called_once()
```

### Task 4.4: Integration tests for providers

**File**: `packages/soothe/tests/integration/utils/llm/test_openai_provider.py`

```python
"""Integration tests for OpenAI provider."""

import pytest
import os

from soothe.config.settings import SootheConfig
from soothe.utils.llm import LLMFactory, invoke_structured_chat


@pytest.fixture
def openai_config():
    return SootheConfig(
        providers=[
            {"name": "openai", "api_key": os.environ.get("OPENAI_API_KEY"), "provider_type": "openai"}
        ],
        router={"default": "openai:gpt-4o-mini"},
    )


@pytest.mark.integration
@pytest.mark.requires_openai
class TestOpenAIProvider:
    async def test_basic_chat_completion(self, openai_config):
        factory = LLMFactory(openai_config)
        model = factory.create_chat_model("default")

        from langchain_core.messages import HumanMessage
        response = await model.ainvoke([HumanMessage(content="Say 'hello'")])

        assert response.content is not None

    async def test_streaming_chunks(self, openai_config):
        factory = LLMFactory(openai_config)
        model = factory.create_chat_model("default")

        from langchain_core.messages import HumanMessage
        chunks = []
        async for chunk in model.astream([HumanMessage(content="Count to 3")]):
            chunks.append(chunk)

        assert len(chunks) > 0

    async def test_structured_output(self, openai_config):
        factory = LLMFactory(openai_config)
        model = factory.create_chat_model("default")

        from langchain_core.messages import HumanMessage
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]}

        result = await invoke_structured_chat(
            model,
            [HumanMessage(content="Return the number 5 as JSON with key 'count'")],
            json_schema=schema,
        )

        assert result["count"] == 5
```

---

## Verification

Run verification after each phase:

```bash
# After Phase 1 (module structure)
make lint
pytest packages/soothe/tests/unit/utils/llm/ -v

# After Phase 2 (integration)
pytest packages/soothe/tests/ -v --ignore=integration

# After Phase 3 (consumers)
make lint
pytest packages/soothe/tests/ -v

# After Phase 4 (testing)
./scripts/verify_finally.sh
```

---

## Dependencies

| Task | Depends On |
|------|-----------|
| 1.2 registry.py | 1.1 types.py |
| 1.3 factory.py | 1.1 types.py, 1.2 registry.py, 1.4 observability.py |
| 1.5 structured.py rename | None |
| 2.1 __init__.py | All of Phase 1 |
| 2.2 SootheConfig | 2.1 |
| 3.1 browser_use | 2.2 |
| 3.2 document.py | 2.2 |
| 4.1-4.4 tests | Phase 1-3 complete |

---

## Notes

- Keep backward compatibility: `SootheConfig.create_chat_model()` continues to work
- Deprecation warnings can be added in Phase 3 for direct config method usage
- Embedding special handling (DashScope) preserved in factory
- Wrapper classes unchanged except docstring refinement