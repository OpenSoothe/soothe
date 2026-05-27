# Automatic Context Window Thread Management Design Draft

**Date**: 2026-05-27
**Status**: Draft
**Related**: RFC-223 (Thread Inheritance), RFC-201 (AgentLoop Architecture)
**Author**: Design exploration via Platonic Brainstorming

---

## Abstract

This design extends RFC-223 thread inheritance with automatic context window management. When a thread's estimated token count exceeds a configurable threshold (default 80% of context_window_limit), in-place compaction is triggered using deepagents SummarizationMiddleware. This enables long-running goals to continue autonomously without hitting model context limits, preserving key conversation history while evicting verbose tool outputs.

---

## Problem Statement

### Current Behavior

AgentLoop tracks `total_tokens_used` and `context_percentage_consumed` in `LoopState`, but these metrics are informational only. When the context window fills:

1. LLM calls fail with `ContextOverflowError` or provider-specific limit errors
2. Goal execution halts or produces degraded reasoning quality
3. No automatic recovery mechanism exists

### Goals

1. **Automatic compaction**: Trigger in-place context reduction when threshold exceeded
2. **Threshold-based triggering**: Use relative percentage (e.g., 80%) for model adaptability
3. **Seamless continuation**: Goal execution continues with compacted context
4. **Observability**: Emit events for TUI/daemon visibility when compaction occurs

---

## Configuration

### New Fields in AgentLoopConfig

```python
class AgentLoopConfig(BaseModel):
    # Existing fields...
    context_window_limit: int = Field(default=200000, description="Model context capacity")

    # NEW: Context overflow threshold
    context_overflow_threshold_pct: float = Field(
        default=0.80,
        ge=0.5,
        le=0.95,
        description=(
            "Percentage of context_window_limit at which automatic "
            "in-place compaction is triggered (0.80 = 80%)."
        ),
    )

    # NEW: Target percentage after compaction
    context_compaction_target_pct: float = Field(
        default=0.60,
        ge=0.30,
        le=0.70,
        description=(
            "Target context percentage after compaction (0.60 = 60%). "
            "Provides buffer for subsequent execute waves."
        ),
    )

    # NEW: Enable step thread context checking (default off)
    step_context_check_enabled: bool = Field(
        default=False,
        description=(
            "Check context on step threads (loop_id__step_{step_id}). "
            "Usually unnecessary; step threads are short-lived."
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
    step_context_check_enabled: false     # Step threads usually short-lived
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
│  • check_and_compact_if_needed(thread_id, state) → Result | None     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ compact_checkpoint_inplace()
┌─────────────────────────────────────────────────────────────────────┐
│  deepagents SummarizationMiddleware                                  │
│  • Summarizes message history to target token limit                  │
│  • Preserves key AIMessage reasoning and recent tool outputs         │
│  • Returns compacted messages + summary                              │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ aupdate()
┌─────────────────────────────────────────────────────────────────────┐
│  LangGraph Checkpointer                                              │
│  • aget_tuple(thread_id) → current checkpoint                        │
│  • aupdate(thread_id, {"messages": compacted}) → updated checkpoint  │
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
  → plan_assess_phase(state) → uses compacted context for reasoning
  → plan_generate_phase(state) → fresh plan with clean context
```

---

## Components

### ContextWindowManager (NEW)

**Location**: `packages/soothe/src/soothe/core/loop/engine/context_window_manager.py`

**Interface**:

