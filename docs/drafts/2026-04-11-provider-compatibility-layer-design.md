# Provider Compatibility Layer Design

**Date**: 2026-04-11
**Status**: Draft
**Scope**: Structured output handling + token budgeting for multi-provider support

---

## Problem Statement

### Current Issue: JSON Truncation in Structured Output

**Provider**: DashScope/Kimi (OpenAI-compatible endpoint)
**Model**: `kimi-k2.5`

**Symptoms**:
```
ValidationError: 1 validation error for ReasonResult
  Invalid JSON: EOF while parsing a string at line 1 column 2644
  [type=json_invalid, input_value='{"goal_progress":0.95,"e... Directory Structure\\n\\n', input_type=str]
```

**Root Cause**:
- Provider truncates JSON output mid-string during `with_structured_output()` invocation
- Truncation occurs at varying lengths (~1500-5000 chars)
- Current 3-tier retry + fallback mechanism fails:
  - Fallback response uses non-standard format: `<|tool_call_begin|>functions.read_file:0<|tool_call_argument_begin|>{...}<|tool_call_end|>`
  - Existing JSON extraction functions (`_strip_markdown_json_fence`, `_extract_balanced_json_object`) don't handle this format

**Impact**:
- Agent enters repetitive execution loops when Reason phase fails
- Degraded user experience for complex goals
- Provider-specific quirk affects production reliability

---

## Broader Context: Multi-Provider Challenges

Soothe supports multiple LLM providers via a unified interface (`init_chat_model`). However, providers differ in:

1. **Structured output methods**:
   - OpenAI/Anthropic: Native `with_structured_output()` (reliable)
   - DashScope/Kimi: Truncates direct structured output, requires alternative method
   - Unknown providers: Unknown reliability, need safe fallback

2. **Token budget constraints**:
   - Different providers have different context/output limits
   - Large schemas (ReasonResult with long reasoning fields) may exceed budget
   - Token budget varies by model tier (fast vs think vs default)

3. **Response formats**:
   - Standard: AIMessage with content field
   - Kimi-specific: `<|tool_calls_section_begin|>...` markers
   - Anthropic: Block-based content with tool_use blocks

4. **Streaming capabilities**: (Future consideration)
   - Some providers support partial streaming
   - Structured output may need special handling

**Design Goal**: Create extensible provider compatibility layer that handles these differences transparently, enabling Soothe to work reliably across all providers.

---

## Solution Architecture: Feature-Module Pattern with Token Budget Integration

### Core Principle: Proactive + Reactive Strategy

**Proactive (Option C - Token Budgeting)**:
- Estimate token requirements before invocation
- Simplify schema if budget insufficient
- Prevent truncation by reducing output size

**Reactive (Option A - Provider-Aware Methods)**:
- Use provider-optimal structured output method (native vs tool-based)
- Intelligent fallback pipeline when primary method fails
- Provider-specific response format handling

**Integration**: Token budgeting and structured output strategies work together:
1. Before invocation: Check budget → simplify schema if needed
2. During invocation: Use provider-optimal method (native/tool-based)
3. After failure: Fallback to manual JSON parsing

---

## Architecture Overview

### Module Structure

```
src/soothe/utils/provider_compat/
├── __init__.py                 # Public API: get_handler()
├── registry.py                 # ProviderCompatibilityRegistry
├── structured_output.py        # StructuredOutputHandler + strategies
├── token_budget.py             # TokenBudgetHandler + estimation
├── schema_simplification.py    # Schema simplification strategies
├── providers/
│   ├── __init__.py
│   ├── base.py                 # BaseProviderHandler
│   ├── dashscope.py            # DashScopeHandler (tool-based + budgeting)
│   ├── anthropic.py            # AnthropicHandler (native + budgeting)
│   ├── openai.py               # OpenAIHandler (native + budgeting)
│   └── unknown.py              # UnknownProviderHandler (fallback)
├── detection.py                # Provider detection utilities
└── exceptions.py               # CompatibilityError hierarchy
```

### Layered Strategy Pipeline

