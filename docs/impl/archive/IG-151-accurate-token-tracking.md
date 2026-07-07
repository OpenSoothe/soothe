# IG-151: Accurate Token Tracking for AgentLoop

**Status:** Draft
**Spec traceability:** RFC-200 (Layer 2 Agentic Goal Execution)
**Platonic phase:** Implementation (IMPL) — code + tests + verification

---

## 1. Overview

This guide implements short-term improvements for AgentLoop context tracking to replace estimation-based token counting with accurate LLM usage data:

1. **Connect LLM middleware token usage to LoopState** — Bridge LLMTracingMiddleware's actual token data to executor
2. **Make context limit configurable** — Replace hard-coded 200k with model-aware config
3. **Use tiktoken utility** — Replace `// 4` estimation with proper token counting

These improvements provide accurate context window metrics for Reason phase decisions.

---

## 2. Current Implementation (Estimation-Based)

**Location**: `src/soothe/cognition/agent_loop/executor.py` lines 110-118

```python
# Context window metrics estimation from output length
# Note: In future, extract from model response usage_metadata for accuracy
if output_length > 0 and self._config is not None:
    # Rough estimate: ~4 chars per token (varies by language/model)
    estimated_tokens = output_length // 4
    state.total_tokens_used += estimated_tokens
    # Assume 200k context limit for estimation (configurable in future)
    context_limit = 200_000
    state.context_percentage_consumed = min(1.0, state.total_tokens_used / context_limit)
```

**Key gaps**:
- Not using actual `usage_metadata` from LLM responses
- Hard-coded context limit (not model-aware)
- Character estimation unreliable across languages

---

## 3. Implementation Plan

### Phase A: Extract Token Usage from LLM Responses

**Goal**: Replace estimation with actual `usage_metadata` from AIMessage responses.

**Data flow**:
1. CoreAgent returns AIMessage with `response_metadata.token_usage`
2. LLMTracingMiddleware logs this (but not passed to executor)
3. Executor needs access to last AIMessage's token usage

**Approach**: Extract from CoreAgent output message directly.

**Files affected**:
- `src/soothe/cognition/agent_loop/executor.py` — Token extraction logic

**Implementation**:

```python
def _extract_token_usage(self, messages: list[BaseMessage]) -> dict[str, int]:
    """Extract token usage from last AIMessage response metadata.

    Args:
        messages: List of messages from CoreAgent execution

    Returns:
        Dict with prompt_tokens, completion_tokens, total_tokens (or empty if unavailable)
    """
    # Find last AIMessage with usage_metadata
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and hasattr(msg, "response_metadata"):
            metadata = msg.response_metadata
            token_usage = metadata.get("token_usage", {})
            if token_usage:
                return {
                    "prompt": token_usage.get("prompt_tokens", 0),
                    "completion": token_usage.get("completion_tokens", 0),
                    "total": token_usage.get("total_tokens", 0),
                }
    return {}
```

**Integration point**: After CoreAgent execution completes, before aggregation.

---

### Phase B: Make Context Limit Configurable

**Goal**: Replace hard-coded 200k with model-aware configuration.

**Config schema**:

```python
class AgenticLoopConfig(BaseModel):
    # Existing fields...
    max_iterations: int = Field(default=3, ge=1, le=10)
    max_subagent_tasks_per_wave: int = Field(default=2, ge=0, le=20)

    # New field
    context_window_limit: int = Field(
        default=200_000,
        ge=10_000,
        le=1_000_000,
        description="Model context window token limit for percentage tracking"
    )
```

**Model-aware defaults** (optional future enhancement):
- Claude models: 200k
- GPT-4: 128k (varies by version)
- Local models: configurable

**Files affected**:
- `src/soothe/config/models.py` — Add `context_window_limit` to `AgenticLoopConfig`
- `src/soothe/cognition/agent_loop/executor.py` — Use config value
- `config/config.yml` — Add config field
- `config/config.dev.yml` — Add dev default

---

