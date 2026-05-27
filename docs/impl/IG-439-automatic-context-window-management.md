# IG-439: Automatic Context Window Management (RFC-224)

**IG**: 439
**Title**: Automatic Context Window Management
**RFC**: RFC-224
**Status**: Completed
**Created**: 2026-05-27
**Dependencies**: IG-438 (Thread Inheritance)

---

## Overview

Implement automatic context window management for AgentLoop threads. When estimated token count exceeds threshold (80%), trigger in-place compaction using deepagents SummarizationMiddleware.

---

## Implementation Scope

### Files to Create

| File | Purpose |
|------|---------|
| `packages/soothe/src/soothe/core/loop/engine/context_window_manager.py` | ContextWindowManager component |
| `packages/soothe/tests/unit/core/loop/engine/test_context_window_manager.py` | Unit tests |

### Files to Modify

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/config/models.py` | Add AgentLoopConfig fields |
| `packages/soothe/src/soothe/core/loop/engine/__init__.py` | Export ContextWindowManager |
| `packages/soothe/src/soothe/core/event_catalog.py` | Register ContextCompactionEvent |
| `config/config.template.yml` | Add new config options |
| `config/config.dev.yml` | Add dev defaults |

---

## Phase 1: Configuration

### 1.1 AgentLoopConfig Fields

Add to `packages/soothe/src/soothe/config/models.py` in `AgentLoopConfig`:

```python
# RFC-224: Context overflow threshold
context_overflow_threshold_pct: float = Field(
    default=0.80,
    ge=0.5,
    le=0.95,
    description=(
        "Percentage of context_window_limit at which automatic "
        "in-place compaction is triggered."
    ),
)

# RFC-224: Target percentage after compaction
context_compaction_target_pct: float = Field(
    default=0.60,
    ge=0.30,
    le=0.70,
    description=(
        "Target context percentage after compaction. "
        "Provides buffer for subsequent execute waves."
    ),
)

# RFC-224: Step thread context checking
step_context_check_enabled: bool = Field(
    default=False,
    description=(
        "Check context on step threads. Usually unnecessary; "
        "step threads are short-lived."
    ),
)
```

### 1.2 Config Templates

Add to `config/config.template.yml` under `agent.loop`:

```yaml
# RFC-224: Automatic context window management
context_overflow_threshold_pct: 0.80
context_compaction_target_pct: 0.60
step_context_check_enabled: false
```

---

## Phase 2: ContextWindowManager Component

### 2.1 Module Structure

Location: `packages/soothe/src/soothe/core/loop/engine/context_window_manager.py`

### 2.2 Key Classes

```python
@dataclass(frozen=True, slots=True)
class ContextCompactionResult:
    """Result from automatic context compaction."""
    thread_id: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    summary_preview: str | None = None


class ContextWindowManager:
    """Manages automatic context window compaction."""
```

### 2.3 Key Methods

| Method | Purpose |
|--------|---------|
| `estimate_checkpoint_tokens(thread_id)` | Async token count from checkpoint |
| `estimate_checkpoint_tokens_sync(checkpoint)` | Sync helper for pre-loaded checkpoint |
| `should_compact(estimated_tokens)` | Check threshold |
| `compact_checkpoint_inplace(thread_id, state)` | Trigger SummarizationMiddleware |
| `check_and_compact_if_needed(thread_id, state)` | Full flow |

### 2.4 Token Estimation Algorithm

1. Get checkpoint via `checkpointer.aget_tuple(thread_id)`
2. Extract messages from `checkpoint.channel_values["messages"]`
3. For each message, extract content:
   - String content: `count_tokens(content)`
   - List content: sum `count_tokens(block["text"])` for text blocks
4. Use `soothe.utils.token_counting.count_tokens()` (tiktoken with fallback)

---

## Phase 3: Event Registration

### 3.1 Event Definition

Create event in `packages/soothe/src/soothe/core/event_catalog.py`:

```python
@register_event
class ContextCompactionEvent(SootheEvent):
    """Event emitted when automatic context compaction occurs."""
    type: str = "soothe.loop.context_compaction"
    thread_id: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    summary_preview: str | None = None
```

---

## Phase 4: Orchestrator Integration

### 4.1 Integration Point

After execute wave in orchestrator, before plan-assess:

```python
# In orchestrator execute phase
context_manager = ContextWindowManager(checkpointer, config)
result = await context_manager.check_and_compact_if_needed(state.thread_id, state)
if result:
    yield ContextCompactionEvent(...)
```

### 4.2 Integration Notes

- Orchestrator already has checkpointer access (RFC-223)
- Integration deferred until IG-438 orchestrator implementation stabilizes

---

## Phase 5: Testing Strategy

### 5.1 Unit Tests

Location: `packages/soothe/tests/unit/core/loop/engine/test_context_window_manager.py`

| Test | Description |
|------|-------------|
| `test_estimate_checkpoint_tokens_empty_returns_0` | No checkpoint → 0 |
| `test_estimate_checkpoint_tokens_sync_counts_messages` | Sync estimation works |
| `test_should_compact_below_threshold_returns_false` | 70% < 80% → false |
| `test_should_compact_at_threshold_returns_true` | 80% >= 80% → true |
| `test_compact_checkpoint_inplace_no_checkpointer_returns_none` | No checkpointer → None |
| `test_compact_checkpoint_inplace_failure_returns_none` | Exception → None |
| `test_check_and_compact_if_needed_skips_below_threshold` | Below → None |
| `test_check_and_compact_if_needed_triggers_above_threshold` | Above → result |

### 5.2 Mocking Strategy

- Mock `BaseCheckpointSaver.aget_tuple` for checkpoint tests
- Mock `SummarizationMiddleware.summarize` for compaction tests
- Use `LoopState` fixtures with `total_tokens_used` tracking

---

## Implementation Checklist

- [x] Add AgentLoopConfig fields (models.py)
- [x] Update config templates
- [x] Create ContextCompactionResult dataclass
- [x] Create ContextWindowManager class
- [x] Implement estimate_checkpoint_tokens (async)
- [x] Implement estimate_checkpoint_tokens_sync (sync helper)
- [x] Implement should_compact threshold check
- [x] Implement compact_checkpoint_inplace
- [x] Implement check_and_compact_if_needed
- [x] Add ContextCompactionEvent to event catalog
- [x] Export ContextWindowManager from engine/__init__.py
- [x] Integrate with orchestrator execute_steps node
- [x] Create unit tests
- [x] Run verify_finally.sh

---

## Notes

### LLM-based Compaction (Not SummarizationMiddleware)

Initial plan was to use deepagents SummarizationMiddleware. However, SummarizationMiddleware is AgentMiddleware for model pipeline (awrap_model_call), not standalone API for checkpoint compaction.

Implementation uses direct LLM call approach:
1. Format old messages as prompt using `get_buffer_string()`
2. Call fast model via `config.create_chat_model("fast").ainvoke()`
3. Replace checkpoint messages with AIMessage summary + recent messages
4. Update checkpoint via `checkpointer.aupdate()`

This approach provides:
- Full control over summarization logic
- In-place checkpoint modification
- Configurable keep/recent message count

### Integration Point

Orchestrator integration in `execute_steps.py` after executor finishes yielding:
- Checkpointer already retrieved for Executor (RFC-223)
- Call `check_and_compact_if_needed()` after metrics aggregation
- Emit `AGENT_LOOP_CONTEXT_COMPACTED` event if compaction occurred

---

## Changelog

### 2026-05-27
- Initial IG for RFC-224
- Configuration schema defined
- Component structure outlined
- Testing strategy defined