**Invocation Flow**:
```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Token Budget Check (Proactive)                               │
│    - Estimate input tokens                                       │
│    - Estimate schema output tokens                               │
│    - Check against provider limits                               │
│    - Simplify schema if over budget                              │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. Provider-Optimal Invocation (Reactive)                       │
│    - Select strategy: Native vs Tool-based                       │
│    - Invoke with structured output                               │
│    - Handle provider-specific response format                    │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Fallback Pipeline (Reactive)                                 │
│    - Retry with adjusted parameters (temperature, etc.)          │
│    - Manual JSON extraction + repair                             │
│    - Schema reconstruction from partial data                     │
└─────────────────────────────────────────────────────────────────┘
```

**Key Innovation**: Token budgeting is checked **before** invocation, preventing truncation proactively rather than reacting after failure.

---

## Component Design

### 1. Registry: Provider Feature Mapping

**Purpose**: Map providers to feature handler combinations.

**Registry Structure**:
```python
ProviderCompatibilityRegistry:
  _handlers: {
    "dashscope": {
      "structured_output": DashScopeStructuredOutputHandler,
      "token_budget": DashScopeTokenBudgetHandler,
      "schema_simplification": AdaptiveSchemaSimplifier,
    },
    "anthropic": {
      "structured_output": AnthropicStructuredOutputHandler,
      "token_budget": AnthropicTokenBudgetHandler,
      "schema_simplification": ConservativeSchemaSimplifier,  # Anthropic is reliable
    },
    "openai": {
      "structured_output": OpenAIStructuredOutputHandler,
      "token_budget": OpenAITokenBudgetHandler,
      "schema_simplification": ConservativeSchemaSimplifier,
    },
  }
  
  _default_handlers: {
    "structured_output": FallbackStructuredOutputHandler,
    "token_budget": ConservativeTokenBudgetHandler,
    "schema_simplification": MinimalSchemaSimplifier,
  }
```

**Handler Retrieval**:
```python
get_handler(provider, feature, model, config):
  - Lookup provider-specific handler class
  - Instantiate with model + config
  - Return handler instance
```

**Extensibility**: Adding a new provider requires only registering its handler classes:
```python
ProviderCompatibilityRegistry.register_provider("new_provider", {
    "structured_output": NewProviderStructuredOutputHandler,
    "token_budget": NewProviderTokenBudgetHandler,
})
```

---

### 2. TokenBudgetHandler: Proactive Size Management

**Purpose**: Estimate and manage token requirements to prevent truncation.

**Key Methods**:

#### Token Estimation

```python
estimate_input_tokens(messages: list) -> int:
  """Estimate tokens for input messages.
  
  Methods:
  1. If tiktoken available: Use cl100k_base encoding (GPT-4 family)
  2. Fallback: Char count / 4 heuristic (rough estimate)
  
  Accounts for:
  - Message metadata (role, name fields)
  - System prompts
  - Conversation history
  """
```

```python
estimate_schema_tokens(schema: type[BaseModel], example_values: dict = None) -> int:
  """Estimate tokens for structured output based on schema.
  
  Methods:
  1. Analyze field definitions (types, defaults)
  2. Use example_values if provided (more accurate)
  3. Apply field-specific heuristics:
     - reasoning: 500-2000 tokens (long text)
     - decision.steps: 50-100 tokens per step
     - status/confidence: 1-5 tokens (enum/int)
  
  Returns: Worst-case estimate (conservative)
  """
```

#### Provider Token Limits

```python
get_provider_limits(provider: str, model_name: str) -> dict:
  """Get token limits for provider/model combo.
  
  Sources:
  1. Known limits database (built-in)
  2. Config overrides (config/config.dev.yml)
  3. Heuristic defaults (8000 output tokens for unknown)
  
  Returns: {
    "context_window": int,      # Total context limit
    "max_output_tokens": int,   # Output generation limit
    "recommended_output": int,  # Safe output limit (90% of max)
  }
  """
```