### Phase C: Use Tiktoken for Fallback Estimation

**Goal**: When `usage_metadata` unavailable, use accurate token counting instead of `// 4`.

**Existing utility**: `src/soothe/utils/token_counting.py`

```python
def count_tokens(text: str, *, use_tiktoken: bool = True) -> int:
    """Count tokens using offline tokenizers.

    Uses cl100k_base encoding (GPT-4/Claude standard).
    Fallback to estimation: len(text) // 4.
    """
```

**Integration**: Import and use for estimation fallback.

**Files affected**:
- `src/soothe/cognition/agent_loop/executor.py` — Import and use `count_tokens()`

---

## 4. File Structure and Changes

| Area | Path | Change |
|------|------|--------|
| Config schema | `src/soothe/config/models.py` | Add `context_window_limit` field |
| Executor | `src/soothe/cognition/agent_loop/executor.py` | Extract token usage, use config limit, import tiktoken utility |
| Config template | `config/config.yml` | Add `context_window_limit: 200000` |
| Dev config | `config/config.dev.yml` | Add `context_window_limit: 200000` |
| Tests | `tests/unit/test_executor_token_tracking.py` | New test: token extraction and tracking |

---

## 5. Detailed Implementation

### 5.1 Phase A: Token Usage Extraction

**File**: `src/soothe/cognition/agent_loop/executor.py`

**Import**:
```python
from langchain_core.messages import AIMessage, BaseMessage
```

**Add method** (after `_aggregate_wave_metrics`):
```python
def _extract_token_usage(self, messages: list[BaseMessage]) -> dict[str, int]:
    """Extract token usage from last AIMessage response metadata.

    Args:
        messages: List of messages from CoreAgent execution

    Returns:
        Dict with prompt_tokens, completion_tokens, total_tokens (or empty dict if unavailable)
    """
    # Find last AIMessage with usage_metadata
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and hasattr(msg, "response_metadata"):
            metadata = msg.response_metadata
            token_usage = metadata.get("token_usage", {})
            if token_usage:
                return {
                    "prompt": token_usage.get("prompt_tokens", 0),
                    "completion": token_usage.get("completion_tokens", 0),
                    "total": token_usage.get("total_tokens", 0),
                }
    return {}
```

**Update `_aggregate_wave_metrics`**:
```python
def _aggregate_wave_metrics(
    self,
    step_results: list[StepResult],
    output: str,
    messages: list[BaseMessage],  # NEW: pass messages for token extraction
    state: LoopState,
) -> None:
    """Aggregate metrics from wave execution into LoopState."""
    # ... existing aggregation ...

    # Context window metrics with actual token usage
    token_usage = self._extract_token_usage(messages)

    if token_usage and "total" in token_usage:
        # Use actual token count from LLM response
        actual_tokens = token_usage["total"]
        state.total_tokens_used += actual_tokens
    elif output:
        # Fallback: use tiktoken for accurate estimation
        from soothe.utils.token_counting import count_tokens
        estimated_tokens = count_tokens(output)
        state.total_tokens_used += estimated_tokens

    # Use configurable context limit
    if self._config is not None:
        context_limit = self._config.agentic.context_window_limit
        state.context_percentage_consumed = min(1.0, state.total_tokens_used / context_limit)
```

---

### 5.2 Phase B: Configurable Context Limit

**File**: `src/soothe/config/models.py`

**Add to `AgenticLoopConfig`** (after line ~50):
```python
class AgenticLoopConfig(BaseModel):
    """Configuration for Layer 2 agentic goal execution loop."""

    max_iterations: int = Field(default=3, ge=1, le=10)
    max_subagent_tasks_per_wave: int = Field(default=2, ge=0, le=20)
    prior_conversation_limit: int = Field(default=10, ge=1, le=50)

    # Context window tracking
    context_window_limit: int = Field(
        default=200_000,
        ge=10_000,
        le=1_000_000,
        description="Model context window token limit for percentage calculation"
    )

    working_memory: LoopWorkingMemoryConfig = Field(default_factory=LoopWorkingMemoryConfig)
```

