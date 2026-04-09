# Design: CoreAgent Message Optimization (Phase 4.2)

**Author**: Claude Code (via Platonic Brainstorming)
**Date**: 2026-04-09
**Status**: Draft
**Scope**: Layer 1 CoreAgent message construction optimization
**Related**: RFC-207 (Layer 2 message separation), RFC-201 (Layer 2 execution)

---

## Executive Summary

Optimize Phase 4.2 CoreAgent message construction by consolidating context projection and memories into SystemMessage, following RFC-207's SystemMessage/HumanMessage separation pattern. This improves token efficiency, LLM response quality, and architectural clarity with minimal code changes (~50 lines across 2 files).

**Goals**:
- Token efficiency: Eliminate duplicate context/memory between SystemMessage and HumanMessage
- LLM response quality: Better model attention through proper SystemMessage weight
- Architectural clarity: Align with RFC-207 pattern (SystemMessage = context, HumanMessage = task)
- Minimal disruption: Extend existing middleware, no new abstractions

---

## Problem Statement

### Current State

Phase 4.2 currently splits context information between messages:

**SystemMessage** (via SystemPromptOptimizationMiddleware):
- Base prompt (complexity-based)
- Environment XML: `<ENVIRONMENT>...</ENVIRONMENT>`
- Workspace XML: `<WORKSPACE>...</WORKSPACE>`
- Thread XML (complex only): `<SOOTHE_THREAD>...`
- Protocols XML (complex only): `<SOOTHE_PROTOCOLS>...`
- Current date line

**HumanMessage** (via `_build_enriched_input()`):
- Context XML: `<context>...</context>` (context projection entries)
- Memory XML: `<memory>...</memory>` (recalled memories)
- User query text

### Issues

1. **Token duplication risk**: Context appears in HumanMessage when it logically belongs with other system context in SystemMessage
2. **Suboptimal model attention**: Claude models weight SystemMessage differently than HumanMessage; context in HumanMessage may not receive appropriate priority
3. **Architectural inconsistency**: Layer 2 uses RFC-207's proper separation (SystemMessage = static context, HumanMessage = dynamic task), but Layer 1 mixes context into HumanMessage
4. **Unclear responsibilities**: Runner builds context/memory XML, but middleware builds environment/workspace XML (split responsibility)

### Proposed Solution

Consolidate all system-level context (environment, workspace, context projection, memories, thread, protocols) into SystemMessage, leaving HumanMessage with only the user's task/query.

**Benefits**:
- Clear separation: SystemMessage = context, HumanMessage = user task
- Better model attention: Context receives SystemMessage weight
- Architectural alignment: Matches RFC-207 pattern
- Simplified runner: `_build_enriched_input()` becomes trivial

---

## Architecture

### Message Structure Comparison

#### Before Optimization

```
┌─────────────────────────────────────────────────────────┐
│ SystemMessage                                            │
│ - Base prompt (complexity-based)                        │
│ - <ENVIRONMENT>platform, model, knowledge_cutoff</ENVIRONMENT> │
│ - <WORKSPACE>root, git status</WORKSPACE>              │
│ - <SOOTHE_THREAD>thread_id, turns</SOOTHE_THREAD>      │
│ - <SOOTHE_PROTOCOLS>context, memory, planner</SOOTHE_PROTOCOLS> │
│ - Current date line                                     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ HumanMessage                                             │
│ - <context>                                             │
│     - [tool] file listing result...                     │
│     - [subagent] research finding...                    │
│   </context>                                            │
│ - <memory>                                              │
│     - [thread_123] previous decision...                 │
│   </memory>                                             │
│ - User query text                                       │
└─────────────────────────────────────────────────────────┘
```

#### After Optimization

