# RFC-627: Unified LLM Utilities Module

**RFC**: 627
**Title**: Unified LLM Utilities Module — Consolidated LLM Calling and Adaptation
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-17
**Updated**: 2026-06-17
**Dependencies**: RFC-000 (System Conceptual Design), RFC-104 (Model Knowledge Cutoff)
**Related**: RFC-412 (Plugin Extension System), RFC-203 (StrangeLoop State & Memory)
**Extends**: None

---

## Abstract

This RFC consolidates all LLM calling and adaptation logic into a unified module at `packages/soothe/src/soothe/utils/llm/` with clean APIs for model creation, structured output, provider adaptation, and token observability. It introduces an `LLMFactory` class that decouples model instantiation from `SootheConfig`, automatic provider-specific wrapper chains, and comprehensive testing coverage for OpenAI-compatible, Anthropic, and local inference providers (LMStudio, MLXServer, SGLang, vLLM, Ollama).

---

## Problem Statement

### Current State

1. **Scattered LLM code**: LLM-related logic distributed across:
   - `config/settings.py`: `SootheConfig.create_chat_model()` (model creation)
   - `utils/llm/structured_invoke.py`: Structured output helpers
   - `utils/llm/wrappers.py`: Provider compatibility wrappers
   - `utils/observability/llm_token_observability.py`: Token counting
   - `subagents/browser_use/implementation.py`: Ad-hoc `init_chat_model`
   - `toolkits/_internal/document.py`: Fallback `ChatOpenAI`

2. **Config-logic coupling**: Model factory methods embedded in `SootheConfig` class, mixing configuration schema with LLM instantiation behavior.

3. **Inconsistent import paths**: No single namespace for LLM utilities; callers must know multiple import locations.

4. **No clear extension points**: Adding new provider types requires modifications across multiple files.

5. **Incomplete provider testing**: Limited test coverage for limited_openai providers (LMStudio, SGLang, vLLM), Anthropic extended thinking, and local inference servers.

### Goals

1. **Unified namespace**: All LLM-related imports from `soothe.utils.llm`.

2. **Decoupled factory**: `LLMFactory` class separate from `SootheConfig`, holding config reference and model cache.

3. **Automatic provider adaptation**: Wrapper chain applied based on provider type without caller knowledge.

4. **Clean extension points**: Registry pattern for new provider types.

5. **Comprehensive testing**: Unit and integration tests covering all provider protocols (OpenAI, Anthropic, limited_openai, Ollama, local inference).

### Non-Goals

- Changing LangChain integration patterns or API signatures
- Modifying CoreAgent prompt templates or execution flow
- Adding new provider implementations (only consolidating existing)
- Changing config file schema (`ModelProviderConfig` remains unchanged)

---

## Solution

### §1 Module Structure

All LLM utilities consolidated under `utils/llm/` with layered modules:

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

Private helpers (wrapper chain application, cache key generation) are private methods within `factory.py`.

### §2 Types and Constants

`types.py` defines shared types for cross-module consistency:

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

# Re-export ModelRole for API consistency (imported from config)
ModelRole = Literal["default", "fast", "think", "image", "embedding"]
```

### §3 Provider Registry

`registry.py` handles provider lookup and credential resolution:

```python
class ProviderRegistry:
    """Provider configuration lookup and type detection."""

    def __init__(self, providers: list[ModelProviderConfig]) -> None:
        self._providers = {p.name: p for p in providers}

    def get_provider(self, name: str) -> ModelProviderConfig | None:
        """Lookup provider config by name."""

    def resolve_provider_type(self, name: str) -> ProviderType:
        """Detect provider type from config string."""

    def get_provider_kwargs(self, name: str) -> tuple[str, dict[str, Any]]:
        """Build init_chat_model kwargs for a provider.
        
        Resolves ${ENV_VAR} in api_base_url and api_key.
        Returns (provider_type_for_langchain, kwargs_dict).
        """
```

**Provider Type Mapping**:

| Config `provider_type` | `ProviderType` Enum | LangChain Init String |
|------------------------|---------------------|----------------------|
| `openai` | `OPENAI` | `openai:model_name` |
| `limited_openai` | `LIMITED_OPENAI` | `openai:model_name` (wrapped) |
| `anthropic` | `ANTHROPIC` | `anthropic:model_name` |
| `ollama` | `OLLAMA` | `ollama:model_name` |
| Other | `CUSTOM` | Direct spec string |

### §4 LLM Factory

`factory.py` provides the core `LLMFactory` class:

```python
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

    def create_embedding_model(self) -> Embeddings:
        """Create embedding model using 'embedding' role."""

    def _create_from_spec(self, spec: str, params: dict[str, Any]) -> BaseChatModel:
        """Internal: parse spec, resolve provider, create, wrap, cache."""

    def _apply_wrapper_chain(
        self,
        model: BaseChatModel,
        provider_type: ProviderType,
        provider_name: str,
    ) -> BaseChatModel:
        """Apply provider-specific wrappers in order."""
