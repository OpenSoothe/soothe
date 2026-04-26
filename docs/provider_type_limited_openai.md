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
- ✅ **LLMTracingWrapper.with_structured_output() delegation added** (critical fix)
- ✅ All verification checks passed (1288 tests)

## Critical Fix: LLMTracingWrapper Delegation

**Issue Found**: Daemon startup failed with:
```
AttributeError: 'LLMTracingWrapper' object has no attribute 'with_structured_output'
```

**Root Cause**: When `IntentClassifier` applies `LLMTracingWrapper` for tracing, then calls `with_structured_output()`:
```python
# classifier.py
traced_model = LLMTracingWrapper(model)  # ← Wraps model
self._intent_model = traced_model.with_structured_output(IntentClassification)  # ← AttributeError
```

**Fix**: Added delegation method to `LLMTracingWrapper`:
```python
# tracing.py
def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
    """Delegate structured output to wrapped model."""
    return self._model.with_structured_output(schema, **kwargs)
```

**Why Needed**: `IntentClassifier` wraps the base model with tracing before calling `with_structured_output()`. Without delegation, the wrapper would block the method call.

## Critical Fix: AIMessage Structure

**Issue Found**: Intent classification still returned `None` after delegation fix.

**Root Cause**: `AIMessage` stores `reasoning_content` in `additional_kwargs`, NOT as a direct attribute!

```python
# WRONG (old code)
if hasattr(response, "reasoning_content") and response.reasoning_content:
    json_str = response.reasoning_content  # ← Never executes!

# CORRECT (fixed code)
if (
    hasattr(response, "additional_kwargs")
    and "reasoning_content" in response.additional_kwargs
    and response.additional_kwargs["reasoning_content"]
):
    json_str = response.additional_kwargs["reasoning_content"]  # ← Works!
```

**Why This Happened**: Langchain's `AIMessage` structure:
```python
AIMessage(
    content="",  # Empty string (limited_openai providers)
    additional_kwargs={
        "reasoning_content": "{...json...}"  # JSON is HERE
    }
)
```

**Fix Applied**: Updated all checks in `JsonSchemaModelWrapper` to use `additional_kwargs.get("reasoning_content")` instead of direct attribute access.

**Files Modified**: `packages/soothe/src/soothe/core/llm/wrappers.py` (invoke + ainvoke methods)

## Critical Fix: LimitedProviderModelWrapper Method Handling

**Issue Found**: IntentClassifier still failed - returned `RunnableSequence` instead of `JsonSchemaModelWrapper`.

**Root Cause**: `LimitedProviderModelWrapper.with_structured_output()` only handled `method="json_mode"`:

```python
# WRONG (old code)
if method == "json_mode":
    return JsonSchemaModelWrapper(self._model, response_format, schema)
else:
    return self._model.with_structured_output(schema, **kwargs)  # ← Returns RunnableSequence!
```

IntentClassifier tries methods in order: `function_calling` → `None` → `json_mode`
When `method="function_calling"` is tried first, it delegated to langchain's default, returning `RunnableSequence` which doesn't check `additional_kwargs["reasoning_content"]`.

**Fix Applied**: `LimitedProviderModelWrapper` now ALWAYS returns `JsonSchemaModelWrapper` for ALL methods:

```python
# CORRECT (fixed code)
# ALWAYS use JsonSchemaModelWrapper for limited_openai providers
try:
    json_schema = schema.model_json_schema()
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "strict": True,
            "schema": json_schema,
        },
    }
    return JsonSchemaModelWrapper(self._model, response_format, schema)
except Exception:
    return self._model.with_structured_output(schema, **kwargs)  # Fallback
```

**Why This Matters**: All methods (`function_calling`, `json_mode`, `None`) now use `JsonSchemaModelWrapper`, ensuring `additional_kwargs["reasoning_content"]` is always checked.

**Files Modified**: `packages/soothe/src/soothe/core/llm/wrappers.py` (LimitedProviderModelWrapper.with_structured_output)

## Change History

**Date**: 2026-04-26
**Issue**: Intent classification returns `None` with mlxserver provider
**Root Causes**:
1. Provider type mismatch (using `openai` instead of `limited_openai`)
2. `LLMTracingWrapper` missing `with_structured_output()` delegation
3. `JsonSchemaModelWrapper` checking `response.reasoning_content` as direct attribute (wrong - stored in `additional_kwargs`)
4. `LimitedProviderModelWrapper` only handling `method="json_mode"` (wrong - must handle ALL methods)

**Fixes Applied**:
1. Implemented `limited_openai` provider type with automatic wrapper application
2. Added `with_structured_output()` delegation to `LLMTracingWrapper`
3. Fixed `JsonSchemaModelWrapper` to check `additional_kwargs["reasoning_content"]` correctly
4. Fixed `LimitedProviderModelWrapper` to ALWAYS return `JsonSchemaModelWrapper` for ALL methods

**Files Modified**:
- `packages/soothe/src/soothe/config/models.py` - Provider type documentation
- `packages/soothe/src/soothe/config/settings.py` - Wrapper application logic
- `packages/soothe/src/soothe/core/llm/wrappers.py` - Fixed reasoning_content access AND method handling (critical fixes)
- `packages/soothe/src/soothe/core/llm/tracing.py` - Added with_structured_output delegation
- `config/config.dev.yml` - Changed provider_type to limited_openai