**File**: `config/config.yml`

**Add under `agentic` section**:
```yaml
agentic:
  enabled: true
  max_iterations: 8
  max_subagent_tasks_per_wave: 2
  prior_conversation_limit: 10
  context_window_limit: 200000  # Claude models default
  working_memory:
    enabled: true
    max_inline_chars: 4000
    max_entry_chars_before_spill: 1500
```

**File**: `config/config.dev.yml`

**Add same section**:
```yaml
agentic:
  enabled: true
  max_iterations: 3
  max_subagent_tasks_per_wave: 2
  prior_conversation_limit: 5
  context_window_limit: 200000  # Default for Claude models
  working_memory:
    enabled: true
    max_inline_chars: 4000
```

---

### 5.3 Phase C: Tiktoken Utility Integration

**File**: `src/soothe/cognition/agent_loop/executor.py`

**Add import** (at top of file):
```python
from soothe.utils.token_counting import count_tokens
```

**Use in fallback** (as shown in Phase A implementation above).

---

## 6. Testing Strategy

### Unit Tests

**Test file**: `tests/unit/test_executor_token_tracking.py`

**Test cases**:

1. **Token extraction from AIMessage**:
   - AIMessage with usage_metadata → extract correctly
   - AIMessage without usage_metadata → return empty dict
   - Mixed messages → extract from last AIMessage

2. **Configurable context limit**:
   - Default 200k → calculate percentage correctly
   - Custom 100k → calculate percentage correctly
   - Tokens exceed limit → cap at 100%

3. **Tiktoken fallback**:
   - No usage_metadata → use count_tokens()
   - Empty output → zero tokens
   - Chinese text → accurate token count (not `// 4`)

### Integration Tests

**Scenario**: Full AgentLoop iteration with token tracking

- Goal: "Write Python script"
- CoreAgent execution → AIMessage with usage_metadata
- Executor extracts tokens → updates LoopState
- Reason phase sees accurate context percentage

---

## 7. Verification

Run after implementation:

```bash
./scripts/verify_finally.sh
```

Expected:
- Formatting passes
- Linting passes (zero errors)
- All tests pass (including new token tracking tests)
- Type checking passes

---

## 8. Implementation Notes

### Token Accuracy

**Actual usage vs estimation**:
- Actual: Most accurate when available (from provider API)
- Tiktoken: Good fallback (cl100k_base encoding matches GPT-4/Claude)
- `// 4`: Avoid (inaccurate for non-English, code, whitespace)

**Why extraction works**: LangChain models populate `response_metadata.token_usage` from provider APIs (OpenAI, Anthropic, etc.).

### Context Limit Configuration

**Default 200k**: Matches Claude models (Sonnet, Opus). Adjust for other models:
- GPT-4-turbo: 128k
- GPT-4o: 128k
- Local models: User-defined

**Future enhancement**: Auto-detect from model name (requires model metadata registry).

### Backward Compatibility

**Schema addition**: New config field with default maintains compatibility.

**Existing behavior**: Estimation removed, replaced with more accurate methods.

---

## 9. Success Criteria

After implementation:

1. **Actual tokens**: Executor extracts from LLM response when available
2. **Configurable limit**: Context limit reads from config, not hard-coded
3. **Accurate fallback**: Tiktoken used when metadata unavailable
4. **Tests pass**: All new tests verify token extraction and tracking
5. **Verification passes**: `./scripts/verify_finally.sh` clean

---

## 10. Related Specifications

| RFC/IG | Relevance |
|--------|-----------|
| RFC-200 | Layer 2 metrics specification |
| IG-132 | Metrics aggregation (estimation-based, this IG improves) |
| RFC-203 | Loop working memory (context management) |

---

## 11. Changelog

**2026-04-12 (created)**:
- IG-151 initial draft
- Three phases: token extraction, config limit, tiktoken integration
- Short-term improvements to replace estimation