**DashScope/Kimi Limits** (discovered from error patterns):
```python
DASHSCOPE_LIMITS = {
  "kimi-k2.5": {
    "context_window": 128000,
    "max_output_tokens": 8192,
    "recommended_output": 7372,  # 90% safety margin
  },
}
```

#### Budget Check & Simplification Trigger

```python
check_budget(messages, schema, provider_limits) -> BudgetCheckResult:
  """Check if invocation fits within limits.
  
  Calculation:
  input_tokens = estimate_input_tokens(messages)
  output_tokens = estimate_schema_tokens(schema)
  total_required = input_tokens + output_tokens
  
  Check:
  1. total_required <= context_window (fail: input too large)
  2. output_tokens <= recommended_output (fail: need schema simplification)
  
  Returns: {
    "fits": bool,
    "input_tokens": int,
    "output_tokens": int,
    "surplus_tokens": int,  # How much headroom
    "recommendation": "proceed" | "simplify_schema" | "reduce_input",
  }
  """
```

---

### 3. SchemaSimplificationHandler: Adaptive Schema Reduction

**Purpose**: Reduce schema complexity to fit token budget while preserving critical fields.

**Simplification Strategies**:

#### Conservative Strategy (Reliable Providers)

**Use case**: Anthropic, OpenAI (native structured output works well)

**Approach**: Minimal changes, preserve field richness.

```python
simplify(schema, budget) -> SimplifiedSchema:
  """Reduce output size by 10-20%.
  
  Tactics:
  1. Truncate expected field lengths (reasoning: 2000 → 1500 chars)
  2. Remove optional fields with None defaults
  3. Simplify nested structures (flatten decision.steps if over 5)
  
  Preserves:
  - Required fields (status, plan_action, decision.type)
  - Core validation semantics
  """
```

#### Adaptive Strategy (Problematic Providers)

**Use case**: DashScope, unknown providers (proactive prevention)

**Approach**: Aggressive simplification, prioritize critical fields.

```python
simplify(schema, budget) -> SimplifiedSchema:
  """Reduce output size by 30-50%.
  
  Tactics:
  1. Drastically shorten text fields:
     - reasoning: 2000 → 500 chars ( truncate to last sentence)
     - soothe_next_action: 150 → 50 chars
  2. Limit array lengths:
     - decision.steps: max 3 steps (force sequential planning)
  3. Remove verbose optional fields:
     - progress_detail: None (omit)
     - evidence_summary: Empty string
  
  Preserves:
  - Status determination fields (status, plan_action)
  - Minimal decision structure (type + 1-3 steps)
  """
```

#### Minimal Strategy (Unknown Providers)

**Use case**: Providers with unknown behavior, safe defaults.

**Approach**: Schema skeleton, minimum viable validation.

```python
simplify(schema, budget) -> SimplifiedSchema:
  """Reduce to essential fields only.
  
  Tactics:
  1. Keep only required fields + minimal decision
  2. Replace long text fields with placeholders
  3. Use enums instead of free text where possible
  
  Result: Schema ~30% of original size
  """
```

**Implementation**: Pydantic schema manipulation via `create_model()`:
```python
from pydantic import create_model

simplified_schema = create_model(
  "SimplifiedReasonResult",
  status=(Literal["continue", "replan", "done"], ...),
  reasoning=(str, Field(default="", max_length=500)),
  decision=(AgentDecision | None, None),
  # ... selected fields only
)
```

---

### 4. StructuredOutputHandler: Reactive Invocation Strategy

**Purpose**: Use provider-optimal method to invoke structured output, handle failures.

**Strategy Selection**:

#### NativeStrategy (OpenAI, Anthropic)

**When**: Provider has reliable `with_structured_output()` implementation.

**Method**:
```python
invoke_structured(model, messages, schema):
  structured_model = model.with_structured_output(schema)
  result = await structured_model.ainvoke(messages)
  
  # Validation already done by langchain
  return result
```

**Advantages**:
- Fast, no overhead
- Direct schema enforcement
- Reliable for OpenAI/Anthropic

#### ToolBasedStrategy (DashScope, Kimi)

**When**: Provider truncates direct structured output, but handles tool calls well.