```
┌─────────────────────────────────────────────────────────┐
│ SystemMessage                                            │
│ - Base prompt (complexity-based)                        │
│ - <ENVIRONMENT>platform, model, knowledge_cutoff</ENVIRONMENT> │
│ - <WORKSPACE>root, git status</WORKSPACE>              │
│ - <context> [NEW]                                       │
│     - [tool] file listing result...                     │
│     - [subagent] research finding...                    │
│   </context>                                            │
│ - <memory> [NEW]                                        │
│     - [thread_123] previous decision...                 │
│   </memory>                                             │
│ - <SOOTHE_THREAD>thread_id, turns</SOOTHE_THREAD>      │
│ - <SOOTHE_PROTOCOLS>context, memory, planner</SOOTHE_PROTOCOLS> │
│ - Current date line                                     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ HumanMessage                                             │
│ - User query text ONLY [SIMPLIFIED]                     │
└─────────────────────────────────────────────────────────┘
```

**Key Change**: Context and memory XML sections move from HumanMessage to SystemMessage, consolidating all system-level context into a single message.

---

## Components

### 1. SystemPromptOptimizationMiddleware (Extended)

**File**: `src/soothe/core/middleware/system_prompt_optimization.py`

#### New Methods

##### `_build_context_section()`

Builds `<context>` XML for context projection entries.

```python
def _build_context_section(self, projection: ContextProjection) -> str:
    """Build <context> XML for context projection entries.

    Args:
        projection: Context projection with relevance-ranked entries.

    Returns:
        XML section string with top 10 entries, 200 chars each.

    Example:
        >>> projection = ContextProjection(entries=[
        ...     ContextEntry(source="tool", content="Found 5 files", ...)
        ... ])
        >>> print(self._build_context_section(projection))
        <context>
        - [tool] Found 5 files
        </context>
    """
    entries = projection.entries[:10]
    lines = [f"- [{e.source}] {e.content[:200]}" for e in entries]
    return f"<context>\n{'\n'.join(lines)}\n</context>"
```

**Design Notes**:
- Truncates to 10 entries (same as current `_build_enriched_input()`)
- Truncates each entry to 200 chars (same as current)
- Returns empty string if no entries (checked by caller)

##### `_build_memory_section()`

Builds `<memory>` XML for recalled memories.

```python
def _build_memory_section(self, memories: list[MemoryItem]) -> str:
    """Build <memory> XML for recalled memories.

    Args:
        memories: Recalled memory items from MemoryProtocol.

    Returns:
        XML section string with top 5 memories, 200 chars each.

    Example:
        >>> memories = [MemoryItem(content="User prefers Python", ...)]
        >>> print(self._build_memory_section(memories))
        <memory>
        - [thread_123] User prefers Python
        </memory>
    """
    lines = [f"- [{m.source_thread or 'unknown'}] {m.content[:200]}" for m in memories[:5]]
    return f"<memory>\n{'\n'.join(lines)}\n</memory>"
```

**Design Notes**:
- Truncates to 5 memories (same as current)
- Truncates each memory to 200 chars (same as current)
- Returns empty string if no memories (checked by caller)

#### Modified Method: `_get_prompt_for_complexity()`

Extends existing method to append context and memory sections.

```python
def _get_prompt_for_complexity(self, complexity: str, state: dict[str, Any] | None = None) -> str:
    """Get prompt with XML context sections for complexity level.

    NEW: Appends context and memory sections to SystemMessage for medium/complex queries.

    Args:
        complexity: One of "chitchat", "medium", "complex".
        state: Request state with context information.

    Returns:
        Base prompt with appended XML sections for medium/complex.

    Message Structure:
        SystemMessage contains:
        - Base prompt core (complexity-specific)
        - ENVIRONMENT section
        - WORKSPACE section
        - CONTEXT section (NEW)
        - MEMORY section (NEW)
        - SOOTHE_THREAD section (complex only)
        - SOOTHE_PROTOCOLS section (complex only)
        - Current date line
    """
    from soothe.core.prompts.context_xml import build_context_sections_for_complexity

    base_core = self._get_base_prompt_core(complexity)
    date_line = self._current_date_line()

    # Chitchat: no context injection
    if complexity == "chitchat":
        return f"{base_core}\n\n{date_line}"

    # Build sections list
    sections = [base_core]

    # Environment, workspace, thread, protocols (existing logic)
    sections.extend(build_context_sections_for_complexity(
        config=self._config,
        complexity=complexity,
        state=state or {},
        include_workspace_extras=False,
    ))

    # NEW: Context projection (medium/complex only)
    if state:
        projection = state.get("context_projection")
        if projection and projection.entries:
            sections.append(self._build_context_section(projection))

        # NEW: Recalled memories (medium/complex only)
        memories = state.get("recalled_memories")
        if memories:
            sections.append(self._build_memory_section(memories))

    sections.append(date_line)
    return "\n\n".join(sections)
```

