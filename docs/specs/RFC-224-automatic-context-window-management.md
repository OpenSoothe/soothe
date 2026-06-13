# RFC-224: Automatic Context Window Management

**RFC**: 224
**Title**: Automatic Context Window Management
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-05-27
**Dependencies**: RFC-223, RFC-201, RFC-214
**Related**: RFC-216 (Multithread Lifecycle), RFC-218 (Checkpoint Tree)

---

## Abstract

This RFC extends RFC-223 thread inheritance with automatic context window management. When a thread's estimated token count exceeds a configurable threshold (default 80% of `context_window_limit`), in-place compaction is triggered using deepagents SummarizationMiddleware. This enables long-running goals to continue autonomously without hitting model context limits, preserving key conversation history while evicting verbose tool outputs.

---

## Problem Statement

### Current Behavior

StrangeLoop tracks `total_tokens_used` and `context_percentage_consumed` in `LoopState`, but these metrics are informational only. When the context window fills:

1. LLM calls fail with `ContextOverflowError` or provider-specific limit errors
2. Goal execution halts or produces degraded reasoning quality
3. No automatic recovery mechanism exists

### Goals

1. **Automatic compaction**: Trigger in-place context reduction when threshold exceeded
2. **Threshold-based triggering**: Use relative percentage for model adaptability
3. **Seamless continuation**: Goal execution continues with compacted context
4. **Observability**: Emit events for TUI/daemon visibility when compaction occurs

---

## Configuration

### New Fields in StrangeLoopConfig

```python
class StrangeLoopConfig(BaseModel):
    # Existing fields...
    context_window_limit: int = Field(default=200000)

    # NEW: Context overflow threshold
    context_overflow_threshold_pct: float = Field(
        default=0.80,
        ge=0.5,
        le=0.95,
        description=(
            "Percentage of context_window_limit at which automatic "
            "in-place compaction is triggered."
        ),
    )

    # NEW: Target percentage after compaction
    context_compaction_target_pct: float = Field(
        default=0.60,
        ge=0.30,
        le=0.70,
        description=(
            "Target context percentage after compaction. "
            "Provides buffer for subsequent execute waves."
        ),
    )

    # NEW: Enable step thread context checking
    step_context_check_enabled: bool = Field(
        default=False,
        description=(
            "Check context on step threads. Usually unnecessary; "
            "step threads are short-lived."
        ),
    )
```

### YAML Configuration

```yaml
agent:
  loop:
    context_window_limit: 200000
    context_overflow_threshold_pct: 0.80  # Trigger at 160k tokens
    context_compaction_target_pct: 0.60   # Compact to 120k tokens
    step_context_check_enabled: false
```

---

## Architecture

### Component Interaction

```
┌─────────────────────────────────────────────────────────────────────┐
│  Orchestrator (plan-assess → plan-generate → execute)               │
│  • After each execute wave, call ContextWindowManager                │
│  • Emit ContextCompactionEvent for observability                     │
│  • Continue to plan-assess with compacted context                    │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ check_and_compact_if_needed()
┌─────────────────────────────────────────────────────────────────────┐
│  ContextWindowManager (NEW)                                          │
│  • estimate_checkpoint_tokens(thread_id) → int                       │
│  • should_compact(estimated_tokens) → bool                           │
│  • compact_checkpoint_inplace(thread_id, state) → Result | None      │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ compact_checkpoint_inplace()
┌─────────────────────────────────────────────────────────────────────┐
│  deepagents SummarizationMiddleware                                  │
│  • Summarizes message history to target token limit                  │
│  • Returns compacted messages + summary                              │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ aupdate()
┌─────────────────────────────────────────────────────────────────────┐
│  LangGraph Checkpointer                                              │
│  • aget_tuple(thread_id) → checkpoint                                │
│  • aupdate(thread_id, {"messages": compacted}) → updated             │
└─────────────────────────────────────────────────────────────────────┘
```

