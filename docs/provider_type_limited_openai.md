# Provider Type: `limited_openai`

## Overview

The `limited_openai` provider type is designed for OpenAI-compatible API providers that have limited compatibility with the full OpenAI API specification. These providers accept OpenAI API format but exhibit specific behavioral differences.

## Characteristics

Providers using `provider_type: limited_openai` typically exhibit:

1. **Structured Output Behavior**:
   - Accept `response_format={"type": "json_schema", ...}`
   - Return structured JSON in `reasoning_content` field (thinking tokens pattern)
   - May return empty `content` field in `AIMessage`

2. **Tool Choice Limitations**:
   - Only support string `tool_choice` values: `"none"`, `"auto"`, `"required"`
   - Do not support object-form `tool_choice` (e.g., `{"type": "function", "function": {"name": "..."}}`)

3. **JSON Schema Requirement**:
   - Reject `response_format={"type": "json_object"}`
   - Require `response_format={"type": "json_schema", "json_schema": {...}}`

## Supported Providers

Examples of providers requiring `limited_openai` type:

- **LMStudio**: Local inference server with thinking tokens support
- **MLXServer**: Apple Silicon MLX framework-based inference server
- **GLM Deployments**: Certain GLM model deployments (e.g., GLM-4.7-flash)
- **Similar Providers**: Any OpenAI-compatible provider returning JSON in `reasoning_content`

## Configuration Example

```yaml
providers:
  - name: mlxserver
    provider_type: limited_openai  # Required for correct handling
    api_base_url: "http://localhost:9271/v1"
    api_key: "fakeapikey"
    models:
      - glm-4.7-flash
      - glm-4.6v-flash
      - nomic-embed

  - name: lmstudio
    provider_type: limited_openai  # Required for correct handling
    api_base_url: "http://localhost:1234/v1"
    api_key: "fakeapikey"
    models:
      - local-model

router:
  default: "mlxserver:glm-4.7-flash"
  fast: "mlxserver:glm-4.7-flash"
```

## Implementation Details

### Wrapper Application

When `provider_type: limited_openai` is detected, `SootheConfig.create_chat_model()` automatically applies `LimitedProviderModelWrapper`:

```python
# settings.py (simplified)
if provider and provider.provider_type == "limited_openai":
    from soothe.core.llm.wrappers import LimitedProviderModelWrapper
    model = LimitedProviderModelWrapper(model, provider_name)
```

### Structured Output Handling

The `JsonSchemaModelWrapper` (used internally) checks both `content` and `reasoning_content` fields:

```python
# wrappers.py (simplified)
if hasattr(response, "content") and response.content:
    json_str = response.content
elif hasattr(response, "reasoning_content") and response.reasoning_content:
    json_str = response.reasoning_content  # ← Handles limited_openai providers
```

### Environment Propagation

Credentials are propagated to `OPENAI_API_KEY`/`OPENAI_BASE_URL` environment variables:

```python
# settings.py (simplified)
if provider_type in ("openai", "limited_openai") and provider.api_key:
    os.environ.setdefault("OPENAI_API_KEY", resolved_key)
```

## Why `limited_openai`?

### Previous Issue (with `provider_type: openai`)

**Problem Chain**:

1. Provider configured as `provider_type: openai`
2. No `LimitedProviderModelWrapper` applied
3. Intent classifier uses `model.with_structured_output(IntentClassification)`
4. LLM returns `AIMessage(content="", reasoning_content="{...json...}")`
5. Langchain's default parser checks `content` field → empty
6. Returns `None` → Intent classification fails

**Log Evidence**:
```
[LLM Trace #7] Response: 43697ms (no content field)
Intent classification error: LLM returned None - structured output parsing failed
```

### Solution (with `provider_type: limited_openai`)

**Fixed Chain**:

1. Provider configured as `provider_type: limited_openai`
2. `LimitedProviderModelWrapper` automatically applied
3. Wrapper uses `JsonSchemaModelWrapper` for structured output
4. Checks both `content` AND `reasoning_content` fields
5. Parses JSON from `reasoning_content` → Pydantic object
6. Returns `IntentClassification` successfully

## Migration Guide

If you're experiencing intent classification failures or empty responses with OpenAI-compatible providers:

### Symptoms

- Intent classification returns `None`
- LLM trace shows `(no content field)`
- Structured output parsing fails

### Fix

1. Identify the provider in your config file
2. Check if it returns JSON in `reasoning_content` field
3. Change `provider_type` from `"openai"` to `"limited_openai"`

```yaml
# Before
providers:
  - name: mlxserver
    provider_type: openai  # ← Issue
    ...

# After
providers:
  - name: mlxserver
    provider_type: limited_openai  # ← Fix
    ...
```

## Testing

Verify the provider type works:

```python
from soothe.config.settings import SootheConfig

config = SootheConfig(
    providers=[{
        "name": "test_provider",
        "provider_type": "limited_openai",
        "api_base_url": "http://localhost:1234/v1",
        "api_key": "test-key",
        "models": ["test-model"]
    }],
    router={"default": "test_provider:test-model"}
)

# Verify wrapper is applied
model = config.create_chat_model("default")
print(f"Model type: {type(model).__name__}")
# Output: "LimitedProviderModelWrapper"
```

## Related Documentation

- [LLM Compatibility Analysis](docs/lms_endpoint_compatibility_analysis.md)
- [JSON Schema Empty Response Analysis](docs/lms_json_schema_empty_response_analysis.md)
- [Core LLM Wrappers](packages/soothe/src/soothe/core/llm/wrappers.py)

## Implementation Status

- ✅ Provider type added to `ModelProviderConfig` documentation
- ✅ Wrapper application in `SootheConfig.create_chat_model()`
- ✅ Wrapper application in `SootheConfig.create_chat_model_for_spec()`
- ✅ Environment propagation in `SootheConfig.propagate_env()`
- ✅ Documentation in wrapper module docstrings
- ✅ All verification checks passed (1288 tests)

## Change History

**Date**: 2026-04-26
**Issue**: Intent classification returns `None` with mlxserver provider
**Root Cause**: Provider type mismatch (using `openai` instead of `limited_openai`)
**Fix**: Implemented `limited_openai` provider type with automatic wrapper application
**Files Modified**:
- `packages/soothe/src/soothe/config/models.py`
- `packages/soothe/src/soothe/config/settings.py`
- `packages/soothe/src/soothe/core/llm/wrappers.py`
- `config/config.dev.yml`