**Design Rationale**:
- Context/memory treated same as environment/workspace (system-level context)
- Conditional injection (medium/complex only) matches existing pattern for workspace
- Reuses existing XML format for consistency
- Graceful degradation: checks `if projection and projection.entries` before building

---

### 2. PhasesMixin._build_enriched_input() (Simplified)

**File**: `src/soothe/core/runner/_runner_phases.py`

#### Before (Current)

```python
def _build_enriched_input(
    self,
    user_input: str,
    projection: ContextProjection | None,
    memories: list[MemoryItem],
) -> list[HumanMessage]:
    """Build the enriched input messages with context and memories."""
    parts: list[str] = []

    if projection and projection.entries:
        context_text = "\n".join(f"- [{e.source}] {e.content[:200]}" for e in projection.entries[:10])
        parts.append(f"<context>\n{context_text}\n</context>")

    if memories:
        memory_text = "\n".join(f"- [{m.source_thread or 'unknown'}] {m.content[:200]}" for m in memories[:5])
        parts.append(f"<memory>\n{memory_text}\n</memory>")

    enriched = "\n\n".join(parts) + f"\n\n{user_input}" if parts else user_input

    return [HumanMessage(content=enriched)]
```

#### After (Optimized)

```python
def _build_enriched_input(
    self,
    user_input: str,
    projection: ContextProjection | None,  # noqa: ARG001 - kept for signature compatibility
    memories: list[MemoryItem],  # noqa: ARG001 - kept for signature compatibility
) -> list[HumanMessage]:
    """Build input message with user query only.

    Context and memory now injected into SystemMessage by
    SystemPromptOptimizationMiddleware. Parameters kept for
    backward compatibility during migration.

    Args:
        user_input: User's query text.
        projection: Context projection (unused, in SystemMessage).
        memories: Recalled memories (unused, in SystemMessage).

    Returns:
        Single HumanMessage with user query.

    Note:
        Context/memory XML construction moved to middleware
        for SystemMessage consolidation (RFC-207 alignment).
    """
    return [HumanMessage(content=user_input)]
```

**Migration Strategy**:
- Parameters kept temporarily for backward compatibility
- Can be removed in cleanup phase after all tests pass
- Signature compatibility allows incremental testing

---

### 3. Request State (No Changes)

**File**: `src/soothe/core/runner/_runner_phases.py` (lines 330-361)

Context projection and memories are already injected into `request.state` by the runner:

```python
async def _stream_phase(self, user_input: str, state: Any) -> AsyncGenerator[StreamChunk]:
    """Run the LangGraph stream with HITL interrupt loop."""
    await self._ensure_checkpointer_initialized()

    enriched_messages = self._build_enriched_input(
        user_input,
        state.context_projection,
        state.recalled_memories,
    )

    # Inject classification into agent state for middleware access
    stream_input: dict[str, Any] | Command = {"messages": enriched_messages}
    if state.unified_classification:
        stream_input["unified_classification"] = state.unified_classification

    # Inject context for system prompt XML sections (RFC-104)
    if hasattr(state, "workspace") and state.workspace:
        stream_input["workspace"] = state.workspace
    if hasattr(state, "git_status"):
        stream_input["git_status"] = state.git_status
    if hasattr(state, "thread_context"):
        stream_input["thread_context"] = state.thread_context
    if hasattr(state, "protocol_summary"):
        stream_input["protocol_summary"] = state.protocol_summary

    # Context projection and memories already available
    # (populated by _pre_stream_independent)
    stream_input["context_projection"] = state.context_projection
    stream_input["recalled_memories"] = state.recalled_memories

    # ... rest of method
```

