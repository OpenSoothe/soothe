# Unified LLM Utilities Module Design

> Consolidate all LLM calling and adaptation logic into `packages/soothe/src/soothe/utils/llm/` with unified APIs for OpenAI-compatible, Anthropic, and local inference providers.

---

## Problem Statement

Currently, LLM-related code is scattered across multiple locations:

- **Model creation** in `config/settings.py` (`SootheConfig.create_chat_model`)
- **Structured output** in `utils/llm/structured_invoke.py`
- **Provider wrappers** in `utils/llm/wrappers.py`
- **Token observability** in `utils/observability/llm_token_observability.py`
- **Ad-hoc instantiation** in `subagents/browser_use/implementation.py` and `toolkits/_internal/document.py`

This fragmentation causes:
1. Import paths are inconsistent and hard to discover
2. LLM logic is coupled with configuration schema (`SootheConfig`)
3. No clear extension point for new provider types
4. Testing provider-specific behaviors requires piecing together multiple modules

---

## Goals

1. **Unified namespace** — All LLM-related imports from `soothe.utils.llm`
2. **Decoupled factory** — Model creation logic separated from `SootheConfig`
3. **Automatic provider adaptation** — Wrapper chain applied based on provider type
4. **Clean extension points** — Registry pattern for new provider types
5. **Comprehensive testing** — Unit and integration tests covering all provider protocols

---

## Architecture

### Module Structure

```
packages/soothe/src/soothe/utils/llm/
├── __init__.py          # Public API contract (re-exports)
├── types.py             # ProviderType enum, ModelRole alias, constants
├── registry.py          # Provider detection and credential resolution
├── factory.py           # LLMFactory class (model creation + caching)
├── structured.py        # Structured output helpers (renamed from structured_invoke.py)
├── wrappers.py          # Provider compatibility wrappers (existing, refined)
├── schema_wire.py       # JSON Schema wire helpers (existing, unchanged)
└── observability.py     # Token/streaming observability (moved from utils/observability/)
```

> **Note**: Private helpers (wrapper chain, cache key generation) are private methods within `factory.py`, not a separate `_internal.py` module.

### Layer Responsibilities

| Layer | Responsibility |
|-------|---------------|
| `types.py` | Shared enums, type aliases, wrapper order constants |
| `registry.py` | Provider lookup, type detection, credential resolution |
| `factory.py` | Model instantiation, caching, wrapper chain application |
| `structured.py` | Structured output invocation with fallback methods |
| `wrappers.py` | Provider-specific compatibility wrappers |
| `observability.py` | Token counting, streaming stats, callback handlers |

---

## Components

### `types.py` — Shared Types

```python
from enum import Enum
from typing import Literal

class ProviderType(Enum):
    """Provider type for wrapper chain selection."""
    OPENAI = "openai"
    LIMITED_OPENAI = "limited_openai"   # LMStudio, MLXServer, SGLang, vLLM
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    CUSTOM = "custom"

# Re-export ModelRole for API consistency
ModelRole = Literal["default", "fast", "think", "image", "embedding"]

# Wrapper chain order (applied left-to-right)
WRAPPER_CHAIN_ORDER: tuple[str, ...] = ("limited_openai", "observability")
```

### `registry.py` — Provider Registry

```python
class ProviderRegistry:
    """Provider configuration lookup and type detection."""

    def __init__(self, providers: list[ModelProviderConfig]) -> None:
        self._providers = {p.name: p for p in providers}

    def get_provider(self, name: str) -> ModelProviderConfig | None:
        """Lookup provider config by name."""
        return self._providers.get(name)

    def resolve_provider_type(self, name: str) -> ProviderType:
        """Detect provider type from config."""
        provider = self.get_provider(name)
        if provider is None:
            return ProviderType.CUSTOM
        type_str = provider.provider_type
        # Map config string to enum
        return ProviderType(type_str) if type_str in ProviderType._value2member_map_ else ProviderType.CUSTOM

    def get_provider_kwargs(self, name: str) -> tuple[str, dict[str, Any]]:
        """Build init_chat_model kwargs for a provider."""
        provider = self.get_provider(name)
        # Resolve base_url, api_key with ${ENV_VAR} expansion
        # Return (provider_type_for_langchain, kwargs_dict)
```