### Position in Existing Flow

```
Orchestrator.run_goal_iteration()
  → execute_phase(decision, state)
     → executor.execute() → yields events, updates state
     → ContextWindowManager.check_and_compact_if_needed()  # NEW
        → if compaction: emit ContextCompactionEvent
     → _aggregate_wave_metrics() → updates state.total_tokens_used
  → plan_assess_phase(state) → uses compacted context
  → plan_generate_phase(state) → fresh plan with clean context
```

---

## Components

### ContextWindowManager (NEW)

**Location**: `packages/soothe/src/soothe/core/loop/engine/context_window_manager.py`

**Interface**:

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ContextCompactionResult:
    """Result from automatic context compaction."""
    thread_id: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    summary_preview: str | None = None


class ContextWindowManager:
    """Manages automatic context window compaction for StrangeLoop threads."""

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver | None,
        config: SootheConfig | None,
    ) -> None:
        self._checkpointer = checkpointer
        self._config = config

    def _context_limit(self) -> int:
        """Get context_window_limit from config."""

    def _threshold_pct(self) -> float:
        """Get overflow threshold percentage from config."""

    def _target_pct(self) -> float:
        """Get compaction target percentage from config."""

    async def estimate_checkpoint_tokens(self, thread_id: str) -> int:
        """Estimate token count from checkpoint messages (async)."""

    def estimate_checkpoint_tokens_sync(self, checkpoint: Checkpoint) -> int:
        """Estimate token count from pre-loaded checkpoint (sync helper)."""

    def should_compact(self, estimated_tokens: int) -> bool:
        """Check if estimated tokens exceed threshold percentage."""

    async def compact_checkpoint_inplace(
        self,
        thread_id: str,
        state: LoopState,
    ) -> ContextCompactionResult | None:
        """Trigger in-place compaction via deepagents middleware."""

    async def check_and_compact_if_needed(
        self,
        thread_id: str,
        state: LoopState,
    ) -> ContextCompactionResult | None:
        """Full flow: estimate → check → compact if needed."""
```

### Token Estimation

Token estimation counts tokens in checkpoint message content using tiktoken:

```python
def estimate_checkpoint_tokens_sync(self, checkpoint: Checkpoint) -> int:
    """Estimate token count from pre-loaded checkpoint."""
    from soothe.utils.token_counting import count_tokens

    messages = checkpoint.channel_values.get("messages", [])
    total = 0
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    total += count_tokens(block["text"])
                elif isinstance(block, str):
                    total += count_tokens(block)
    return total
```

**Note**: Estimation covers message content only, not tool call arguments or channel metadata. Message content is the dominant factor.

### Compaction Implementation

```python
async def compact_checkpoint_inplace(
    self,
    thread_id: str,
    state: LoopState,
) -> ContextCompactionResult | None:
    """Trigger in-place compaction."""
    if self._checkpointer is None:
        return None

    checkpoint_tuple = await self._checkpointer.aget_tuple(thread_id)
    if checkpoint_tuple is None:
        return None

    checkpoint = checkpoint_tuple.checkpoint
    messages = checkpoint.channel_values.get("messages", [])
    original_tokens = self.estimate_checkpoint_tokens_sync(checkpoint)

    if original_tokens == 0:
        return None

    target_tokens = int(self._context_limit() * self._target_pct())

    # Use deepagents summarization middleware
    middleware = SummarizationMiddleware(max_tokens=target_tokens)
    compacted_messages, summary = await middleware.summarize(messages)

    # Update checkpoint in-place
    await self._checkpointer.aupdate(thread_id, {"messages": compacted_messages})

    new_tokens = await self.estimate_checkpoint_tokens(thread_id)

    # Update LoopState metrics
    state.total_tokens_used = new_tokens
    state.context_percentage_consumed = min(1.0, new_tokens / self._context_limit())

    return ContextCompactionResult(
        thread_id=thread_id,
        tokens_before=original_tokens,
        tokens_after=new_tokens,
        messages_removed=len(messages) - len(compacted_messages),
        summary_preview=(summary[:200] if summary else None),
    )