```python
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint
    from soothe.config import SootheConfig
    from soothe.core.loop.state.schemas import LoopState


@dataclass(frozen=True, slots=True)
class ContextCompactionResult:
    """Result from automatic context compaction."""
    thread_id: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    summary_preview: str | None = None


class ContextWindowManager:
    """Manages automatic context window compaction for AgentLoop threads.

    RFC-223 extension: After execute waves, check estimated context size
    and trigger in-place summarization via deepagents middleware when
    threshold exceeded.
    """

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver | None,
        config: SootheConfig | None,
    ) -> None:
        """Initialize ContextWindowManager.

        Args:
            checkpointer: LangGraph checkpointer for checkpoint access.
            config: Soothe config for threshold and limit values.
        """
        self._checkpointer = checkpointer
        self._config = config

    def _context_limit(self) -> int:
        """Get context_window_limit from config."""
        if self._config is None:
            return 200_000  # Default fallback
        return self._config.agent.loop.context_window_limit

    def _threshold_pct(self) -> float:
        """Get overflow threshold percentage from config."""
        if self._config is None:
            return 0.80  # Default fallback
        return self._config.agent.loop.context_overflow_threshold_pct

    def _target_pct(self) -> float:
        """Get compaction target percentage from config."""
        if self._config is None:
            return 0.60  # Default fallback
        return self._config.agent.loop.context_compaction_target_pct

    async def estimate_checkpoint_tokens(
        self,
        thread_id: str,
    ) -> int:
        """Estimate token count from checkpoint messages (async).

        Fetches checkpoint via aget_tuple and counts tokens in messages.
        Uses tiktoken for accuracy with fallback estimation.
        Returns 0 if checkpoint unavailable or checkpointer not set.

        Args:
            thread_id: Thread to estimate.

        Returns:
            Estimated token count in checkpoint messages.
        """
        ...

    def estimate_checkpoint_tokens_sync(
        self,
        checkpoint: Checkpoint,
    ) -> int:
        """Estimate token count from pre-loaded checkpoint (sync helper).

        Used internally when checkpoint is already loaded, avoiding
        redundant async call.

        Args:
            checkpoint: Pre-loaded checkpoint with channel_values.

        Returns:
            Estimated token count in checkpoint messages.
        """
        ...

    def should_compact(self, estimated_tokens: int) -> bool:
        """Check if estimated tokens exceed threshold percentage.

        Args:
            estimated_tokens: Current estimated token count.

        Returns:
            True if compaction should be triggered.
        """
        threshold = int(self._context_limit() * self._threshold_pct())
        return estimated_tokens >= threshold

    async def compact_checkpoint_inplace(
        self,
        thread_id: str,
        state: LoopState,
    ) -> ContextCompactionResult | None:
        """Trigger in-place compaction via deepagents SummarizationMiddleware.

        Args:
            thread_id: Thread to compact.
            state: LoopState to update with new metrics.

        Returns:
            Compaction result with before/after metrics, or None on failure.
        """
        ...

    async def check_and_compact_if_needed(
        self,
        thread_id: str,
        state: LoopState,
    ) -> ContextCompactionResult | None:
        """Full flow: estimate → check → compact if needed.

        Called after execute wave completes.

        Args:
            thread_id: Thread to check.
            state: LoopState to update.

        Returns:
            Compaction result if triggered, None otherwise.
        """
        ...
```

### Token Estimation Implementation

```python
async def estimate_checkpoint_tokens(self, thread_id: str) -> int:
    """Estimate token count from checkpoint messages (async)."""
    from soothe.utils.token_counting import count_tokens

    if self._checkpointer is None:
        return 0

    checkpoint_tuple = await self._checkpointer.aget_tuple(thread_id)
    if checkpoint_tuple is None:
        return 0

    checkpoint = checkpoint_tuple.checkpoint
    return self.estimate_checkpoint_tokens_sync(checkpoint)


def estimate_checkpoint_tokens_sync(self, checkpoint: Checkpoint) -> int:
    """Estimate token count from pre-loaded checkpoint (sync helper)."""
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
                # Skip non-text blocks (images, etc.)
    return total
```

### Compaction Implementation