### `factory.py` — LLM Factory

```python
from langchain_core.language_models import BaseChatModel

class LLMFactory:
    """Model creation with automatic provider adaptation."""

    def __init__(self, config: SootheConfig) -> None:
        self._config = config
        self._registry = ProviderRegistry(config.providers)
        self._cache: dict[str, BaseChatModel] = {}
        self._cache_lock = threading.Lock()

    def create_chat_model(self, role: ModelRole = "default") -> BaseChatModel:
        """Create model for router role with caching and wrappers."""
        spec = self._config.resolve_model(role)
        return self._create_from_spec(spec, {})

    def create_chat_model_for_spec(
        self,
        spec: str,
        params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Create model from explicit provider:model spec."""
        return self._create_from_spec(spec, params or {})

    def _create_from_spec(self, spec: str, params: dict[str, Any]) -> BaseChatModel:
        """Internal: parse spec, resolve provider, create, wrap, cache."""
        provider_name, model_name = self._parse_spec(spec)
        provider_type = self._registry.resolve_provider_type(provider_name)
        kwargs = self._registry.get_provider_kwargs(provider_name)

        # Build init_chat_model string
        init_str = f"{provider_type.value}:{model_name}" if provider_name else model_name

        # Create model
        model = init_chat_model(init_str, streaming=True, stream_usage=True, **kwargs)

        # Apply wrapper chain
        model = self._apply_wrapper_chain(model, provider_type, provider_name)

        # Cache and return
        cache_key = self._cache_key(spec, params)
        self._cache[cache_key] = model
        return model

    def _apply_wrapper_chain(
        self,
        model: BaseChatModel,
        provider_type: ProviderType,
        provider_name: str,
    ) -> BaseChatModel:
        """Apply provider-specific wrappers in order."""
        # LIMITED_OPENAI: LimitedProviderModelWrapper
        if provider_type == ProviderType.LIMITED_OPENAI:
            model = LimitedProviderModelWrapper(model, provider_name)

        # Always: Token observability
        model = SootheTokenUsageChatModel(model)

        return model

    def create_embedding_model(self) -> Embeddings:
        """Create embedding model using 'embedding' role."""
        # Similar pattern with DashScope special handling
```

### `structured.py` — Structured Output

Keep existing `structured_invoke.py` logic with minor refinements:

```python
async def invoke_structured_chat(
    chat: BaseChatModel,
    messages: list[Any],
    *,
    json_schema: dict[str, Any],
    schema_name: str | None = None,
    strict: bool = True,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke chat with structured output, method fallback chain."""
    # Existing implementation: function_calling -> json_schema -> json_mode

# Convenience wrapper that creates model internally
async def invoke_structured(
    factory: LLMFactory,
    messages: list[Any],
    json_schema: dict[str, Any],
    *,
    role: ModelRole = "default",
) -> dict[str, Any]:
    """Create model from factory and invoke structured."""
    chat = factory.create_chat_model(role)
    return await invoke_structured_chat(chat, messages, json_schema=json_schema)
```

### `wrappers.py` — Provider Wrappers

Keep existing classes with refined docstrings:

- `LimitedProviderModelWrapper`: Handles providers with limited OpenAI API compatibility
- `JsonSchemaModelWrapper`: JSON schema response format injection

### `observability.py` — Token Observability

Move from `utils/observability/llm_token_observability.py`:

```python
class SootheTokenUsageChatModel(BaseChatModel):
    """Wrapper that prepends token usage handling on every generate path."""

def extract_token_counts_from_llm_result(response: LLMResult) -> dict[str, int] | None:
    """Best-effort token totals from LLMResult."""

def get_llm_token_usage_callback_handler() -> SootheLLMTokenUsageCallbackHandler:
    """Return shared token-usage callback handler."""
```