```

**Factory Behavior**:

1. Parse spec string (`provider:model`)
2. Resolve provider type via registry
3. Build kwargs with env var expansion
4. Call `init_chat_model(init_str, streaming=True, stream_usage=True, **kwargs)`
5. Apply wrapper chain based on provider type
6. Cache under `spec:params:streaming` key
7. Return wrapped model

### §5 Wrapper Chain

Provider-specific wrappers applied automatically by provider type:

| Provider Type | Wrappers Applied (Order) |
|---------------|--------------------------|
| `openai` | `SootheTokenUsageChatModel` |
| `limited_openai` | `OpenAICompatModelWrapper` → `SootheTokenUsageChatModel` |
| `anthropic` | `SootheTokenUsageChatModel` |
| `ollama` | `SootheTokenUsageChatModel` |
| `custom` | `SootheTokenUsageChatModel` |

**Wrapper Responsibilities**:

- `OpenAICompatModelWrapper`: Converts `json_mode` to `json_schema`, sanitizes `tool_choice` to string values, extracts JSON from `reasoning_content` field
- `SootheTokenUsageChatModel`: Prepends token usage callback handler, ensures Langfuse-compatible token format in `llm_output`

### §6 Structured Output

`structured.py` (renamed from `structured_invoke.py`) provides structured output helpers:

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

async def invoke_structured_chat_typed(
    chat: BaseChatModel,
    messages: list[Any],
    schema: type[T],
    *,
    strict: bool = True,
    config: dict[str, Any] | None = None,
) -> T:
    """Typed variant returning Pydantic instance."""

# Convenience wrapper (NEW)
async def invoke_structured(
    factory: LLMFactory,
    messages: list[Any],
    json_schema: dict[str, Any],
    *,
    role: ModelRole = "default",
) -> dict[str, Any]:
    """Create model from factory and invoke structured."""
```

**Method Fallback Chain**: `function_calling` → `json_schema` → `json_mode`

Thinking models (MiniMax, glm-5, Moonshot) reject `function_calling` with `tool_choice` object; fallback to `json_schema` handles this automatically.

### §7 Token Observability

`observability.py` moved from `utils/observability/llm_token_observability.py`:

```python
class SootheTokenUsageChatModel(BaseChatModel):
    """Wrapper that prepends token usage handling on every generate path."""

def extract_token_counts_from_llm_result(response: LLMResult) -> dict[str, int] | None:
    """Best-effort token totals from LLMResult."""

def ensure_openai_style_token_usage_on_llm_result(response: LLMResult) -> None:
    """Mutate llm_output for Langfuse compatibility."""

def get_llm_token_usage_callback_handler() -> SootheLLMTokenUsageCallbackHandler:
    """Return shared token-usage callback handler."""
```

### §8 Public API

`__init__.py` exposes the unified API contract:

```python
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
    "OpenAICompatModelWrapper",
    "JsonSchemaModelWrapper",

    # Observability
    "get_llm_token_usage_callback_handler",
    "extract_token_counts_from_llm_result",

    # Schema helpers
    "build_json_schema_response_format",
    "validate_response_schema",
]
```

### §9 SootheConfig Integration

`SootheConfig` delegates to factory for backward compatibility:

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

Existing callers of `config.create_chat_model()` work unchanged.

### §10 Consumer Updates

Ad-hoc LLM instantiation replaced with factory usage:

| File | Current | Updated |
|------|---------|---------|
| `subagents/browser_use/implementation.py` | `init_chat_model(...)` | `config.llm_factory.create_chat_model_for_spec(...)` |
| `toolkits/_internal/document.py` | `ChatOpenAI(model=...)` | `config.llm_factory.create_chat_model("fast")` |

---

## Testing Strategy

### Unit Tests

Located in `packages/soothe/tests/unit/utils/llm/`:

| Module | Test File | Coverage Focus |
|--------|-----------|----------------|
| `factory.py` | `test_factory.py` | Caching, role resolution, wrapper chain, concurrency |
| `registry.py` | `test_registry.py` | Type detection, env var expansion, provider lookup |
| `structured.py` | `test_structured.py` | Fallback chain, typed variants, validation |
| `wrappers.py` | `test_wrappers.py` | JSON schema conversion, tool_choice sanitization |
| `observability.py` | `test_observability.py` | Token extraction, callback prepending |