**Why No Changes Needed**:
- `state.context_projection` populated by `_pre_stream_independent()` (line 591)
- `state.recalled_memories` populated by `_pre_stream_independent()` (line 579)
- Both already injected into `stream_input` for middleware access
- Middleware can now read these fields from `request.state`

---

## Data Flow

### Sequence Diagram

```
Pre-stream Phase
├─ Load context_projection (ContextProtocol.project)
└─ Load recalled_memories (MemoryProtocol.recall)

_stream_phase()
├─ Build HumanMessage via _build_enriched_input()
│  └─ Returns [HumanMessage(content=user_input)] (SIMPLIFIED)
├─ Inject state into stream_input
│  ├─ workspace
│  ├─ git_status
│  ├─ context_projection [ALREADY PRESENT]
│  ├─ recalled_memories [ALREADY PRESENT]
│  └─ unified_classification
├─ CoreAgent.astream() invocation
│  └─ Middleware chain processes request
│     └─ SystemPromptOptimizationMiddleware.modify_request()
│        ├─ Read state.context_projection
│        ├─ Read state.recalled_memories
│        ├─ Build SystemMessage with:
│        │  ├─ Base prompt
│        │  ├─ ENVIRONMENT
│        │  ├─ WORKSPACE
│        │  ├─ CONTEXT [NEW]
│        │  ├─ MEMORY [NEW]
│        │  ├─ SOOTHE_THREAD (complex)
│        │  ├─ SOOTHE_PROTOCOLS (complex)
│        │  └─ Date line
│        └─ Return modified request
└─ LLM receives [SystemMessage(enriched), HumanMessage(clean)]
```

### Key Differences

**Before**:
- Runner builds context/memory XML in `_build_enriched_input()`
- XML embedded in HumanMessage
- Middleware builds environment/workspace in SystemMessage
- Context split across two message types

**After**:
- Runner returns clean HumanMessage (user query only)
- Middleware builds ALL context sections (environment, workspace, context, memory)
- All system context consolidated in SystemMessage
- Clear separation: SystemMessage = context, HumanMessage = task

---

## Error Handling

### Edge Cases

| Case | Handling | Code Location |
|------|----------|---------------|
| Empty context projection | Check `if projection and projection.entries` before building | `_get_prompt_for_complexity()` |
| Empty memories list | Check `if memories` before building | `_get_prompt_for_complexity()` |
| Chitchat complexity | Early return before context/memory injection | `_get_prompt_for_complexity()` |
| Missing state fields | Use `state.get()` with None default | `_get_prompt_for_complexity()` |
| Large context/memory | Truncate to 10 entries/200 chars (context), 5 entries/200 chars (memory) | `_build_context_section()`, `_build_memory_section()` |

### Backward Compatibility

**Signature Compatibility**:
- `_build_enriched_input()` keeps parameters `projection` and `memories`
- Marked with `# noqa: ARG001` to suppress unused parameter warnings
- Can be removed in cleanup phase after migration complete

**Behavioral Equivalence**:
- Same XML format (no changes to content structure)
- Same truncation limits
- Same conditional injection logic (medium/complex only)
- LLM responses identical in structure and content

**Rollback Path**:
- If issues arise, revert `_build_enriched_input()` to build context/memory XML
- Remove context/memory section building from middleware
- No state injection changes needed

---

## Testing Strategy