---

## Public API (`__init__.py`)

```python
from soothe.utils.llm.factory import LLMFactory
from soothe.utils.llm.types import ProviderType, ModelRole
from soothe.utils.llm.structured import (
    invoke_structured_chat,
    invoke_structured_chat_typed,
    invoke_structured_chat_sync,
    invoke_structured_chat_sync_typed,
    invoke_structured,  # New convenience function
    StructuredOutputError,
)
from soothe.utils.llm.wrappers import (
    LimitedProviderModelWrapper,
    JsonSchemaModelWrapper,
)
from soothe.utils.llm.observability import (
    get_llm_token_usage_callback_handler,
    extract_token_counts_from_llm_result,
)
from soothe.utils.llm.schema_wire import (
    build_json_schema_response_format,
    validate_response_schema,
)

__all__ = [
    # Factory
    "LLMFactory",
    "ProviderType",
    "ModelRole",

    # Structured output
    "invoke_structured_chat",
    "invoke_structured_chat_typed",
    "invoke_structured_chat_sync",
    "invoke_structured_chat_sync_typed",
    "invoke_structured",
    "StructuredOutputError",

    # Wrappers (advanced)
    "LimitedProviderModelWrapper",
    "JsonSchemaModelWrapper",

    # Observability
    "get_llm_token_usage_callback_handler",
    "extract_token_counts_from_llm_result",

    # Schema helpers
    "build_json_schema_response_format",
    "validate_response_schema",
]
```

---

## Integration with SootheConfig

```python
class SootheConfig:
    _llm_factory: LLMFactory | None = None

    @property
    def llm_factory(self) -> LLMFactory:
        """Lazy-initialized LLM factory."""
        if self._llm_factory is None:
            from soothe.utils.llm import LLMFactory
            self._llm_factory = LLMFactory(self)
        return self._llm_factory

    # Backward compatibility: delegate to factory
    def create_chat_model(self, role: ModelRole = "default") -> BaseChatModel:
        return self.llm_factory.create_chat_model(role)

    def create_chat_model_for_spec(
        self,
        model_spec: str,
        *,
        model_params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        return self.llm_factory.create_chat_model_for_spec(model_spec, model_params)
```

---

## Data Flow

```
User Code
    │
    ├─ config.llm_factory.create_chat_model("default")
    │       │
    │       ├─ resolve_model("default") → "dashscope:qwen-max"
    │       ├─ parse_spec → ("dashscope", "qwen-max")
    │       ├─ registry.resolve_provider_type("dashscope") → LIMITED_OPENAI
    │       ├─ registry.get_provider_kwargs("dashscope") → ("openai", {base_url, api_key})
    │       ├─ init_chat_model("openai:qwen-max", ...)
    │       ├─ _apply_wrapper_chain(model, LIMITED_OPENAI)
    │       │       ├─ LimitedProviderModelWrapper(model)
    │       │       └─ SootheTokenUsageChatModel(model)
    │       └─ cache & return wrapped model
    │
    └─ invoke_structured_chat(model, messages, json_schema={...})
            │
            ├─ _try_create_structured_runnable (method fallback)
            │       ├─ function_calling (fails for thinking models)
            │       ├─ json_schema (works)
            │       └─ fallback to json_mode if needed
            ├─ ensure_json_keyword_in_messages
            ├─ ainvoke with RunnableConfig
            └─ normalize + post_validate
```

---

## Wrapper Chain by Provider Type

| Provider Type | Wrappers Applied |
|---------------|------------------|
| `openai` | `SootheTokenUsageChatModel` |
| `limited_openai` | `LimitedProviderModelWrapper` → `SootheTokenUsageChatModel` |
| `anthropic` | `SootheTokenUsageChatModel` |
| `ollama` | `SootheTokenUsageChatModel` |
| `custom` | `SootheTokenUsageChatModel` |

---

## Testing Strategy

### Test Organization

