# ContextProtocol

**RFC**: 400  
**Status**: Draft (Not Yet Implemented)  
**Location**: Planned implementation  
**Supersedes**: RFC-300 (Context and Memory Architecture)  

## Overview

ContextProtocol is **planned** as Soothe's unbounded knowledge accumulator for cognitive context engineering. It serves as StrangeLoop's "consciousness" layer, maintaining complete execution knowledge across threads.

⚠️ **Implementation Status**: ContextProtocol is defined in RFC-400 (draft status) but **not yet implemented**. The current architecture uses alternative mechanisms for context management. This documentation describes the **planned design**.

## Planned Purpose

- **Unbounded ledger**: Append-only knowledge accumulation
- **Bounded projection**: Token-budget-aware view extraction
- **Goal-centric retrieval**: Self-contained retrieval module
- **Thread-scoped persistence**: Per-thread ledger persistence
- **Subagent briefing**: Scoped projections for delegation

## Planned Protocol Interface

```python
class ContextProtocol(Protocol):
    """Unbounded knowledge accumulator for cognitive context engineering.
    
    Planned design per RFC-400.
    """

    async def ingest(self, entry: ContextEntry) -> None:
        """Append knowledge entry (append-only, never discard).
        
        Args:
            entry: ContextEntry to append to ledger.
        """
        ...

    async def project(
        self, 
        query: str, 
        token_budget: int
    ) -> ContextProjection:
        """Project bounded view for orchestrator reasoning.
        
        Args:
            query: Relevance query for projection.
            token_budget: Maximum tokens in projection.
            
        Returns:
            ContextProjection with ranked entries.
        """
        ...

    async def project_for_subagent(
        self, 
        goal: str, 
        token_budget: int
    ) -> ContextProjection:
        """Project bounded view scoped for subagent briefing.
        
        Args:
            goal: Delegated goal for scoping.
            token_budget: Maximum tokens in projection.
            
        Returns:
            ContextProjection scoped to goal.
        """
        ...

    def get_retrieval_module(self) -> ContextRetrievalModule:
        """Get self-contained retrieval module for goal-centric access.
        
        Returns:
            ContextRetrievalModule with stable API boundary.
        """
        ...

    async def summarize(self, scope: str | None = None) -> str:
        """Generate summary of context entries.
        
        Args:
            scope: Optional scope filter for summary.
            
        Returns:
            Human-readable context summary.
        """
        ...

    async def persist(self, thread_id: str) -> None:
        """Persist context ledger to durability backend.
        
        Args:
            thread_id: Thread ID for persistence key.
        """
        ...

    async def restore(self, thread_id: str) -> bool:
        """Restore context ledger from durability backend.
        
        Args:
            thread_id: Thread ID to restore.
            
        Returns:
            True if ledger restored successfully.
        """
        ...
```

## Planned Data Models

### ContextEntry

```python
class ContextEntry(BaseModel):
    """Unit of knowledge in context ledger.
    
    Args:
        source: Source identifier (agent, tool, subagent, reflection).
        content: Knowledge content.
        timestamp: Entry creation timestamp.
        tags: Tags for categorization and filtering.
        importance: Importance score (0.0-1.0) for projection ranking.
    """

    source: str
    content: str
    timestamp: datetime
    tags: list[str] = []
    importance: float = 0.5
```

### ContextProjection

```python
class ContextProjection(BaseModel):
    """Bounded view of context ledger.
    
    Args:
        entries: Ranked entries within token budget.
        summary: Brief summary of projection context.
        total_entries: Total entries in ledger (projection subset).
        token_count: Actual token count in projection.
    """

    entries: list[ContextEntry]
    summary: str
    total_entries: int
    token_count: int
```

## Design Principles (RFC-400)

### 1. Accumulate, Never Discard

Context ledger is append-only and unbounded:
- No deletion of entries
- No truncation of history
- Knowledge persists indefinitely
- Only projections bounded by token budgets

### 2. Relevance-Based Projection

Entries ranked by relevance to query:
- Importance weighting
- Tag matching
- Semantic similarity (if embedding-based)
- Temporal decay (optional)

### 3. Purpose-Scoped Projections

Different views for different purposes:
- **Orchestrator reasoning**: Full context with goal relevance
- **Subagent briefing**: Scoped to delegated goal
- **Reflection**: Structured evidence summaries
- **User summary**: High-level progress overview

### 4. Subagent Isolation

Subagents receive projections, not full context:
- Scoped to delegated goal
- Bounded by token budget
- Return results only (no context access)
- Orchestrator ingests subagent results

## ContextRetrievalModule (Planned)

Self-contained retrieval module with stable API boundary:

```python
class ContextRetrievalModule:
    """Self-contained retrieval module for ContextProtocol.
    
    Stable API boundary enables algorithm evolution without
    breaking ContextProtocol interface.
    """

    def __init__(self, embedding_model: Embeddings) -> None:
        self._embedding_model = embedding_model
        self._algorithm_version = "v1_keyword"  # Evolvable

    def retrieve_by_goal_relevance(
        self,
        goal_id: str,
        query: str,
        token_budget: int,
    ) -> list[ContextEntry]:
        """Retrieve entries by goal-centric relevance.
        
        Args:
            goal_id: Goal identifier for context scope.
            query: Relevance query text.
            token_budget: Maximum tokens to retrieve.
            
        Returns:
            Ranked entries within budget.
        """
        ...
```

## Current Context Management

Until ContextProtocol is implemented, Soothe uses:

### Current Mechanisms

1. **Conversation History**: Managed by deepagents `SummarizationMiddleware`
2. **LoopWorkingMemory**: Bounded scratchpad for Plan prompts
3. **MemoryProtocol**: Cross-thread long-term memory

### Migration Path

When ContextProtocol is implemented:

1. Conversation history → SummarizationMiddleware (unchanged)
2. Working memory → LoopWorkingMemoryProtocol (unchanged)
3. **New**: ContextProtocol for unbounded ledger

## Specification Reference

- **RFC-400**: ContextProtocol: Unbounded Knowledge & Goal-Centric Retrieval (draft)
- **RFC-001**: Core Modules Architecture (references RFC-400 for retrieval)
- **RFC-300**: Context and Memory Architecture Design (superseded by RFC-400)

## Implementation Timeline

ContextProtocol is planned for future implementation. Current blockers:

- RFC-400 is in draft status
- Retrieval module design needs finalization
- Backend architecture decisions pending

**Track RFC-400 status** for implementation updates.

## Related Documentation

- [RFC-400 Draft](../specs/RFC-400-context-protocol-architecture.md)
- [Memory Protocol](memory.md) - Current cross-thread memory
- [LoopWorkingMemory Protocol](loop-protocols.md) - Current bounded scratchpad
- [Planner Protocol](planner.md) - Uses bounded context for planning