**Method**:
```python
invoke_structured(model, messages, schema):
  # Convert schema to tool definition
  tool_def = schema_to_tool(schema)
  
  # Bind tool
  model_with_tools = model.bind_tools([tool_def])
  
  # Invoke
  response = await model_with_tools.ainvoke(messages)
  
  # Extract from tool call (handle Kimi format)
  tool_call = extract_tool_call(response, tool_def["name"])
  
  # Validate
  return schema.model_validate(tool_call["args"])
```

**Schema → Tool Conversion**:
```python
schema_to_tool(schema: type[BaseModel]) -> dict:
  json_schema = schema.model_json_schema()
  
  return {
    "type": "function",
    "function": {
      "name": schema.__name__,
      "description": schema.__doc__ or f"Output structured {schema.__name__}",
      "parameters": {
        "type": "object",
        "properties": json_schema["properties"],
        "required": json_schema.get("required", []),
      }
    }
  }
```

**Kimi Tool Call Extraction**:
```python
extract_tool_call(response, tool_name) -> dict:
  # Standard langchain format
  if hasattr(response, "tool_calls"):
    return find_tool_call_by_name(response.tool_calls, tool_name)
  
  # Kimi-specific format
  content = response.content
  if "<|tool_call_begin|>" in content:
    # Parse: <|tool_call_begin|>ToolName:0<|tool_call_argument_begin|>{json}<|tool_call_end|>
    pattern = r'<|tool_call_argument_begin|>({.*?})<|tool_call_end|>'
    match = re.search(pattern, content)
    if match:
      args = json.loads(match.group(1))
      return {"name": tool_name, "args": args}
  
  raise StructuredOutputError("Tool call not found")
```

**Advantages**:
- Avoids truncation (tool calls handled separately)
- Provider formats tool responses properly
- Works with existing langchain tool infrastructure

#### FallbackStrategy (Unknown, Last Resort)

**When**: Other strategies fail, or provider unknown.

**Method**:
```python
invoke_structured(model, messages, schema):
  # Direct invocation
  response = await model.ainvoke(messages)
  
  # Extract JSON from response
  content = extract_text_content(response)
  json_str = strip_markdown_json_fence(content)
  json_obj = extract_balanced_json_object(json_str)
  
  # Repair truncated JSON
  repaired = repair_truncated_json(json_obj)
  parsed_dict = try_parse_json_dict(repaired)
  
  # Validate
  return schema.model_validate(parsed_dict)
```

**Integration**: Uses existing functions from `llm.py` (`_strip_markdown_json_fence`, `_repair_truncated_json`, etc.)

---

### 5. Provider Handlers: Combined Feature Coordination

**Purpose**: Coordinate multiple features (budget + structured output) per provider.

**DashScopeHandler** (Example):

```python
class DashScopeStructuredOutputHandler(StructuredOutputHandler):
  """DashScope/Kimi: Tool-based strategy + proactive budgeting."""
  
  async def invoke_with_budgeting(
    self,
    messages: list,
    schema: type[BaseModel],
    max_retries: int = 3,
  ) -> BaseModel:
    """Full pipeline with budget check + simplification."""
    
    # 1. Token budget check
    budget_handler = get_handler(self._model, feature="token_budget")
    check_result = budget_handler.check_budget(messages, schema)
    
    # 2. Simplify if needed
    if check_result["recommendation"] == "simplify_schema":
      simplifier = get_handler(self._model, feature="schema_simplification")
      schema = simplifier.simplify(schema, check_result["surplus_tokens"])
      logger.info("[DashScope] Schema simplified for token budget")
    
    # 3. Use tool-based strategy (avoid truncation)
    strategy = ToolBasedStructuredOutputStrategy()
    
    # 4. Retry pipeline
    for attempt in range(max_retries):
      try:
        return await strategy.invoke_structured(self._model, messages, schema)
      except StructuredOutputError:
        if attempt == max_retries - 1:
          # Final fallback
          return await FallbackStrategy().invoke_structured(
            self._model, messages, schema
          )
```

**AnthropicHandler** (Contrast):