```
packages/soothe/tests/
├── unit/utils/llm/
│   ├── test_factory.py
│   ├── test_registry.py
│   ├── test_structured.py
│   ├── test_wrappers.py
│   ├── test_observability.py
│   └── test_schema_wire.py
│
└── integration/utils/llm/
│   ├── test_openai_provider.py
│   ├── test_anthropic_provider.py
    ├── test_limited_openai_providers.py
    ├── test_ollama_provider.py
    └── test_local_inference.py
```

### Unit Tests

#### `test_factory.py`

```python
class TestLLMFactory:
    def test_create_chat_model_caches_result(self, mock_config):
        """Model is cached under spec:key."""

    def test_create_chat_model_role_resolution(self, mock_config):
        """Role 'fast' resolves to correct provider:model."""

    def test_create_chat_model_for_spec_override(self, mock_config):
        """Explicit spec bypasses role resolution."""

    def test_wrapper_chain_limited_openai(self, mock_config):
        """LIMITED_OPENAI provider gets LimitedProviderModelWrapper."""

    def test_wrapper_chain_anthropic(self, mock_config):
        """Anthropic provider gets only token observability."""

    def test_streaming_enabled_by_default(self, mock_config):
        """Created models have streaming=True."""

    def test_concurrent_cache_access(self, mock_config):
        """Thread-safe cache with concurrent create calls."""
```

#### `test_registry.py`

```python
class TestProviderRegistry:
    def test_resolve_provider_type_openai(self):
        """provider_type='openai' maps to ProviderType.OPENAI."""

    def test_resolve_provider_type_limited_openai(self):
        """provider_type='limited_openai' maps correctly."""

    def test_resolve_provider_type_unknown_returns_custom(self):
        """Unknown provider types return ProviderType.CUSTOM."""

    def test_env_var_expansion_in_credentials(self):
        """${API_KEY} in api_key is resolved."""

    def test_provider_not_found_returns_none(self):
        """get_provider returns None for unknown name."""
```

#### `test_structured.py`

```python
class TestStructuredOutput:
    def test_invoke_structured_chat_function_calling(self, mock_chat):
        """function_calling method succeeds first."""

    def test_invoke_structured_chat_fallback_chain(self, mock_chat):
        """Falls from function_calling → json_schema → json_mode."""

    def test_invoke_structured_chat_typed_returns_pydantic(self, mock_chat):
        """Typed variant returns validated Pydantic instance."""

    def test_invoke_structured_chat_sync_blocking(self, mock_chat):
        """Sync variant blocks until completion."""

    def test_json_keyword_injection(self):
        """ensure_json_keyword_in_messages adds hint when missing."""

    def test_post_validation_raises_on_schema_violation(self):
        """Strict mode validates against jsonschema."""

    def test_method_cache_optimization(self, mock_chat):
        """Working method is cached for subsequent calls."""

    def test_thinking_model_rejects_function_calling(self, mock_chat):
        """Thinking models skip function_calling, use json_schema."""
```

#### `test_wrappers.py`

```python
class TestLimitedProviderModelWrapper:
    def test_with_structured_output_converts_to_json_schema(self, mock_model):
        """method=json_mode converted to json_schema."""

    def test_bind_tools_sanitizes_tool_choice(self, mock_model):
        """Object tool_choice converted to string 'auto'."""

    def test_reasoning_content_extraction(self, mock_response):
        """JSON extracted from reasoning_content when content empty."""

    def test_json_parse_failure_logging(self, mock_model, mock_response):
        """Detailed logs on JSON parse failure."""

class TestJsonSchemaModelWrapper:
    def test_response_format_injection(self, mock_model):
        """json_schema response_format injected on invoke."""

    def test_pydantic_model_parsing(self, mock_response):
        """Response parsed into Pydantic model."""

    def test_dict_schema_validation(self, mock_response):
        """Dict schema validated with jsonschema."""
```

#### `test_observability.py`