### Unit Tests

**File**: `tests/unit/core/middleware/test_system_prompt_optimization.py`

#### New Tests

```python
import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from soothe.core.middleware import SystemPromptOptimizationMiddleware
from soothe.protocols.context import ContextEntry, ContextProjection
from soothe.protocols.memory import MemoryItem
from soothe.core.unified_classifier import UnifiedClassification


class TestContextMemoryInSystemMessage:
    """Tests for context and memory consolidation into SystemMessage."""

    def test_context_section_built_correctly(self):
        """Verify _build_context_section produces correct XML."""
        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        projection = ContextProjection(entries=[
            ContextEntry(source="tool", content="Found 5 Python files", ...),
            ContextEntry(source="subagent", content="Research complete", ...),
        ])

        result = middleware._build_context_section(projection)

        assert "<context>" in result
        assert "</context>" in result
        assert "[tool] Found 5 Python files" in result
        assert "[subagent] Research complete" in result

    def test_memory_section_built_correctly(self):
        """Verify _build_memory_section produces correct XML."""
        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        memories = [
            MemoryItem(content="User prefers Python 3.11", source_thread="t1", ...),
        ]

        result = middleware._build_memory_section(memories)

        assert "<memory>" in result
        assert "</memory>" in result
        assert "[t1] User prefers Python 3.11" in result

    def test_context_appears_in_system_message(self):
        """Verify context projection appears in SystemMessage after modify_request."""
        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        projection = ContextProjection(entries=[
            ContextEntry(source="tool", content="test result", ...),
        ])
        state = {
            "context_projection": projection,
            "workspace": "/tmp/test",
            "unified_classification": UnifiedClassification(task_complexity="medium"),
        }

        request = create_mock_request(state=state)
        modified = middleware.modify_request(request)

        system_msg = modified.messages[0]
        assert isinstance(system_msg, SystemMessage)
        assert "<context>" in system_msg.content
        assert "test result" in system_msg.content

    def test_memory_appears_in_system_message(self):
        """Verify memories appear in SystemMessage after modify_request."""
        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        memories = [MemoryItem(content="important note", source_thread="t1", ...)]
        state = {
            "recalled_memories": memories,
            "unified_classification": UnifiedClassification(task_complexity="complex"),
        }

        request = create_mock_request(state=state)
        modified = middleware.modify_request(request)

        system_msg = modified.messages[0]
        assert isinstance(system_msg, SystemMessage)
        assert "<memory>" in system_msg.content
        assert "important note" in system_msg.content

    def test_human_message_is_clean(self):
        """Verify HumanMessage contains only user query after optimization."""
        from soothe.core.runner import SootheRunner

        runner = SootheRunner()
        result = runner._build_enriched_input(
            user_input="What files are in the project?",
            projection=ContextProjection(entries=[
                ContextEntry(source="tool", content="previous result", ...),
            ]),
            memories=[MemoryItem(content="previous memory", ...)],
        )

        assert len(result) == 1
        assert isinstance(result[0], HumanMessage)
        assert result[0].content == "What files are in the project?"
        assert "<context>" not in result[0].content
        assert "<memory>" not in result[0].content

    def test_chitchat_skips_context_memory(self):
        """Verify chitchat queries do not get context/memory injection."""
        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        state = {
            "context_projection": ContextProjection(entries=[...]),
            "recalled_memories": [MemoryItem(...)],
            "unified_classification": UnifiedClassification(task_complexity="chitchat"),
        }

        request = create_mock_request(state=state)
        modified = middleware.modify_request(request)

        system_msg = modified.messages[0]
        assert "<context>" not in system_msg.content
        assert "<memory>" not in system_msg.content

    def test_empty_projection_no_section(self):
        """Verify empty context projection produces no section."""
        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        projection = ContextProjection(entries=[])
        state = {
            "context_projection": projection,
            "unified_classification": UnifiedClassification(task_complexity="medium"),
        }

        request = create_mock_request(state=state)
        modified = middleware.modify_request(request)

        system_msg = modified.messages[0]
        assert "<context>" not in system_msg.content

    def test_truncation_limits_respected(self):
        """Verify context/memory truncation limits are maintained."""
        middleware = SystemPromptOptimizationMiddleware(config=mock_config)

        # Create 20 entries (should truncate to 10)
        projection = ContextProjection(entries=[
            ContextEntry(source=f"src{i}", content=f"content {i}", ...)
            for i in range(20)
        ])

        result = middleware._build_context_section(projection)

        # Count entries in result
        lines = [l for l in result.split('\n') if l.startswith('- [')]
        assert len(lines) == 10
```