```

---

## Event Definition

```python
class ContextCompactionEvent(SootheEvent):
    """Event emitted when automatic context compaction occurs."""

    type: str = "soothe.loop.context_compaction"
    thread_id: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    summary_preview: str | None = None


register_event(
    ContextCompactionEvent,
    summary_template="Context compacted: {tokens_before} → {tokens_after} tokens",
)
```

---

## Step Thread Handling

Step threads (`{loop_id}__step_{step_id}`) are typically short-lived (one execute wave). Context overflow is unlikely but possible for long-running subagent tasks.

| Thread Type | Checking | Compaction Action |
|-------------|----------|-------------------|
| Main thread (`loop_id`) | Always | In-place after execute wave |
| Step thread | Optional (`step_context_check_enabled`) | Compact in-place if enabled |

**Default**: Step thread checking disabled. Enable for long-running subagent workflows.

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| Checkpointer unavailable | Skip, return None, log debug |
| Checkpoint empty | Return 0 tokens, no compaction |
| SummarizationMiddleware fails | Log warning, graceful degradation |
| Token estimation fails | Use fallback (chars // 4) |
| Compaction insufficient | Retry with 50% target, proceed anyway |

---

## Design Decisions

1. **Compaction timing**: After execute wave, before plan-assess. Maximum context accumulation after tool execution.

2. **Threshold default (80%)**: Leaves buffer for plan-assess LLM response (10-20%).

3. **Target after compaction (60%)**: Room for 2-3 execute waves before next compaction. Prevents thrashing.

4. **Step thread checking disabled**: Short-lived threads; overhead not worth it.

5. **Fast model for summarization**: Compaction is overhead; cheaper and faster.

6. **In-place compaction over thread fork**: Preserves history in compacted form.

---

## Testing Strategy

### Unit Tests

- `test_estimate_checkpoint_tokens_empty_returns_0()`
- `test_estimate_checkpoint_tokens_sync_counts_messages()`
- `test_should_compact_below_threshold_returns_false()`
- `test_should_compact_at_threshold_returns_true()`
- `test_compact_checkpoint_inplace_reduces_tokens()`
- `test_compact_checkpoint_inplace_updates_state()`
- `test_compact_checkpoint_inplace_no_checkpointer_returns_none()`
- `test_check_and_compact_if_needed_skips_when_below_threshold()`
- `test_check_and_compact_if_needed_triggers_when_above_threshold()`

### Integration Tests

- `test_main_thread_compaction_after_execute_wave()`
- `test_compaction_preserves_goal_state()`
- `test_compaction_event_emitted()`
- `test_compaction_with_rfc223_step_threads()`

---

## Migration Path

1. Add configuration fields to `StrangeLoopConfig`
2. Implement `ContextWindowManager` component
3. Integrate deepagents SummarizationMiddleware API
4. Add orchestrator integration point
5. Register `ContextCompactionEvent`
6. Unit and integration tests
7. Update config templates

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Summarization loses context | Target 60% conservatively; keep recent messages |
| Compaction latency | Use fast model; emit progress event |
| Token estimation inaccurate | Use tiktoken; document limitations |
| Compaction fails | Graceful degradation; proceed anyway |
| Thrashing | 60% target leaves buffer |

---

## References

- RFC-223: Thread Inheritance with LangGraph Checkpoint Forking
- RFC-201: StrangeLoop Plan-Execute Loop Architecture
- RFC-214: Unified Message Ledger
- deepagents SummarizationMiddleware

---

## Changelog

### 2026-05-27 (Draft)
- Initial RFC draft extending RFC-223
- ContextWindowManager component specification
- Configuration schema with threshold/target percentages
- Integration point after execute wave
- Event definition for observability