```python
class TestTokenObservability:
    def test_extract_token_counts_from_usage_metadata(self):
        """Tokens extracted from AIMessage.usage_metadata."""

    def test_extract_token_counts_from_llm_output(self):
        """Tokens extracted from LLMResult.llm_output['token_usage']."""

    def test_ensure_openai_style_token_usage_mutates(self):
        """llm_output mutated for Langfuse compatibility."""

    def test_callback_handler_prepended(self):
        """Token handler prepended to run_manager.handlers."""

    def test_callback_handler_logs_debug(self):
        """on_llm_end emits structured debug log."""
```

### Integration Tests

#### Provider Categories

| Category | Providers | Test Focus |
|----------|-----------|------------|
| **OpenAI-compatible** | OpenAI, DashScope (OpenAI endpoint) | Standard API, streaming, tool calling |
| **Anthropic** | Anthropic Claude | Native API, thinking, extended thinking |
| **Limited OpenAI** | LMStudio, MLXServer, SGLang, vLLM | JSON in reasoning_content, limited tool_choice |
| **Ollama** | Ollama local | Local inference, model pulling |
| **Local inference** | SGLang, vLLM, MLXServer | Performance, batching, structured output |

#### `test_openai_provider.py`

```python
@pytest.mark.integration
class TestOpenAIProvider:
    async def test_basic_chat_completion(self, real_config):
        """Standard invoke returns AIMessage."""

    async def test_streaming_chunks(self, real_config):
        """astream yields AIMessageChunk sequence."""

    async def test_tool_calling(self, real_config):
        """bind_tools + invoke produces tool calls."""

    async def test_structured_output_function_calling(self, real_config):
        """with_structured_output(method='function_calling') works."""

    async def test_structured_output_json_schema(self, real_config):
        """with_structured_output(method='json_schema') works."""

    async def test_token_usage_in_response(self, real_config):
        """usage_metadata populated correctly."""

    async def test_error_handling_rate_limit(self, real_config):
        """Rate limit error handled appropriately."""
```

#### `test_anthropic_provider.py`

```python
@pytest.mark.integration
class TestAnthropicProvider:
    async def test_basic_chat_completion(self, real_config):
        """Anthropic invoke returns AIMessage."""

    async def test_streaming_chunks(self, real_config):
        """astream with Anthropic-specific chunk handling."""

    async def test_extended_thinking(self, real_config):
        """thinking parameter produces reasoning_content."""

    async def test_tool_calling_with_thinking(self, real_config):
        """Tool calls work with thinking mode enabled."""

    async def test_structured_output_json_mode(self, real_config):
        """with_structured_output(method='json_mode') works."""

    async def test_structured_output_json_schema(self, real_config):
        """with_structured_output(method='json_schema') works."""

    async def test_token_usage_anthropic_format(self, real_config):
        """Anthropic token format extracted correctly."""

    async def test_error_handling_overload(self, real_config):
        """Overload error handled appropriately."""
```

#### `test_limited_openai_providers.py`

```python
@pytest.mark.integration
class TestLimitedOpenAIProviders:
    async def test_lmstudio_structured_output(self, lmstudio_config):
        """LMStudio returns JSON in reasoning_content."""

    async def test_mlxserver_json_schema(self, mlx_config):
        """MLXServer accepts json_schema format."""

    async def test_sglang_reasoning_content(self, sglang_config):
        """SGLang structured output via reasoning_content."""

    async def test_vllm_structured_output(self, vllm_config):
        """vLLM structured output handling."""

    async def test_tool_choice_string_only(self, lmstudio_config):
        """tool_choice='auto' works, object format rejected."""

    async def test_wrapper_applied_automatically(self, limited_config):
        """Factory applies LimitedProviderModelWrapper."""

    async def test_json_keyword_required(self, dashscope_config):
        """'json' keyword required in prompt for json_object mode."""
```

#### `test_local_inference.py`