#### Updated Tests

Any existing tests that check for context/memory in HumanMessage should be updated:

```python
# Before: Checked HumanMessage for context
def test_enriched_input_contains_context():
    result = runner._build_enriched_input(...)
    assert "<context>" in result[0].content  # OLD

# After: Check SystemMessage instead
def test_system_message_contains_context():
    modified = middleware.modify_request(request)
    system_msg = modified.messages[0]
    assert "<context>" in system_msg.content  # NEW
```

### Integration Tests

**Files**: `tests/integration/` (existing tests)

**Expectation**: All integration tests should pass unchanged because:
- LLM responses have identical structure and content
- Only message structure differs (internal implementation detail)
- No API changes to runner or middleware

**Verification**:

```bash
# Run all tests
make test-unit        # Unit tests (900+)
make test-integration # Integration tests
./scripts/verify_finally.sh  # Full verification (format, lint, tests)
```

### Manual Testing

**Test Case 1: Simple Query (Medium Complexity)**

```bash
# Run simple query
soothe "List files in the workspace"

# Expected:
# - SystemMessage contains <ENVIRONMENT>, <WORKSPACE>, <context>, <memory>
# - HumanMessage contains only "List files in the workspace"
# - Response identical to before optimization
```

**Test Case 2: Complex Query**

```bash
# Run complex query
soothe "Research the codebase architecture and propose improvements"

# Expected:
# - SystemMessage contains all sections including context/memory
# - Multiple tool calls executed correctly
# - Response quality maintained or improved
```

**Test Case 3: Chitchat**

```bash
# Run chitchat query
soothe "Hello!"

# Expected:
# - SystemMessage contains only base prompt + date line
# - No context/memory injection
# - Fast response
```

---

## Migration Path

### Phase 1: Implementation (1-2 hours)

1. **Add context/memory builders to middleware**:
   - Add `_build_context_section()` method
   - Add `_build_memory_section()` method
   - Add type hints and docstrings

2. **Extend middleware prompt builder**:
   - Modify `_get_prompt_for_complexity()` to append context/memory
   - Add defensive checks for empty projections/memories
   - Maintain existing conditional logic (medium/complex only)

3. **Simplify runner**:
   - Update `_build_enriched_input()` to return clean HumanMessage
   - Keep parameters for backward compatibility
   - Add deprecation note in docstring

### Phase 2: Testing (1 hour)

1. **Add unit tests**:
   - Test `_build_context_section()` output
   - Test `_build_memory_section()` output
   - Test context/memory appear in SystemMessage
   - Test HumanMessage is simplified
   - Test chitchat skips injection

2. **Run existing tests**:
   - `make test-unit` (900+ tests)
   - Identify and fix any failures

3. **Manual verification**:
   - Run sample queries
   - Verify SystemMessage contains context/memory
   - Verify responses identical to before

### Phase 3: Verification (30 minutes)

1. **Run full verification suite**:
   ```bash
   ./scripts/verify_finally.sh
   ```
   - Format check passes
   - Linting passes (zero errors)
   - All 900+ tests pass

2. **Performance check**:
   - Run sample queries
   - Verify no latency regression
   - Check token usage (should be same or better)

### Phase 4: Documentation (30 minutes)

