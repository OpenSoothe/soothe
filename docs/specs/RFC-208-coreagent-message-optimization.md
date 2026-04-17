# RFC-208: CoreAgent Message Optimization (Phase 4.2)

**RFC**: 208
**Title**: Layer 1 CoreAgent Message Optimization
**Status**: Deprecated
**Kind**: Architecture Refinement
**Created**: 2026-04-09
**Dependencies**: RFC-207, RFC-200, RFC-100, RFC-104
**Replaces**: None (refines Layer 1 message construction)
**Redirect**: Superseded by `RFC-207-agentloop-thread-context-lifecycle.md`

## Abstract

Optimize Phase 4.2 CoreAgent message construction by consolidating context projection and memories into SystemMessage, following RFC-207's SystemMessage/HumanMessage separation pattern. This improves token efficiency, LLM response quality, and architectural clarity with minimal code changes (~50 lines across 2 files).

## Motivation

### Current Issues

Phase 4.2 currently splits context information between SystemMessage and HumanMessage:

**SystemMessage** contains:
- Base prompt (complexity-based)
- Environment XML
- Workspace XML
- Thread XML (complex only)
- Protocols XML (complex only)

**HumanMessage** contains:
- Context XML (context projection entries)
- Memory XML (recalled memories)
- User query text

**Problems**:

1. **Token duplication risk**: Context in HumanMessage when it logically belongs in SystemMessage
2. **Suboptimal model attention**: Claude models weight SystemMessage differently; context in HumanMessage may not receive appropriate priority
3. **Architectural inconsistency**: Layer 2 uses RFC-207's proper separation, but Layer 1 mixes context into HumanMessage
4. **Unclear responsibilities**: Runner builds context/memory XML, middleware builds environment/workspace XML

### Proposed Solution

Consolidate all system-level context into SystemMessage, leaving HumanMessage with only the user's task/query.

---

## Specification

### Message Structure

**Before**:
```
SystemMessage: [base prompt] [ENVIRONMENT] [WORKSPACE] [THREAD] [PROTOCOLS]
HumanMessage: [context] [memory] [user query]
```

**After**:
```
SystemMessage: [base prompt] [ENVIRONMENT] [WORKSPACE] [context] [memory] [THREAD] [PROTOCOLS]
HumanMessage: [user query]
```

### Component Changes

#### 1. SystemPromptOptimizationMiddleware (Extended)

**File**: `src/soothe/core/middleware/system_prompt_optimization.py`

**New Methods**:

```python
def _build_context_section(self, projection: ContextProjection) -> str:
    """Build <context> XML for context projection entries.

    Args:
        projection: Context projection with relevance-ranked entries.

    Returns:
        XML section string with top 10 entries, 200 chars each.
    """
    entries = projection.entries[:10]
    lines = [f"- [{e.source}] {e.content[:200]}" for e in entries]
    return f"<context>\n{'\n'.join(lines)}\n</context>"

def _build_memory_section(self, memories: list[MemoryItem]) -> str:
    """Build <memory> XML for recalled memories.

    Args:
        memories: Recalled memory items from MemoryProtocol.

    Returns:
        XML section string with top 5 memories, 200 chars each.
    """
    lines = [f"- [{m.source_thread or 'unknown'}] {m.content[:200]}" for m in memories[:5]]
    return f"<memory>\n{'\n'.join(lines)}\n</memory>"
```

**Modified Method**:

```python
def _get_prompt_for_complexity(self, complexity: str, state: dict[str, Any] | None = None) -> str:
    """Get prompt with XML context sections for complexity level.

    NEW: Appends context and memory sections to SystemMessage for medium/complex queries.
    """
    # ... existing code ...

    # NEW: Context projection and memories (medium/complex only)
    if state:
        projection = state.get("context_projection")
        if projection and projection.entries:
            sections.append(self._build_context_section(projection))

        memories = state.get("recalled_memories")
        if memories:
            sections.append(self._build_memory_section(memories))

    # ... rest of method ...
```

#### 2. PhasesMixin._build_enriched_input() (Simplified)

