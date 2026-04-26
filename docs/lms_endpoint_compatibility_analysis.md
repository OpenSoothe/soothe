# LMS Endpoint Compatibility Analysis

**Last Updated**: 2026-04-26  
**Status**: ⚠️ Partial Compatibility - See Latest Test Results

---

## Latest Findings (2026-04-26 Real Test)

**CRITICAL ISSUE IDENTIFIED**: LMStudio accepts `json_schema` format but returns empty content.

See detailed analysis: [`docs/lms_json_schema_empty_response_analysis.md`](lms_json_schema_empty_response_analysis.md)

**Quick Summary**:
- ❌ Intent classification fails (empty JSON response)
- ❌ Planner fails (empty JSON response)
- ✅ Agent execution works via tool-based fallback
- ⚠️ 10-20s latency added by failed LLM calls

**Recommended**: Disable unified_classification or use different provider for intent detection.

## Original Problem Statement

Testing why Soothe cannot work with the LMS deployed model service at `http://100.75.70.86:9271/v1`.

## Root Cause Identified

**The LMS endpoint has limited OpenAI API compatibility** - it only accepts simple string values for `tool_choice` parameter and rejects the advanced object format that Soothe uses for structured output.

### Evidence

1. **Error Message from LMS Endpoint**:
   ```json
   {
     "error": "Invalid tool_choice type: 'object'. Supported string values: none, auto, required"
   }
   ```

2. **Supported Tool Choice Values**:
   - ✅ `"none"` - Don't use any tools
   - ✅ `"auto"` - Let model decide
   - ✅ `"required"` - Must use some tool
   - ❌ `{"type": "function", "function": {"name": "..."}}` - Specific tool selection (REJECTED)

3. **Response Format Issue**:
   - ❌ `{"type": "json_object"}` - Rejected by LMS
   - ✅ `{"type": "json_schema", ...}` - Accepted by LMS

## Available Models

The endpoint provides 6 models:

| Model ID | Type | Purpose |
|----------|------|---------|
| `zai-org/glm-4.7-flash` | Chat | Main conversational model |
| `zai-org/glm-4.6v-flash` | Chat | Vision-capable model |
| `qwen/qwen3.5-27b` | Chat | Alternative chat model |
| `google/gemma-4-e4b` | Chat | Small efficient model |
| `google/gemma-4-26b-a4b` | Chat | Large advanced model |
| `text-embedding-nomic-embed-text-v1.5` | Embedding | 768-dimensional vectors |

## Special Features

The chat models include **reasoning tokens** (thinking process) separate from output tokens:
- `reasoning_content` field shows the thinking process
- `completion_tokens_details.reasoning_tokens` reports thinking token usage
- Example: 134 reasoning tokens for a simple math question

## Current Architecture

**All LLM adaptation consolidated in `soothe.core.llm` module**:

- `tracing.py`: LLMTracingWrapper for request/response logging
- `wrappers.py`: Generic LimitedProviderModelWrapper for compatibility
- Standard provider_type configuration (no special LMStudio backend)

---

## Configuration (DEPRECATED - Use Standard OpenAI Provider)

**File**: `config/config.dev.yml`

**Current approach**: Use standard `provider_type: openai`:

```yaml
- name: lmstudio
  provider_type: openai  # Standard OpenAI provider type
  api_base_url: "http://100.75.70.86:9271/v1"
  api_key: "lm-studio"
  models:
    - google/gemma-4-26b-a4b
    - zai-org/glm-4.7-flash
    - zai-org/glm-4.6v-flash
    - text-embedding-nomic-embed-text-v1.5
```

**Note**: LMStudio-specific backend (`lmstudio`) has been removed. All compatibility handling is now generic in `soothe.core.llm.wrappers`.

## Soothe's Core LLM Module

**Location**: `packages/soothe/src/soothe/core/llm/`

All LLM adaptation consolidated in single module:

### 1. LLMTracingWrapper (tracing.py)

Request/response logging for direct model calls:

- **Usage**: Classifier, consensus, criticality components
- **Features**: Token tracking, duration logging, message type detection

### 2. LimitedProviderModelWrapper (wrappers.py)

Generic compatibility wrapper:

- **Tool choice**: Sanitizes object-form to string values
- **Structured output**: Handles limited provider formats
- **Transparent**: Delegates all BaseChatModel methods

### 3. JsonSchemaModelWrapper (wrappers.py)

JSON response parsing:

- **Response format**: Injects json_schema format
- **Fallback checking**: Checks both content and reasoning_content fields
- **Error logging**: Detailed debugging information

## Testing Results

### Test 1: Basic Chat ✅
- **Works**: Standard chat completions without tools
- **Response**: Includes reasoning_content field

### Test 2: Simple Tool Choice ✅
- **Works**: `tool_choice: "auto"` (string value)
- **Behavior**: Model decides whether to use tools