1. **Update design documentation**:
   - Update `docs/references/llm-communication-analysis.md`
   - Add to CLAUDE.md Recent Changes (optional)

2. **Code documentation**:
   - Ensure all methods have docstrings
   - Add inline comments for complex logic

### Phase 5: Cleanup (Optional)

1. **Remove unused parameters** (after all tests stable):
   - Remove `projection` and `memories` from `_build_enriched_input()`
   - Update call sites

2. **Remove deprecation notes**

---

## Files Modified

### Primary Implementation (2 files)

1. **`src/soothe/core/middleware/system_prompt_optimization.py`**
   - Add `_build_context_section()` method (~10 lines)
   - Add `_build_memory_section()` method (~8 lines)
   - Extend `_get_prompt_for_complexity()` (~15 lines)
   - Add imports for ContextProjection, MemoryItem (~2 lines)
   - **Total**: ~35 lines added

2. **`src/soothe/core/runner/_runner_phases.py`**
   - Simplify `_build_enriched_input()` body (~12 lines removed)
   - Add backward compatibility note in docstring (~5 lines)
   - **Total**: ~7 lines net change (simplification)

### Tests (1 file)

3. **`tests/unit/core/middleware/test_system_prompt_optimization.py`**
   - Add test class `TestContextMemoryInSystemMessage` (~80 lines)
   - Update existing tests if needed (~10 lines)
   - **Total**: ~90 lines added

### Documentation (Optional)

4. **`docs/references/llm-communication-analysis.md`**
   - Update Phase 4.2 section (~20 lines changed)

5. **`CLAUDE.md`**
   - Add to Recent Changes section (~5 lines)

---

## Success Criteria

### Functional Requirements

- [ ] Context projection XML appears in SystemMessage (not HumanMessage)
- [ ] Memories XML appears in SystemMessage (not HumanMessage)
- [ ] HumanMessage contains only user query text
- [ ] Chitchat queries skip context/memory injection
- [ ] Medium/complex queries include context/memory in SystemMessage
- [ ] Truncation limits maintained (10 entries/200 chars for context, 5/200 for memory)

### Quality Requirements

- [ ] All 900+ unit tests pass
- [ ] All integration tests pass
- [ ] Linting passes with zero errors
- [ ] Code formatting passes
- [ ] No duplicate context/memory between SystemMessage and HumanMessage

### Behavioral Requirements

- [ ] LLM responses have identical structure and content
- [ ] No performance regression (latency, token usage)
- [ ] Backward compatible (signature unchanged)
- [ ] Error handling maintains graceful degradation

---

## Benefits

### Token Efficiency

✅ **Eliminated duplication**: Context/memory appear once in SystemMessage
✅ **Cleaner message structure**: No redundant information across message types
✅ **Better token utilization**: System context consolidated in single message

### LLM Response Quality

✅ **Better model attention**: Context receives SystemMessage weight (Claude best practice)
✅ **Clear hierarchy**: System context vs user task distinction
✅ **Improved reasoning**: Model properly prioritizes contextual information

### Architectural Clarity

✅ **RFC-207 alignment**: Same SystemMessage/HumanMessage separation as Layer 2
✅ **Single responsibility**: Middleware owns all system prompt construction
✅ **Simplified runner**: `_build_enriched_input()` becomes trivial
✅ **Consistent pattern**: Context/memory treated same as environment/workspace

### Maintainability

✅ **Easier testing**: Mock request.state, verify SystemMessage contains all context
✅ **Clear boundaries**: System context in middleware, user task in runner
✅ **Less code**: ~12 lines removed from runner, ~35 lines added to middleware (net reduction)

### Minimal Disruption

