# RFC-400: ContextProtocol Architecture

**RFC**: 400
**Title**: ContextProtocol: Unbounded Knowledge & Goal-Centric Retrieval
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Dependencies**: RFC-000, RFC-001
**Related**: RFC-402 (Memory), RFC-408 (Durability)

---

## Abstract

This RFC defines ContextProtocol, Soothe's unbounded knowledge accumulator for cognitive context engineering. ContextProtocol provides append-only knowledge ingestion, relevance-based projection for bounded token windows, and goal-centric retrieval through self-contained retrieval module with stable API boundary. ContextProtocol serves as AgentLoop's "consciousness" layer, maintaining complete execution knowledge across threads.

---

## Protocol Interface

```python
class ContextProtocol(Protocol):
    """Unbounded knowledge accumulator for cognitive context engineering."""

    async def ingest(self, entry: ContextEntry) -> None:
        """Append knowledge entry (append-only, never discard)."""
        ...

    async def project(self, query: str, token_budget: int) -> ContextProjection:
        """Project bounded view for orchestrator reasoning."""
        ...

    async def project_for_subagent(self, goal: str, token_budget: int) -> ContextProjection:
        """Project bounded view scoped for subagent briefing."""
        ...

    def get_retrieval_module(self) -> ContextRetrievalModule:
        """Get self-contained retrieval module for goal-centric access."""
        ...

    async def summarize(self, scope: str | None = None) -> str:
        """Generate summary of context entries."""
        ...

    async def persist(self, thread_id: str) -> None:
        """Persist context ledger to durability backend."""
        ...

    async def restore(self, thread_id: str) -> bool:
        """Restore context ledger from durability backend."""
        ...
```

---

## Data Models

### ContextEntry

```python
class ContextEntry(BaseModel):
    """Unit of knowledge in context ledger."""
    source: str
    """Source identifier (agent, tool, subagent, reflection)."""
    content: str
    """Knowledge content."""
    timestamp: datetime
    """Entry creation timestamp."""
    tags: list[str] = []
    """Tags for categorization and filtering."""
    importance: float = 0.5
    """Importance score (0.0-1.0) for projection ranking."""
```

### ContextProjection

```python
class ContextProjection(BaseModel):
    """Bounded view of context ledger."""
    entries: list[ContextEntry]
    """Ranked entries within token budget."""
    summary: str
    """Brief summary of projection context."""
    total_entries: int
    """Total entries in ledger (projection subset)."""
    token_count: int
    """Actual token count in projection."""
```

---

## Design Principles

### 1. Accumulate, Never Discard

Context ledger is append-only and unbounded:
- No deletion of entries
- No truncation of history
- Knowledge persists indefinitely
- Only projections bounded by token budgets

### 2. Relevance-Based Projection

Entries ranked by relevance to query, not just recency:
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

---

## ContextRetrievalModule

**Canonical section**: This is the **authoritative** specification for `ContextRetrievalModule` and goal-centric retrieval. [RFC-001](./RFC-001-core-modules-architecture.md) summarizes `ContextProtocol` and defers here for the full retrieval API and algorithm-version table.

### Self-Contained Goal-Centric Retrieval

Self-contained retrieval module with stable API boundary enables algorithm evolution without breaking ContextProtocol interface.

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
        execution_context: dict[str, Any],
        limit: int = 10,
    ) -> list[ContextEntry]:
        """Goal-centric retrieval (not query-centric).

        Relevance determined by goal relationship to history,
        not keyword similarity.

        Args:
            goal_id: Target goal for relevance matching
            execution_context: Current execution state
            limit: Maximum entries to return

        Returns:
            ContextEntry list ranked by goal relevance

        Stable API: Algorithm can evolve (keyword → embedding → hybrid)
        without breaking callers.
        """