```python
async def compact_checkpoint_inplace(
    self,
    thread_id: str,
    state: LoopState,
) -> ContextCompactionResult | None:
    """Trigger in-place compaction."""
    import logging

    from deepagents.middleware.summarization import SummarizationMiddleware

    logger = logging.getLogger(__name__)

    if self._checkpointer is None:
        logger.debug("[ContextWindow] No checkpointer, skipping compaction")
        return None

    try:
        # Get current checkpoint
        checkpoint_tuple = await self._checkpointer.aget_tuple(thread_id)
        if checkpoint_tuple is None:
            return None

        checkpoint = checkpoint_tuple.checkpoint
        messages = checkpoint.channel_values.get("messages", [])
        original_tokens = self.estimate_checkpoint_tokens_sync(checkpoint)

        if original_tokens == 0:
            return None

        # Target token limit after compaction
        target_tokens = int(self._context_limit() * self._target_pct())

        # Use deepagents summarization middleware
        # Note: Exact API to be verified during implementation
        middleware = SummarizationMiddleware(
            max_tokens=target_tokens,
        )

        # Apply summarization
        compacted_messages, summary = await middleware.summarize(messages)

        # Update checkpoint in-place
        await self._checkpointer.aupdate(
            thread_id,
            {"messages": compacted_messages},
        )

        # Estimate new token count (async fetch of updated checkpoint)
        new_tokens = await self.estimate_checkpoint_tokens(thread_id)

        # Update LoopState metrics
        state.total_tokens_used = new_tokens
        state.context_percentage_consumed = min(
            1.0,
            new_tokens / self._context_limit()
        )

        logger.info(
            "[ContextWindow] Compacted thread %s: %d → %d tokens (%d messages removed)",
            thread_id,
            original_tokens,
            new_tokens,
            len(messages) - len(compacted_messages),
        )

        return ContextCompactionResult(
            thread_id=thread_id,
            tokens_before=original_tokens,
            tokens_after=new_tokens,
            messages_removed=len(messages) - len(compacted_messages),
            summary_preview=(summary[:200] if summary else None),
        )

    except Exception:
        logger.warning(
            "[ContextWindow] Compaction failed for thread %s",
            thread_id,
            exc_info=True,
        )
        return None
```

### Orchestrator Integration

```python
# In orchestrator (AgentLoop orchestrator node)
async def _execute_phase(...) -> AsyncGenerator:
    # Execute steps (existing flow)
    async for item in executor.execute(decision, state):
        yield item

    # NEW: Check context after execute wave
    context_manager = ContextWindowManager(self._checkpointer, self._config)
    compaction_result = await context_manager.check_and_compact_if_needed(
        thread_id=state.thread_id,
        state=state,
    )
    if compaction_result:
        # Emit event for observability
        yield ContextCompactionEvent(
            thread_id=compaction_result.thread_id,
            tokens_before=compaction_result.tokens_before,
            tokens_after=compaction_result.tokens_after,
            messages_removed=compaction_result.messages_removed,
        )
```

---

## Event Definition

```python
# In soothe/core/loop/events.py or appropriate location
from soothe.core.event_catalog import register_event
from soothe.core.base_events import SootheEvent


class ContextCompactionEvent(SootheEvent):
    """Event emitted when automatic context compaction occurs.

    Indicates thread context was compacted to stay within configured threshold.
    """

    type: str = "soothe.loop.context_compaction"
    thread_id: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    summary_preview: str | None = None


# Register in event_catalog.py
register_event(
    ContextCompactionEvent,
    summary_template="Context compacted: {tokens_before} → {tokens_after} tokens",
)
```

---

## Step Thread Handling

Step threads (`{loop_id}__step_{step_id}`) are typically short-lived (one execute wave). Context overflow is unlikely but possible for long-running subagent tasks.

**Default behavior**: Step thread context checking disabled (`step_context_check_enabled: false`)

**If enabled**: After step completes, check estimated tokens. If exceeded, compact in-place before next step in dependency chain.