```python
@pytest.mark.integration
class TestLocalInference:
    async def test_sglang_batching(self, sglang_config):
        """SGLang handles concurrent requests efficiently."""

    async def test_vllm_batching(self, vllm_config):
        """vLLM continuous batching works."""

    async def test_mlxserver_apple_silicon(self, mlx_config):
        """MLXServer optimized for Apple Silicon."""

    async def test_ollama_model_pull(self, ollama_config):
        """Ollama pulls model if not present."""

    async def test_ollama_structured_output(self, ollama_config):
        """Ollama structured output (json mode)."""

    async def test_local_provider_timeout_handling(self, local_config):
        """Timeout handling for slow local inference."""
```

---

## Test Infrastructure

### Mock Providers

```python
# tests/conftest.py

@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response with token usage."""

@pytest.fixture
def mock_anthropic_response():
    """Mock Anthropic API response with thinking."""

@pytest.fixture
def mock_limited_openai_response():
    """Mock LMStudio-style response with reasoning_content."""

@pytest.fixture
def mock_config(providers):
    """SootheConfig with configurable providers."""
```

### Environment Setup for Integration Tests

```yaml
# config/config.test.yml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    provider_type: openai
    models: [gpt-4o-mini]

  - name: anthropic
    api_key: ${ANTHROPIC_API_KEY}
    provider_type: anthropic
    models: [claude-sonnet-4-5]

  - name: lmstudio
    api_base_url: http://localhost:1234/v1
    provider_type: limited_openai
    models: [local-model]

  - name: sglang
    api_base_url: http://localhost:30000/v1
    provider_type: limited_openai
    models: [meta-llama/Llama-3.1-8B-Instruct]

  - name: ollama
    api_base_url: http://localhost:11434
    provider_type: ollama
    models: [llama3.2]
```

### Test Markers

```python
# pytest.ini
[pytest]
markers =
    integration: requires real API keys or local server running
    requires_openai: requires OPENAI_API_KEY
    requires_anthropic: requires ANTHROPIC_API_KEY
    requires_local_server: requires local inference server (LMStudio, SGLang, etc.)
    slow: long-running tests (batching, performance)
```

---

## Migration Plan

### Phase 1: Create Module Structure

1. Create `utils/llm/types.py` with `ProviderType` enum
2. Create `utils/llm/registry.py` with `ProviderRegistry`
3. Create `utils/llm/factory.py` with `LLMFactory`
4. Move `llm_token_observability.py` to `utils/llm/observability.py`
5. Rename `structured_invoke.py` to `structured.py`

### Phase 2: Integrate Factory

1. Add `llm_factory` property to `SootheConfig`
2. Update `SootheConfig.create_chat_model` to delegate
3. Update `utils/__init__.py` to re-export from `llm`

### Phase 3: Update Consumers

1. Update `subagents/browser_use/implementation.py` to use factory
2. Update `toolkits/_internal/document.py` to use factory
3. Update any other direct `init_chat_model` calls

### Phase 4: Testing

1. Implement unit tests for all modules
2. Implement integration tests for each provider category
3. Add CI configuration for provider-specific test jobs

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing `SootheConfig` callers | Keep delegation methods, deprecate gradually |
| Local inference servers unavailable in CI | Use mock fixtures, mark integration tests as optional |
| Anthropic extended thinking API changes | Pin to stable API version, add version check |
| Wrapper chain order bugs | Explicit `WRAPPER_CHAIN_ORDER` constant, unit tests |
| Cache key collisions | Include all params in key, use sorted JSON serialization |

---

## Success Criteria

1. **All LLM imports from single namespace**: `from soothe.utils.llm import ...`
2. **Factory decoupled from config**: `LLMFactory` is standalone class
3. **Automatic provider adaptation**: Correct wrappers applied without caller knowledge
4. **Test coverage ≥ 90%**: All provider paths have unit + integration tests
5. **Zero breaking changes**: Existing `SootheConfig` methods work unchanged

---

## Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Module structure | 1-2 days | None |
| Phase 2: Factory integration | 1 day | Phase 1 |
| Phase 3: Consumer updates | 1-2 days | Phase 2 |
| Phase 4: Testing | 2-3 days | Phase 1-3 |

**Total: 5-8 days**