```

### Algorithm Versions

| Version | Algorithm | Description | Status |
|---------|-----------|-------------|--------|
| `v1_keyword` | Goal tag matching | Match entries with `goal_id` tag (immediate) | ✅ Recommended MVP |
| `v2_embedding` | Semantic similarity | Embed goal description, match entry embeddings | ⚠️ Future enhancement |
| `hybrid` | Combined approach | Keyword + embedding hybrid scoring | ⚠️ Future enhancement |

**Version Selection**: Configurable via `context.retrieval.algorithm_version`. Algorithm evolution behind stable API preserves integration contracts.

### AgentLoop Integration Pattern

**Integration with RFC-201 AgentLoop.Executor**:

```python
# AgentLoop.Executor calls ContextRetrievalModule
retrieval = context.get_retrieval_module()
relevant_history = retrieval.retrieve_by_goal_relevance(
    goal_id=state.current_goal_id,
    execution_context={"iteration": state.iteration},
    limit=10,
)
# Build task package with goal-centric context
```

**Ownership Boundary** (RFC-201 §61-78):
- **ContextProtocol ownership**: Retrieval module implementation, algorithm versions, stable API
- **AgentLoop operational authority**: WHEN to retrieve, FOR WHICH goal, HOW to combine with GoalContextManager output

### Evidence Storage Pattern

**GoalEngine Failure Evidence Storage**:

```python
# GoalEngine stores failure evidence
evidence_entry = ContextEntry(
    source="goal_engine",
    content=f"Goal {goal_id} failed: {error}",
    tags=["failure", goal_id],
    importance=0.8,  # High importance for failures
    goal_id=goal_id,
)
await context.ingest(evidence_entry)
```

**Tagging Schema**:
- Goal-centric entries tagged with `goal_id` for retrieval
- Failure entries tagged with `["failure", goal_id]` (importance: 0.8)
- Success entries tagged with `["success", goal_id]` (importance: 0.5-0.7)
- Reflection entries tagged with `["reflection", goal_id]` (importance: 0.9)

### Stable API Design

**API contract preserved across algorithm evolution**:
- Input: goal_id, execution_context, limit
- Output: list[ContextEntry] ranked by relevance
- Internal algorithm: Evolvable without breaking callers

**Benefits**:
- Algorithm experimentation without breaking changes
- Performance optimization transparent to callers
- Future embedding integration seamless

---

## Implementation Priority

**Critical Foundation**: ContextProtocol is specified but not yet implemented. This is a foundational protocol required by:
- GoalBackoffReasoner (RFC-200) - needs ContextProtocol for evidence storage
- ThreadRelationshipModule (RFC-609) - needs ContextProtocol for embedding model access
- AgentLoop.Executor (RFC-201) - needs ContextProtocol for goal-centric retrieval

**Recommended Implementation Sequence**:
1. Phase 1: KeywordContext backend (v1_keyword algorithm, JSON persistence)
2. Phase 2: Integration with SootheRunner, AgentLoop.Executor, GoalEngine
3. Phase 3: VectorContext backend (v2_embedding algorithm, requires vector store)

---

## Implementations

### KeywordContext

```python
class KeywordContext(ContextProtocol):
    """Keyword/tag-based context implementation."""

    def __init__(
        self,
        persist_store: PersistStore | None = None,
        embedding_model: Embeddings | None = None,
    ) -> None:
        self._entries: list[ContextEntry] = []
        self._persist_store = persist_store
        self._retrieval_module = ContextRetrievalModule(embedding_model)

    async def ingest(self, entry: ContextEntry) -> None:
        self._entries.append(entry)

    async def project(self, query: str, token_budget: int) -> ContextProjection:
        # Keyword matching + importance ranking
        relevant_entries = self._filter_by_tags(query)
        ranked_entries = self._rank_by_importance(relevant_entries)
        bounded_entries = self._truncate_to_budget(ranked_entries, token_budget)
        return ContextProjection(entries=bounded_entries, ...)

    def get_retrieval_module(self) -> ContextRetrievalModule:
        return self._retrieval_module
