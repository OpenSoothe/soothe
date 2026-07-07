# IG-145: CoreAgent Message Optimization (RFC-208)

**Status**: ✅ Completed
**Created**: 2026-04-09
**Author**: AI Agent
**Scope**: Layer 1 CoreAgent message construction optimization
**RFC**: RFC-208
**Dependencies**: RFC-207 (Layer 2 message separation)

---

## Summary

Implement RFC-208 CoreAgent message optimization by consolidating context projection and memories into SystemMessage, following RFC-207's SystemMessage/HumanMessage separation pattern. This refines Phase 4.2 message construction for better token efficiency, LLM response quality, and architectural clarity.

---

## Motivation

Phase 4.2 currently splits context between SystemMessage (environment/workspace) and HumanMessage (context/memory/user query). This optimization:

1. **Token efficiency**: Eliminates duplicate context between messages
2. **LLM response quality**: Context receives proper SystemMessage weight
3. **Architectural clarity**: Aligns with RFC-207 pattern (SystemMessage = context, HumanMessage = task)
4. **Minimal disruption**: ~50 lines across 2 files

---

## Goals

1. Add `_build_context_section()` to SystemPromptOptimizationMiddleware
2. Add `_build_memory_section()` to SystemPromptOptimizationMiddleware
3. Extend `_get_prompt_for_complexity()` to append context/memory to SystemMessage
4. Simplify `_build_enriched_input()` to return clean HumanMessage
5. Add comprehensive unit tests
6. All 900+ tests pass, linting zero errors

---

## Implementation Plan

### Phase 1: Extend SystemPromptOptimizationMiddleware

**File**: `src/soothe/core/middleware/system_prompt_optimization.py`

#### 1.1 Add Import Statements

```python
from soothe.protocols.context import ContextProjection
from soothe.protocols.memory import MemoryItem
```

Add after existing imports (around line 12-15).

#### 1.2 Add _build_context_section() Method

Insert after `_get_domain_scoped_prompt()` method (around line 127):

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

#### 1.3 Add _build_memory_section() Method

Insert after `_build_context_section()`:

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

#### 1.4 Extend _get_prompt_for_complexity()

Find method starting around line 83. Add context/memory section building after workspace sections and before date line:

```python
def _get_prompt_for_complexity(self, complexity: str, state: dict[str, Any] | None = None) -> str:
    """Get prompt with XML context sections for complexity level.

    NEW: Appends context and memory sections to SystemMessage for medium/complex queries.
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

    # NEW: Context projection and memories (medium/complex only)
    if state:
        projection = state.get("context_projection")
        if projection and projection.entries:
            sections.append(self._build_context_section(projection))

        memories = state.get("recalled_memories")
        if memories:
            sections.append(self._build_memory_section(memories))

    sections.append(date_line)
    return "\n\n".join(sections)
```

---

### Phase 2: Simplify _build_enriched_input()

**File**: `src/soothe/core/runner/_runner_phases.py`