```python
class AnthropicStructuredOutputHandler(StructuredOutputHandler):
  """Anthropic: Native strategy + conservative budgeting."""
  
  async def invoke_with_budgeting(...):
    # 1. Budget check (Anthropic is reliable, conservative check)
    check_result = budget_handler.check_budget(messages, schema)
    
    # 2. Minimal simplification if over budget (preserve richness)
    if check_result["recommendation"] == "simplify_schema":
      schema = simplifier.simplify(schema, check_result["surplus_tokens"])
      # ConservativeStrategy reduces by only 10-20%
    
    # 3. Native strategy (fast, reliable)
    strategy = NativeStructuredOutputStrategy()
    
    # 4. Direct invocation (Anthropic doesn't need retries usually)
    return await strategy.invoke_structured(self._model, messages, schema)
```

---

### 6. Provider Detection

**Purpose**: Identify provider from model instance for handler selection.

**Detection Sources**:

```python
detect_provider(model: BaseChatModel) -> str:
  """Detect provider name with fallback methods.
  
  Priority:
  1. model._soothe_provider (attached by SootheConfig)
  2. Class name heuristics (ChatAnthropic → anthropic)
  3. Base URL inspection (dashscope.aliyuncs.com → dashscope)
  4. Model name patterns (gpt-* → openai, claude-* → anthropic)
  5. Unknown (default)
  """
  
  # Method 1: Explicit metadata
  if hasattr(model, "_soothe_provider"):
    return model._soothe_provider
  
  # Method 2: Class name
  class_name = model.__class__.__name__
  if "Anthropic" in class_name:
    return "anthropic"
  if "OpenAI" in class_name:
    return "openai"
  
  # Method 3: Base URL
  base_url = getattr(model, "base_url", "")
  if "dashscope.aliyuncs.com" in base_url:
    return "dashscope"
  
  # Method 4: Model name
  model_name = getattr(model, "model_name", getattr(model, "model", ""))
  if model_name.startswith("gpt-"):
    return "openai"
  if model_name.startswith("claude-"):
    return "anthropic"
  
  return "unknown"
```

**Integration with SootheConfig**:

```python
# In SootheConfig.create_chat_model()
model = init_chat_model(init_str, **kwargs)

# Attach provider metadata for detection
model._soothe_provider = provider_name
model._soothe_config = self  # Reference for handler access

return model
```

---

### 7. Integration Points

#### SootheConfig.create_chat_model()

**Current**: Direct `init_chat_model()` → return model

**Enhanced**: Attach compatibility metadata:

```python
def create_chat_model(self, role: str = "default") -> BaseChatModel:
  # Existing provider resolution
  provider_name, model_name = self.resolve_model(role).partition(":")
  
  # Create model
  model = init_chat_model(init_str, **kwargs)
  
  # NEW: Attach compatibility metadata
  model._soothe_provider = provider_name
  model._soothe_config = self
  
  # Cache
  self._model_cache[cache_key] = model
  return model
```

**Impact**: Minimal code change, metadata enables handler detection.

#### LLMPlanner.reason()

**Current**: Direct `with_structured_output()` + manual fallback (lines 1091-1189)

**Enhanced**: Use compatibility layer:

```python
async def reason(self, goal: str, state: LoopState, context: PlanContext) -> ReasonResult:
  messages = self._prompt_builder.build_reason_messages(goal, state, context)
  
  # NEW: Get handler
  from soothe.utils.provider_compat import get_handler
  
  handler = get_handler(
    model=self._model,
    feature="structured_output",
  )
  
  # NEW: Invoke with full pipeline (budget + strategy + fallback)
  result = await handler.invoke_with_budgeting(
    messages=messages,
    schema=ReasonResult,
    max_retries=3,
  )
  
  # Existing post-processing (evidence-based confidence, etc.)
  result.confidence = _calculate_evidence_based_confidence(state, result)
  result.goal_progress = _calculate_evidence_based_progress(state, result)
  
  return result
```

**Impact**: Replace ~100 lines of manual retry/fallback logic with handler invocation.