✅ **2 files modified**: ~50 lines changed total
✅ **No new abstractions**: Extends existing middleware pattern
✅ **No data plumbing changes**: Context/memory already in request.state
✅ **Backward compatible**: Signature unchanged, can revert if needed

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Tests fail after message structure change | Low | Medium | Backward compatible signature, incremental testing, comprehensive test suite |
| Behavior changes in LLM responses | Very Low | High | Integration tests verify responses identical; same XML format, same truncation |
| Missing context in edge cases | Low | Medium | Defensive checks (`if projection and projection.entries`), empty state handling |
| Performance regression | Very Low | Low | Same operations, just different location; benchmark if concerned |
| Breaking existing mocks | Low | Low | Update mocks to check SystemMessage instead of HumanMessage |
| Large context/memory overhead | Very Low | Low | Truncation limits already in place; no change to size constraints |

---

## Alternatives Considered

### Alternative 1: Build XML in Runner, Inject via Middleware

**Description**: Runner builds context/memory XML, stores in state, middleware retrieves and appends.

**Pros**:
- Runner maintains XML building logic
- Middleware remains simple string concatenation

**Cons**:
- More moving parts (indirect data flow)
- Harder to trace (built in runner, stored in state, retrieved in middleware)
- Still need to pass context/memory to runner for XML building

**Why Rejected**: Added complexity without clear benefit; current approach (build in middleware) is cleaner.

### Alternative 2: Create CoreAgentMessageBuilder Class

**Description**: New builder class mirroring Layer 2's PromptBuilder pattern.

**Pros**:
- Architectural consistency with Layer 2
- Single responsibility for message construction
- Enables future optimizations (caching, compression)

**Cons**:
- More significant architectural change
- Introduces new abstraction layer
- Bypasses middleware for primary message construction
- More parameters to pass around

**Why Rejected**: Over-engineered for current needs; extending middleware is simpler and sufficient.

### Alternative 3: Conditional Placement Based on Complexity

**Description**: Simple queries keep context in HumanMessage, complex queries move to SystemMessage.

**Pros**:
- Tailored approach per complexity level

**Cons**:
- Inconsistent behavior across query types
- Harder to test and reason about
- No clear benefit over always placing in SystemMessage

**Why Rejected**: Adds complexity without benefit; consistent placement in SystemMessage is cleaner.

---

## Future Considerations

### Potential Follow-up Work

1. **Prompt Caching**:
   - SystemMessage is relatively static across iterations
   - Could leverage Claude's prompt caching for cost reduction
   - Requires Claude API support and careful invalidation logic

2. **Message Compression**:
   - For long-running agents with extensive context
   - Implement message compression/summarization
   - Reduce token costs for large context projections

3. **Dynamic SystemMessage Refresh**:
   - Certain context might change between iterations
   - Implement selective SystemMessage regeneration
   - Keep static parts cached, refresh dynamic parts

4. **Context Window Optimization**:
   - Intelligent token budget allocation
   - Prioritize most relevant context entries
   - Adaptive truncation based on importance scores

**Note**: These are out of scope for this design but worth considering for future iterations.

---

## Timeline Estimate

- **Implementation**: 1-2 hours
- **Testing**: 1 hour
- **Verification**: 30 minutes
- **Documentation**: 30 minutes
- **Total**: ~3-4 hours

---

## References

### Related Specifications

- **RFC-207**: SystemMessage/HumanMessage Separation (Layer 2)
- **RFC-201**: Layer 2 Agentic Goal Execution (Reason/Act loop)
- **RFC-100**: Layer 1 CoreAgent Runtime
- **RFC-104**: Context XML Injection

### Implementation Guides

- **IG-142**: Message Type Separation (RFC-207 implementation)
- **IG-137**: Prompt Architecture Consolidation

### Code References

- `src/soothe/core/middleware/system_prompt_optimization.py` (middleware)
- `src/soothe/core/runner/_runner_phases.py` (runner phases)
- `src/soothe/core/prompts/context_xml.py` (XML builders)

---

**Document Status**: Design Complete
**Next Step**: Implementation upon approval
**Estimated Completion**: 3-4 hours from start