```

**Backend**: Keyword/tag matching
**Persistence**: JSON or RocksDB via `PersistStore`

### VectorContext

```python
class VectorContext(ContextProtocol):
    """Vector/embedding-based context implementation."""

    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        embedding_model: Embeddings,
    ) -> None:
        self._vector_store = vector_store
        self._embedding_model = embedding_model
        self._retrieval_module = ContextRetrievalModule(embedding_model)

    async def ingest(self, entry: ContextEntry) -> None:
        # Embed content + store in vector store
        vector = await self._embedding_model.embed_query(entry.content)
        await self._vector_store.insert(
            vectors=[vector],
            payloads=[entry.model_dump()],
            ids=[entry.id],
        )

    async def project(self, query: str, token_budget: int) -> ContextProjection:
        # Semantic similarity search
        query_vector = await self._embedding_model.embed_query(query)
        results = await self._vector_store.search(
            query=query,
            vector=query_vector,
            limit=20,
        )
        bounded_entries = self._truncate_to_budget(results, token_budget)
        return ContextProjection(entries=bounded_entries, ...)
```

**Backend**: VectorStoreProtocol + Embeddings
**Persistence**: Delegated to VectorStore

---

## Persistence Integration

Context persistence automatic when `context_persist_dir` configured:

```yaml
protocols:
  context:
    backend: keyword  # keyword | vector
    persist_dir: $SOOTHE_HOME/context/
    vector_store_provider: pgvector  # For vector backend
```

**SootheRunner integration**:
- `context.restore(thread_id)` during pre-stream when resuming thread
- `context.persist(thread_id)` during post-stream after ingestion

---

## Usage Patterns

### Goal-Centric Retrieval

```python
# AgentLoop uses retrieval module for goal-centric context
context = agent.soothe_context
retrieval = context.get_retrieval_module()
relevant_history = retrieval.retrieve_by_goal_relevance(
    goal_id="perf_analysis",
    execution_context={"iteration": 3},
    limit=10,
)

# Build task package with goal-centric context
task_package = TaskPackage(
    goal_context=goal_context_manager.get_execute_briefing(),
    execution_history=relevant_history,
    ...
)
```

### Subagent Delegation

```python
# Project scoped context for subagent
projection = await context.project_for_subagent(
    goal=subagent_task,
    token_budget=2000,
)

# Subagent receives bounded projection (not full ledger)
subagent_config = {
    "context_briefing": projection,
    ...
}
```

---

## Configuration

```yaml
protocols:
  context:
    enabled: true
    backend: keyword  # keyword | vector
    persist_dir: $SOOTHE_HOME/context/

    retrieval:
      algorithm_version: v1_keyword  # v1_keyword | v2_embedding | hybrid
      embedding_role: embedding  # Model role for embedding-based retrieval

  vector_store:  # For vector backend
    provider: pgvector
    config: {...}
```

---

## Implementation Status

- ✅ ContextProtocol interface (defined in this RFC)
- ✅ ContextEntry data model (defined in this RFC)
- ✅ ContextProjection bounded view (defined in this RFC)
- ⚠️ KeywordContext implementation (not yet implemented - critical gap)
- ⚠️ VectorContext implementation (future work)
- ✅ ContextRetrievalModule stable API (design documented - RFC-400 §128-191)
- ⚠️ Goal-centric retrieval v1_keyword (not yet implemented)
- ⚠️ v2_embedding algorithm (future work)
- ⚠️ Persistence integration (not yet implemented)
- ⚠️ AgentLoop integration (not yet implemented)
- ⚠️ Evidence storage pattern (not yet implemented)

---

## References

- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture (original Module 1)
- RFC-402: MemoryProtocol Architecture
- RFC-408: DurabilityProtocol Architecture

---

## Changelog

### 2026-04-17
- Consolidated RFC-001 Module 1 (ContextProtocol) with ContextRetrievalModule enhancement from IG-184
- Added goal-centric retrieval stable API with algorithm evolution capability
- Defined v1_keyword, v2_embedding, hybrid algorithm versions
- Maintained unbounded knowledge accumulator principle
- Preserved all implementation details and configuration

---

*ContextProtocol unbounded knowledge accumulator with goal-centric retrieval module providing stable API for algorithm evolution.*