**File**: `src/soothe/core/runner/_runner_phases.py`

**Before**:
```python
def _build_enriched_input(self, user_input, projection, memories) -> list[HumanMessage]:
    parts = []
    if projection and projection.entries:
        # Build context XML
    if memories:
        # Build memory XML
    enriched = "\n\n".join(parts) + f"\n\n{user_input}"
    return [HumanMessage(content=enriched)]
```

**After**:
```python
def _build_enriched_input(self, user_input, projection, memories) -> list[HumanMessage]:
    """Build input message with user query only.

    Context and memory now injected into SystemMessage by
    SystemPromptOptimizationMiddleware.
    """
    return [HumanMessage(content=user_input)]
```

### Request State (No Changes)

Context projection and memories are already available in `request.state`:
- `state.context_projection` populated by `_pre_stream_independent()`
- `state.recalled_memories` populated by `_pre_stream_independent()`
- Middleware reads from `request.state.get("context_projection")` and `request.state.get("recalled_memories")`

---

## Implementation

### Files Modified

1. **`src/soothe/core/middleware/system_prompt_optimization.py`** (~35 lines added)
   - Add `_build_context_section()` method
   - Add `_build_memory_section()` method
   - Extend `_get_prompt_for_complexity()` to append context/memory

2. **`src/soothe/core/runner/_runner_phases.py`** (~12 lines simplified)
   - Simplify `_build_enriched_input()` to return clean HumanMessage

3. **`tests/unit/core/middleware/test_system_prompt_optimization.py`** (~90 lines added)
   - Test context/memory appear in SystemMessage
   - Test HumanMessage is simplified
   - Test edge cases (empty projections, chitchat, etc.)

### Testing

**Unit Tests**:
- Context projection appears in SystemMessage
- Memories appear in SystemMessage
- HumanMessage contains only user query
- Chitchat skips context/memory injection
- Empty projections/memories handled gracefully
- Truncation limits maintained

**Integration Tests**:
- All existing tests pass unchanged
- LLM responses identical in structure and content

**Verification**:
```bash
./scripts/verify_finally.sh  # Format, lint, 900+ tests
```

---

## Edge Cases

| Case | Handling |
|------|----------|
| Empty context projection | Check `if projection and projection.entries` before building |
| Empty memories list | Check `if memories` before building |
| Chitchat complexity | Early return before context/memory injection |
| Missing state fields | Use `state.get()` with None default |
| Large context/memory | Truncate to 10 entries/200 chars (context), 5/200 (memory) |

---

## Benefits

### Token Efficiency
✅ Eliminated duplication: Context/memory appear once in SystemMessage
✅ Cleaner message structure: No redundant information across message types

### LLM Response Quality
✅ Better model attention: Context receives SystemMessage weight
✅ Clear hierarchy: System context vs user task distinction

### Architectural Clarity
✅ RFC-207 alignment: Same SystemMessage/HumanMessage separation as Layer 2
✅ Single responsibility: Middleware owns all system prompt construction
✅ Simplified runner: `_build_enriched_input()` becomes trivial

### Minimal Disruption
✅ 2 files modified: ~50 lines changed total
✅ No new abstractions: Extends existing middleware pattern
✅ Backward compatible: Can revert if needed

---

## Success Criteria

1. ✅ Context projection XML appears in SystemMessage
2. ✅ Memories XML appears in SystemMessage
3. ✅ HumanMessage contains only user query text
4. ✅ All 900+ tests pass
5. ✅ Linting passes with zero errors
6. ✅ Behavior identical (LLM responses same structure)

---

## Related Specifications

- **RFC-207**: SystemMessage/HumanMessage Separation (Layer 2)
- **RFC-200**: Layer 2 Agentic Goal Execution
- **RFC-100**: Layer 1 CoreAgent Runtime
- **RFC-104**: Dynamic System Context

---

## Changelog

**2026-04-09 (created)**:
- Initial RFC for CoreAgent message optimization
- Consolidates context/memory into SystemMessage
- Aligns with RFC-207 pattern
- Minimal code changes (~50 lines)