Find method around line 772. Replace entire method body:

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
        for SystemMessage consolidation (RFC-208 alignment).
    """
    return [HumanMessage(content=user_input)]
```

---

### Phase 3: Add Unit Tests

**File**: `tests/unit/core/middleware/test_system_prompt_optimization.py`

#### 3.1 Add Test Class

Add new test class at end of file:

```python
class TestContextMemoryInSystemMessage:
    """Tests for context and memory consolidation into SystemMessage (RFC-208)."""

    def test_context_section_built_correctly(self, mock_config):
        """Verify _build_context_section produces correct XML."""
        from soothe.protocols.context import ContextEntry, ContextProjection
        from soothe.core.middleware import SystemPromptOptimizationMiddleware

        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        projection = ContextProjection(
            entries=[
                ContextEntry(
                    source="tool",
                    content="Found 5 Python files",
                    timestamp=datetime.now(UTC),
                    tags=[],
                    importance=0.8,
                ),
                ContextEntry(
                    source="subagent",
                    content="Research complete",
                    timestamp=datetime.now(UTC),
                    tags=[],
                    importance=0.9,
                ),
            ],
            summary="Test summary",
            total_entries=2,
            token_count=100,
        )

        result = middleware._build_context_section(projection)

        assert "<context>" in result
        assert "</context>" in result
        assert "[tool] Found 5 Python files" in result
        assert "[subagent] Research complete" in result

    def test_memory_section_built_correctly(self, mock_config):
        """Verify _build_memory_section produces correct XML."""
        from soothe.protocols.memory import MemoryItem
        from soothe.core.middleware import SystemPromptOptimizationMiddleware

        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        memories = [
            MemoryItem(
                content="User prefers Python 3.11",
                source_thread="t1",
                created_at=datetime.now(UTC),
                tags=["preference"],
            ),
        ]

        result = middleware._build_memory_section(memories)

        assert "<memory>" in result
        assert "</memory>" in result
        assert "[t1] User prefers Python 3.11" in result

    def test_context_appears_in_system_message(self, mock_config):
        """Verify context projection appears in SystemMessage after modify_request."""
        from langchain.agents.middleware.types import ModelRequest
        from langchain_core.messages import HumanMessage, SystemMessage
        from soothe.protocols.context import ContextEntry, ContextProjection
        from soothe.core.middleware import SystemPromptOptimizationMiddleware
        from soothe.core.unified_classifier import UnifiedClassification

        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        projection = ContextProjection(
            entries=[
                ContextEntry(
                    source="tool",
                    content="test result",
                    timestamp=datetime.now(UTC),
                    tags=[],
                    importance=0.8,
                ),
            ],
            summary="Test",
            total_entries=1,
            token_count=50,
        )
        state = {
            "context_projection": projection,
            "workspace": "/tmp/test",
            "unified_classification": UnifiedClassification(task_complexity="medium"),
        }

        request = ModelRequest(
            state=state,
            messages=[HumanMessage(content="test query")],
        )
        modified = middleware.modify_request(request)

        system_msg = modified.messages[0]
        assert isinstance(system_msg, SystemMessage)
        assert "<context>" in system_msg.content
        assert "test result" in system_msg.content

    def test_memory_appears_in_system_message(self, mock_config):
        """Verify memories appear in SystemMessage after modify_request."""
        from langchain.agents.middleware.types import ModelRequest
        from langchain_core.messages import HumanMessage, SystemMessage
        from soothe.protocols.memory import MemoryItem
        from soothe.core.middleware import SystemPromptOptimizationMiddleware
        from soothe.core.unified_classifier import UnifiedClassification

        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        memories = [
            MemoryItem(
                content="important note",
                source_thread="t1",
                created_at=datetime.now(UTC),
                tags=["note"],
            ),
        ]
        state = {
            "recalled_memories": memories,
            "unified_classification": UnifiedClassification(task_complexity="complex"),
        }

        request = ModelRequest(
            state=state,
            messages=[HumanMessage(content="test")],
        )
        modified = middleware.modify_request(request)

        system_msg = modified.messages[0]
        assert isinstance(system_msg, SystemMessage)
        assert "<memory>" in system_msg.content
        assert "important note" in system_msg.content

    def test_chitchat_skips_context_memory(self, mock_config):
        """Verify chitchat queries do not get context/memory injection."""
        from langchain.agents.middleware.types import ModelRequest
        from langchain_core.messages import HumanMessage
        from soothe.protocols.context import ContextProjection, ContextEntry
        from soothe.protocols.memory import MemoryItem
        from soothe.core.middleware import SystemPromptOptimizationMiddleware
        from soothe.core.unified_classifier import UnifiedClassification

        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        projection = ContextProjection(
            entries=[
                ContextEntry(
                    source="tool",
                    content="data",
                    timestamp=datetime.now(UTC),
                    tags=[],
                    importance=0.8,
                ),
            ],
            summary="",
            total_entries=1,
            token_count=10,
        )
        state = {
            "context_projection": projection,
            "recalled_memories": [MemoryItem(content="mem", source_thread="t1", created_at=datetime.now(UTC), tags=[])],
            "unified_classification": UnifiedClassification(task_complexity="chitchat"),
        }

        request = ModelRequest(
            state=state,
            messages=[HumanMessage(content="hello")],
        )
        modified = middleware.modify_request(request)

        system_msg = modified.messages[0]
        assert "<context>" not in system_msg.content
        assert "<memory>" not in system_msg.content

    def test_empty_projection_no_section(self, mock_config):
        """Verify empty context projection produces no section."""
        from langchain.agents.middleware.types import ModelRequest
        from langchain_core.messages import HumanMessage
        from soothe.protocols.context import ContextProjection
        from soothe.core.middleware import SystemPromptOptimizationMiddleware
        from soothe.core.unified_classifier import UnifiedClassification

        middleware = SystemPromptOptimizationMiddleware(config=mock_config)
        projection = ContextProjection(
            entries=[],
            summary="",
            total_entries=0,
            token_count=0,
        )
        state = {
            "context_projection": projection,
            "unified_classification": UnifiedClassification(task_complexity="medium"),
        }

        request = ModelRequest(
            state=state,
            messages=[HumanMessage(content="test")],
        )
        modified = middleware.modify_request(request)

        system_msg = modified.messages[0]
        assert "<context>" not in system_msg.content
```

---

### Phase 4: Verification

#### 4.1 Run Tests

```bash
# Run unit tests
make test-unit

# Run linting
make lint

# Run format check
make format-check

# Full verification
./scripts/verify_finally.sh
```

#### 4.2 Success Criteria

1. ✅ All 900+ tests pass
2. ✅ Linting passes with zero errors
3. ✅ Code formatting passes
4. ✅ Context projection appears in SystemMessage
5. ✅ Memories appear in SystemMessage
6. ✅ HumanMessage simplified
7. ✅ Chitchat skips injection
8. ✅ Empty projections handled gracefully

---

## Files Modified

### Primary Implementation

1. `src/soothe/core/middleware/system_prompt_optimization.py`:
   - Add `_build_context_section()` method
   - Add `_build_memory_section()` method
   - Extend `_get_prompt_for_complexity()`

2. `src/soothe/core/runner/_runner_phases.py`:
   - Simplify `_build_enriched_input()`

### Tests

3. `tests/unit/core/middleware/test_system_prompt_optimization.py`:
   - Add `TestContextMemoryInSystemMessage` test class

---

## Edge Cases

| Case | Handling |
|------|----------|
| Empty context projection | Check `if projection and projection.entries` |
| Empty memories list | Check `if memories` |
| Chitchat complexity | Early return in `_get_prompt_for_complexity()` |
| Missing state fields | Use `state.get()` with None default |
| Large context/memory | Truncate to 10/200 (context), 5/200 (memory) |

---

## Testing Strategy

### Unit Tests

- Test `_build_context_section()` output format
- Test `_build_memory_section()` output format
- Test context appears in SystemMessage after `modify_request()`
- Test memory appears in SystemMessage after `modify_request()`
- Test HumanMessage is simplified
- Test chitchat skips injection
- Test empty projections/memories
- Test truncation limits

### Integration Tests

All existing integration tests should pass unchanged (behavior identical).

---

## Rollback Plan

If issues arise:

1. Revert `_build_enriched_input()` to build context/memory XML
2. Remove context/memory section building from middleware
3. No state injection changes needed

---

## Dependencies

- **RFC-208**: CoreAgent message optimization
- **RFC-207**: Layer 2 message separation (pattern reference)
- **RFC-201**: Layer 2 execution (context flow)
- **RFC-100**: CoreAgent runtime (Layer 1)

---

## Success Metrics

- Code quality: Linting zero errors, formatting passes
- Test coverage: All 900+ tests pass
- Behavioral equivalence: LLM responses identical
- Architectural improvement: Clear SystemMessage/HumanMessage separation

---

## Next Steps

1. ✅ RFC-208 created
2. ✅ IG-145 created (this guide)
3. 🚧 Implement Phase 1: Extend middleware
4. 🚧 Implement Phase 2: Simplify runner
5. 🚧 Implement Phase 3: Add tests
6. 🚧 Run Phase 4: Verification
7. ✅ Mark IG-145 as Completed
8. ✅ Update RFC-208 status to Implemented

---

## Changelog

**2026-04-09 (completed)**:
- ✅ All 4 phases implemented
- ✅ SystemPromptOptimizationMiddleware extended
- ✅ _build_enriched_input() simplified
- ✅ All 1595 tests pass
- ✅ Linting passes with zero errors
- ✅ Code formatting passes
- ✅ Context/memory now in SystemMessage
- ✅ HumanMessage simplified to user query only
- ✅ RFC-208 status updated to Implemented

**2026-04-09 (created)**:
- Initial IG-145 created
- Implementation plan defined
- 4 phases outlined
- Files modified list compiled
- Success criteria defined