**Benefits**:
- Provider-agnostic code (LLMPlanner doesn't need to know about DashScope quirks)
- Token budgeting happens automatically before invocation
- Fallback logic centralized in compatibility layer

#### LLMPlanner.create_plan()

**Current**: Similar pattern, uses `with_structured_output(Plan)` (lines 874-887)

**Enhanced**: Same pattern as `reason()`:

```python
async def _create_plan_via_llm(self, goal: str, context: PlanContext) -> Plan:
  prompt = self._build_plan_prompt(goal, context)
  
  handler = get_handler(self._model, feature="structured_output")
  
  plan = await handler.invoke_with_budgeting(
    messages=[HumanMessage(content=prompt)],
    schema=Plan,
    max_retries=3,
  )
  
  return self._normalize_hints(plan)
```

---

### 8. Configuration Integration

**Token Limits Configuration** (config/config.dev.yml):

```yaml
providers:
  - name: dashscope
    provider_type: openai
    api_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: "${DASHSCOPE_API_KEY}"
    models: [kimi-k2.5]
    
    # NEW: Provider-specific limits
    token_limits:
      kimi-k2.5:
        context_window: 128000
        max_output_tokens: 8192
        recommended_output: 7372  # 90% safety margin
```

**Schema Simplification Configuration**:

```yaml
protocols:
  planner:
    routing: auto
    planner_model: think
    
    # NEW: Simplification policy
    schema_simplification:
      policy: adaptive  # conservative | adaptive | minimal
      max_reasoning_chars: 500  # Override field limits
      max_steps: 3  # Limit decision.steps
```

**Fallback to defaults if not configured**: Handlers use built-in limits database.

---

## Design Trade-offs

### Proactive vs Reactive Balance

**Proactive (Token Budgeting)**:
- ✅ Prevents truncation before it happens
- ✅ Improves success rate for large schemas
- ❌ May over-simplify for providers that don't need it (Anthropic)
- ❌ Estimation inaccuracies (tiktoken not perfect, heuristic rough)

**Mitigation**: Per-provider simplification policies:
- Anthropic: Conservative (minimal simplification)
- DashScope: Adaptive (aggressive simplification)
- Unknown: Minimal (skeleton schema)

### Strategy Selection Logic

**Current Design**: Registry maps provider → strategy.

**Trade-off**:
- ✅ Simple, predictable behavior
- ✅ Easy to configure per provider
- ❌ Static mapping, doesn't adapt to runtime behavior

**Alternative**: Dynamic strategy selection based on failure patterns:
- Start with native
- After N truncation failures, auto-switch to tool-based
- Requires runtime state tracking

**Decision**: Keep static mapping for predictability. Runtime adaptation adds complexity without clear benefit (providers don't change behavior dynamically).

### Schema Simplification Depth

**Aggressive simplification** (Adaptive strategy):
- ✅ Prevents truncation reliably
- ❌ Loss of planning richness (short reasoning, fewer steps)
- ❌ May affect agent decision quality

**Conservative simplification**:
- ✅ Preserves schema richness
- ❌ May still fail for very large schemas

**Balance**: Provider-specific policies + field prioritization:
- Critical fields preserved: status, plan_action, decision.type
- Verbose fields reduced: reasoning, soothe_next_action, progress_detail
- Optional fields omitted: evidence_summary (can be filled later)

### Testability

**Strategy pattern enables**:
- Unit test each strategy independently (mock model responses)
- Unit test simplification logic (schema → simplified schema)
- Integration test full pipeline per provider

**Testing approach**:
- Mock AIMessage responses with known truncation patterns
- Verify tool-based strategy handles Kimi format
- Verify simplification reduces size within budget
- Verify fallback reconstructs schema from partial JSON

---

## Future Extensibility

### Adding New Providers

**Steps**:
1. Create provider handler class: `NewProviderStructuredOutputHandler`
2. Implement provider-specific strategy (if needed)
3. Register in `ProviderCompatibilityRegistry`
4. Add token limits to limits database
5. Configure in `config.yml`

**Example**: Adding Groq:
```python
# providers/groq.py
class GroqStructuredOutputHandler(StructuredOutputHandler):
  async def invoke_with_budgeting(...):
    # Groq: Very fast, may truncate, use tool-based
    strategy = ToolBasedStructuredOutputStrategy()
    ...

# registry.py
ProviderCompatibilityRegistry.register_provider("groq", {
  "structured_output": GroqStructuredOutputHandler,
  "token_budget": GroqTokenBudgetHandler,
})
```

### Adding New Features

**Example**: Streaming structured output (partial results):

```
src/soothe/utils/provider_compat/
├── streaming.py            # StreamingStructuredOutputHandler
├── providers/
│   ├── anthropic.py        # Anthropic supports partial streaming
│   └── ...
```

**Registry extension**:
```python
_handlers: {
  "anthropic": {
    "structured_output": AnthropicStructuredOutputHandler,
    "streaming": AnthropicStreamingHandler,  # NEW
  },
}
```

**Usage**: Same pattern as structured_output:
```python
handler = get_handler(model, feature="streaming")
result_stream = await handler.stream_structured(messages, schema)
```

### Feature Interaction

**Potential interactions**:
- Token budgeting affects both structured output and streaming
- Schema simplification reduces streaming granularity

**Design principle**: Handlers coordinate via shared interfaces:
```python
# TokenBudgetHandler interface used by both features
class TokenBudgetHandler:
  def check_budget(messages, schema) -> BudgetCheckResult:
    ...
  def simplify_schema(schema, budget) -> SimplifiedSchema:
    ...

# Used by StructuredOutputHandler, StreamingHandler
```

---

## Performance Considerations

### Token Estimation Overhead

**Tiktoken approach**: ~1-5ms for typical messages
**Heuristic approach**: <1ms (char count / 4)

**Impact**: Minimal compared to LLM invocation (seconds)

**Optimization**: Cache budget check results for identical message sets:
```python
_budget_cache: dict[str, BudgetCheckResult] = {}

check_budget(messages, schema):
  cache_key = hash(messages) + hash(schema)
  if cache_key in _budget_cache:
    return _budget_cache[cache_key]
  
  # ... compute ...
  _budget_cache[cache_key] = result
  return result
```

### Schema Simplification Overhead

**Pydantic create_model()**: ~5-10ms for complex schema

**Impact**: Small compared to retry overhead

**Optimization**: Cache simplified schemas:
```python
_simplified_schema_cache: dict[str, type[BaseModel]] = {}

simplify(schema, budget):
  cache_key = f"{schema.__name__}:{budget}"
  if cache_key in _simplified_schema_cache:
    return _simplified_schema_cache[cache_key]
  
  # ... create model ...
  _simplified_schema_cache[cache_key] = simplified
  return simplified
```

### Handler Instantiation Overhead

**Handler creation**: <1ms (simple object instantiation)

**Impact**: Negligible

**Optimization**: Handlers created per invocation, not cached (lightweight).

---

## Migration Strategy

### Phase 1: Core Implementation (Structured Output)

**Scope**:
- Registry + StructuredOutputHandler base class
- ToolBasedStrategy + NativeStrategy + FallbackStrategy
- Provider handlers (DashScopeHandler, OpenAIHandler, AnthropicHandler, UnknownHandler)
- Provider detection utilities
- Basic `invoke_with_retries()` method (no budgeting yet)

**Integration**:
- Update `SootheConfig.create_chat_model()` (attach metadata)
- Update `LLMPlanner.reason()` (use `handler.invoke_with_retries()`)
- Update `LLMPlanner._create_plan_via_llm()` (use handler)

**Validation**:
- Unit tests for strategies
- Integration tests per provider
- Manual testing with DashScope/Kimi (verify tool-based strategy works)

### Phase 2: Token Budgeting Integration

**Scope**:
- TokenBudgetHandler + estimation methods (tiktoken + heuristic)
- SchemaSimplificationHandler + 3 simplification strategies (Conservative, Adaptive, Minimal)
- Provider limits database (DashScope limits, defaults)
- Enhanced `invoke_with_budgeting()` method (replace Phase 1's `invoke_with_retries()`)

**Integration**:
- Update provider handlers to implement `invoke_with_budgeting()`
- Update `LLMPlanner.reason()` to use budgeting variant
- Add token_limits configuration schema
- Add simplification policy configuration

**Validation**:
- Test estimation accuracy (compare tiktoken vs heuristic)
- Test simplification preserves critical fields
- Test budget check prevents truncation with large schemas

### Phase 3: Polish + Extensibility

**Scope**:
- Caching optimizations
- Telemetry (log budget checks, simplification events)
- Documentation (provider compatibility guide)
- Configuration validation

**Future**: Add streaming feature, new providers

---

## Success Criteria

### Must Have

- ✅ DashScope/Kimi structured output succeeds without truncation
- ✅ OpenAI/Anthropic behavior unchanged (no regression)
- ✅ Unknown providers use safe fallback
- ✅ All existing tests pass (LLMPlanner tests, planning tests)
- ✅ Manual testing confirms truncation issue resolved

### Should Have

- ✅ Token budgeting reduces truncation failures across providers
- ✅ Schema simplification preserves critical validation semantics
- ✅ Handler architecture extensible for new providers/features
- ✅ Configuration allows customization per deployment
- ✅ Telemetry provides visibility into compatibility layer usage

### Nice to Have

- ✅ Performance optimizations (caching)
- ✅ Dynamic strategy selection based on failure patterns
- ✅ Streaming structured output support
- ✅ Provider behavior profiling (track reliability metrics)

---

## Open Questions

### Q1: Should simplification be configurable per goal?

**Scenario**: Complex goals need rich schemas, simple goals can use minimal schemas.

**Option A**: Static policy per provider (current design)
**Option B**: Dynamic policy based on goal complexity classification

**Discussion**: Goal classification already exists (trivial/simple/medium/complex). Could map complexity → simplification depth. Adds another decision layer.

**Recommendation**: Start with static policy, explore dynamic in Phase 3.

### Q2: How to handle schema simplification validation?

**Challenge**: Simplified schema may produce valid instances but with incomplete data.

**Example**: Simplified schema has reasoning max_length=500, but original expects 2000. Model produces 500-char reasoning, passes validation, but may affect downstream logic.

**Mitigation**:
- Field priority annotation: Mark critical fields that should not be simplified
- Simplification whitelist: Explicitly list fields safe to simplify
- Downstream impact testing: Verify simplified ReasonResult doesn't break evidence accumulation

**Recommendation**: Add field priority metadata in Phase 2.

### Q3: Should token estimation use actual token counting or heuristics?

**Consideration**:
- Tiktoken: Accurate but adds dependency + overhead
- Heuristic: Fast but inaccurate for non-English content

**Hybrid approach**: Use tiktoken if available, fallback to heuristic.

**Recommendation**: Implement hybrid, make tiktoken optional dependency.

---

## References

**Related RFCs**:
- RFC-000: System Conceptual Design (protocol-driven architecture)
- RFC-200: Agentic Goal Execution (ReasonResult schema)
- RFC-603: Reasoning Quality & Progressive Actions (evidence-based confidence)

**Related Implementation Guides**:
- IG-043: Planning Unified Architecture Guide (fallback logic in LLMPlanner)

**External References**:
- langchain `with_structured_output()`: https://python.langchain.com/docs/modules/model_io/chat/structured_output
- Pydantic model manipulation: https://docs.pydantic.dev/latest/concepts/models/#dynamic-model-creation
- Tiktoken: https://github.com/openai/tiktoken

---

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2026-04-11 | Claude Sonnet 4.6 | Initial design draft |

---

## Next Steps

**After review approval**:
1. Create implementation guide in `docs/impl/`
2. Implement core registry + handlers
3. Integrate with SootheConfig + LLMPlanner
4. Write unit + integration tests
5. Validate with DashScope/Kimi provider
6. Update documentation

**Implementation scope estimate**: ~600-800 lines (handlers + registry + detection + tests)