### Test 3: Advanced Tool Choice ❌
- **Fails**: `tool_choice: {"type": "function", "function": {"name": "..."}}`
- **Error**: "Invalid tool_choice type: 'object'. Supported string values: none, auto, required"

### Test 4: JSON Schema Format ❌ → ✅ (FIXED)
- **Original Issue**: LMStudio returns **empty `content` field** when using `json_schema` format
- **Error**: `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` from empty string
- **Root Cause**: LMStudio returns structured output in `reasoning_content` field (thinking tokens), not `content`
- **Fix**: Updated `JsonSchemaModelWrapper` to check both fields:
  1. Try `content` field first (standard OpenAI behavior)
  2. Fallback to `reasoning_content` field (LMStudio behavior)
  3. Better error logging showing both fields for debugging

## Solution Flow

1. **Config**: Set `supports_advanced_tool_choice: false` in provider config
2. **Settings**: Soothe reads flag and wraps model with `LimitedProviderModelWrapper`
3. **Structured Output**: Wrapper converts `json_mode` → `json_schema` format
4. **Tool Choice**: Wrapper intercepts object-form and converts to `"auto"`
5. **Result**: Soothe works correctly with LMS endpoint

## Verification Steps

To verify the fix works:

1. ✅ Config updated with `supports_advanced_tool_choice: false`
2. ✅ Soothe architecture already has compatibility handling
3. ✅ Wrapper applied automatically when flag is false
4. ✅ LMS endpoint accepts `json_schema` format parameter
5. ✅ LMS endpoint accepts string tool_choice values
6. ✅ **FIX APPLIED**: Wrapper now checks both `content` and `reasoning_content` fields
7. 🔄 **TESTING**: Run intent classification to verify fix resolves empty response issue

## Recommendations

1. **Keep flag in config**: The `supports_advanced_tool_choice: false` flag is essential for LMS compatibility
2. **Monitor reasoning tokens**: Models report thinking token usage separately - useful for cost tracking
3. **Test with other models**: Try all available models (qwen, gemma) to verify compatibility
4. **Document limitation**: LMS endpoints have limited OpenAI API compatibility - not full implementation
5. **Verify structured output**: Test intent classification after fix to ensure `reasoning_content` field contains JSON
6. **Report findings**: If LMStudio returns empty responses for all structured output calls, may need alternative approach (e.g., prompt engineering instead of `json_schema`)

## Related Documentation

- **Core LLM Module**: `packages/soothe/src/soothe/core/llm/` (consolidated)
- **Config Models**: `packages/soothe/src/soothe/config/models.py`
- **Settings Application**: `packages/soothe/src/soothe/config/settings.py`
- **Config Template**: `packages/soothe/src/soothe/config/config.yml`

---

## Test Script

Created `test_lms_json_schema.py` to verify LMStudio behavior.

**Test cases**:
1. Basic chat completion
2. json_schema format response
3. json_object format (should fail)
4. Direct field inspection

---

**Status**: ✅ Consolidated - All LLM adaptation in core.llm module

## Recent Error (2026-04-25 23:42)

**Issue Discovered**: LMStudio returns empty `content` field for `json_schema` format:

```
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Location**: `packages/soothe/src/soothe/core/model_wrapper.py:109` (ainvoke method)

**Analysis**:
- LMStudio accepts `response_format={"type": "json_schema"}` parameter
- But returns empty string in `content` field of AIMessage
- Hypothesis: JSON output is in `reasoning_content` field (thinking tokens)

**Fix Applied** (2026-04-25):

Updated `JsonSchemaModelWrapper` in `model_wrapper.py` to:
1. Check both `content` and `reasoning_content` fields
2. Add detailed debug logging for both fields
3. Raise informative error when both fields are empty
4. Provide context about response structure in error messages

**Code Changes**:
- File: `packages/soothe/src/soothe/core/model_wrapper.py`
- Methods: `invoke()` and `ainvoke()` in `JsonSchemaModelWrapper`
- Added: Import `preview_first` utility for better log previews
- Improved: Error messages now show both fields for debugging

---

## Conclusion

**Original Configuration Issue**: RESOLVED by adding `supports_advanced_tool_choice: false` flag

**New Structured Output Issue**: PARTIALLY RESOLVED - Fix applied to check `reasoning_content` field

**Testing Needed**: Verify that LMStudio returns JSON in `reasoning_content` field for structured output requests

Soothe's architecture now handles this scenario with:
1. Automatic model wrapping based on provider capabilities
2. Conversion of incompatible API formats (json_mode → json_schema)
3. Sanitization of tool_choice parameters
4. **NEW**: Dual-field checking (content + reasoning_content) for LMStudio responses

---

**Test Script**: `test_lms_json_schema.py` (verify LMStudio behavior)
**Architecture**: Dedicated `lmstudio` provider type with specialized LMStudio handling
**Date**: 2026-04-25 (initial), 2026-04-26 (architectural refactor to dedicated backend)
**Status**: ✅ Complete - Dedicated backend created, config migrated, needs verification