```python
# In Executor._execute_step_collecting_events()
if self._config.agent.loop.step_context_check_enabled:
    step_thread_id = configurable["thread_id"]
    context_manager = ContextWindowManager(self._checkpointer, self._config)
    estimated = await context_manager.estimate_checkpoint_tokens(step_thread_id)
    if context_manager.should_compact(estimated):
        await context_manager.compact_checkpoint_inplace(step_thread_id, state)
```

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| Checkpointer unavailable | Skip estimation, return None, log debug |
| Checkpoint has no messages | Return 0 tokens, no compaction needed |
| SummarizationMiddleware fails | Log warning, graceful degradation |
| Token estimation fails | Use fallback estimation (chars // 4) |
| Compaction insufficient (still > threshold) | Retry with lower target (50%), proceed anyway |
| Summarization model unavailable | Use fast model role as fallback |

```python
async def check_and_compact_if_needed(self, thread_id: str, state: LoopState):
    try:
        estimated = await self.estimate_checkpoint_tokens(thread_id)
        if not self.should_compact(estimated):
            return None

        result = await self.compact_checkpoint_inplace(thread_id, state)

        # Check if compaction insufficient
        if result and self.should_compact(result.tokens_after):
            logger.warning(
                "[ContextWindow] Compaction insufficient (%d > threshold); retrying",
                result.tokens_after,
            )
            # Retry with lower target
            self._target_pct_override = 0.50
            result = await self.compact_checkpoint_inplace(thread_id, state)

        return result
    except Exception:
        logger.warning("[ContextWindow] Compaction check failed", exc_info=True)
        return None
```

---

## Testing Strategy

### Unit Tests (ContextWindowManager)

- `test_estimate_checkpoint_tokens_empty_returns_0()`
- `test_estimate_checkpoint_tokens_sync_counts_messages()`
- `test_should_compact_below_threshold_returns_false()`
- `test_should_compact_at_threshold_returns_true()`
- `test_compact_checkpoint_inplace_reduces_tokens()`
- `test_compact_checkpoint_inplace_updates_state()`
- `test_compact_checkpoint_inplace_no_checkpointer_returns_none()`
- `test_compact_checkpoint_inplace_failure_returns_none()`
- `test_check_and_compact_if_needed_skips_when_below_threshold()`
- `test_check_and_compact_if_needed_triggers_when_above_threshold()`

### Integration Tests

- `test_main_thread_compaction_after_execute_wave()`
- `test_compaction_preserves_goal_state()`
- `test_compaction_event_emitted()`
- `test_compaction_with_rfc223_step_threads()`
- `test_multiple_compactions_over_iterations()`

### Performance Tests

- `test_token_estimation_1000_messages_under_100ms()`
- `test_compaction_typical_checkpoint_under_5s()`

---

## Migration Path

1. **Phase 1**: Add configuration fields to `AgentLoopConfig`
2. **Phase 2**: Implement `ContextWindowManager` component
3. **Phase 3**: Research and integrate deepagents SummarizationMiddleware API
4. **Phase 4**: Add orchestrator integration point
5. **Phase 5**: Register `ContextCompactionEvent` in event catalog
6. **Phase 6**: Unit and integration tests
7. **Phase 7**: Update config templates and documentation

---

## Design Decisions

1. **Compaction timing**: After execute wave, before plan-assess. Reason: Maximum context accumulation after tool execution; plan-assess needs clean context for accurate reasoning.

2. **Threshold default (80%)**: Leaves buffer for plan-assess LLM response (typically 10-20%). Configurable for specific use cases.

3. **Target after compaction (60%)**: Provides room for 2-3 execute waves before next compaction. Prevents compaction thrashing.

4. **Step thread checking disabled**: Step threads short-lived; compaction overhead not worth it for typical 1-5 minute steps. Enable for long-running workflows.

5. **Use fast model for summarization**: Compaction is overhead; fast model is cheaper and faster.

6. **Prefer in-place compaction over thread fork**: RFC-223 fork is for inheritance, not context management. Compaction preserves history in compacted form.

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Summarization loses critical context | Configure target conservatively (60%); keep recent messages |
| Compaction latency impacts UX | Use fast model; emit event for TUI progress indicator |
| Token estimation inaccurate | Use tiktoken; document estimation method limitations |
| Compaction fails mid-goal | Graceful degradation; proceed with degraded context |
| Repeated compactions thrash | Target 60% leaves buffer; track compaction frequency |

---

## References

- RFC-223: Thread Inheritance with LangGraph Checkpoint Forking
- RFC-201: AgentLoop Plan-Execute Loop Architecture
- deepagents SummarizationMiddleware documentation
- `soothe.utils.token_counting` module

---

## Changelog

### 2026-05-27 (Draft)
- Initial design draft from Platonic Brainstorming session
- Configuration schema for threshold and target percentages
- ContextWindowManager component specification
- Integration point after execute wave
- Event definition for observability
- Error handling and graceful degradation strategy