### Integration Tests

Located in `packages/soothe/tests/integration/utils/llm/`:

| Provider | Test File | Tests |
|----------|-----------|-------|
| OpenAI | `test_openai_provider.py` | Chat, streaming, tools, structured output, tokens |
| Anthropic | `test_anthropic_provider.py` | Chat, streaming, extended thinking, tokens |
| Limited OpenAI | `test_limited_openai_providers.py` | LMStudio, MLXServer, SGLang, vLLM structured output |
| Ollama | `test_ollama_provider.py` | Local inference, model pull, structured output |
| Local | `test_local_inference.py` | Batching, timeout handling |

### Test Markers

```python
markers =
    integration: requires real API keys or local server running
    requires_openai: requires OPENAI_API_KEY
    requires_anthropic: requires ANTHROPIC_API_KEY
    requires_local_server: requires local inference server
    slow: long-running tests (batching, performance)
```

### Test Coverage Target

≥ 90% coverage for all provider paths (unit + integration).

---

## Migration Plan

### Phase 1: Module Structure (1-2 days)

1. Create `utils/llm/types.py` with `ProviderType` enum
2. Create `utils/llm/registry.py` with `ProviderRegistry`
3. Create `utils/llm/factory.py` with `LLMFactory`
4. Move `llm_token_observability.py` to `utils/llm/observability.py`
5. Rename `structured_invoke.py` to `structured.py`

### Phase 2: Factory Integration (1 day)

1. Add `llm_factory` property to `SootheConfig`
2. Update `SootheConfig.create_chat_model` to delegate
3. Update `utils/__init__.py` to re-export from `llm`

### Phase 3: Consumer Updates (1-2 days)

1. Update `subagents/browser_use/implementation.py`
2. Update `toolkits/_internal/document.py`
3. Audit for other direct `init_chat_model` calls

### Phase 4: Testing (2-3 days)

1. Implement unit tests for all modules
2. Implement integration tests for each provider category
3. Add CI configuration for provider-specific test jobs

**Total Timeline: 5-8 days**

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing `SootheConfig` callers | Delegation methods preserved; deprecation warning in Phase 3 |
| Local inference servers unavailable in CI | Mock fixtures + optional integration tests |
| Anthropic extended thinking API changes | Pin stable API version, version check in wrapper |
| Wrapper chain order bugs | Explicit order constant, comprehensive unit tests |
| Cache key collisions | Include all params, sorted JSON serialization |

---

## Success Criteria

1. **Unified namespace**: All LLM imports from `soothe.utils.llm`
2. **Factory decoupled**: `LLMFactory` is standalone class
3. **Automatic adaptation**: Wrappers applied by provider type
4. **Test coverage ≥ 90%**: All provider paths tested
5. **Zero breaking changes**: Existing `SootheConfig` methods unchanged

---

## Appendix A: Data Flow Diagram

```
User Code
    │
    ├─ config.llm_factory.create_chat_model("default")
    │       │
    │       ├─ resolve_model("default") → "provider:model"
    │       ├─ parse_spec → (provider_name, model_name)
    │       ├─ registry.resolve_provider_type(provider_name)
    │       ├─ registry.get_provider_kwargs(provider_name)
    │       ├─ init_chat_model(init_str, streaming=True, ...)
    │       ├─ _apply_wrapper_chain(model, provider_type, provider_name)
    │       │       ├─ OpenAICompatModelWrapper (if LIMITED_OPENAI)
    │       │       └─ SootheTokenUsageChatModel (always)
    │       └─ cache & return wrapped model
    │
    └─ invoke_structured_chat(model, messages, json_schema={...})
            │
            ├─ _try_create_structured_runnable (method fallback)
            ├─ ensure_json_keyword_in_messages
            ├─ ainvoke with RunnableConfig
            └─ normalize + post_validate
```

---

## Appendix B: Provider Configuration Example

```yaml
# config/config.yml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    provider_type: openai
    models: [gpt-4o, gpt-4o-mini]

  - name: anthropic
    api_key: ${ANTHROPIC_API_KEY}
    provider_type: anthropic
    models: [claude-sonnet-4-5, claude-opus-4-6]

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

router:
  default: openai:gpt-4o-mini
  think: anthropic:claude-opus-4-6
  fast: openai:gpt-4o-mini
  embedding: openai:text-embedding-3-small
```