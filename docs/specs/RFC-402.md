# RFC-402: MemoryProtocol Architecture

**RFC**: 402
**Title**: MemoryProtocol: Cross-Thread Memory & Context Separation
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Dependencies**: RFC-000, RFC-400
**Related**: RFC-408 (Durability)

---

## Abstract

This RFC defines MemoryProtocol, Soothe's cross-thread long-term memory for persistent knowledge surviving beyond single thread execution. MemoryProtocol provides explicit knowledge population through `remember()` operations, semantic recall via query or tags, and clear separation from ContextProtocol (within-thread unbounded accumulator). MemoryProtocol integrates with ContextProtocol at thread lifecycle boundaries.

---

## Protocol Interface

```python
class MemoryProtocol(Protocol):
    """Cross-thread long-term memory protocol."""

    async def remember(self, item: MemoryItem) -> str:
        """Store important knowledge explicitly."""
        ...

    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Recall knowledge by semantic relevance."""
        ...

    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]:
        """Recall knowledge by tag filtering."""
        ...

    async def forget(self, item_id: str) -> bool:
        """Remove knowledge item."""
        ...

    async def update(self, item_id: str, content: str) -> None:
        """Update knowledge content."""
        ...
```

---

## Data Models

### MemoryItem

```python
class MemoryItem(BaseModel):
    """Cross-thread memory knowledge item."""
    id: str
    """Unique identifier."""
    content: str
    """Knowledge content."""
    source_thread: str
    """Thread where knowledge was learned."""
    created_at: datetime
    """Creation timestamp."""
    tags: list[str] = []
    """Tags for categorization."""
    importance: float = 0.5
    """Importance score (0.0-1.0)."""
    metadata: dict[str, Any] = {}
    """Additional metadata."""
```

---

## Design Principles

### 1. Explicit Population

Memory explicitly populated, not auto-memorized from all context:
- Significant responses remembered (>50 chars)
- Important findings manually stored
- User explicitly marks knowledge as memorable
- Not every context entry becomes memory

### 2. Semantic Recall

Memory queryable by semantic relevance:
- `recall(query)`: Keyword or embedding-based search
- `recall_by_tags()`: Tag-based filtering
- Relevance ranking by importance + similarity
- Cross-thread knowledge aggregation

### 3. Context vs Memory Separation

**ContextProtocol** (RFC-400):
- Within-thread knowledge
- Unbounded accumulation
- Append-only ledger
- Bounded projections for LLM

**MemoryProtocol** (this RFC):
- Cross-thread knowledge
- Explicit population
- Selective storage
- Semantic recall across threads

**Integration**: Memory recalled at thread start → ingested into Context.

---

## Memory Integration Flow

### Thread Lifecycle Integration

```python
# Thread start: recall relevant memory
async def _pre_stream(thread_id: str):
    # 1. Restore context (within-thread)
    context.restore(thread_id)

    # 2. Recall memory (cross-thread)
    goal = extract_goal_from_query(query)
    relevant_memories = await memory.recall(goal, limit=5)

    # 3. Ingest memories into context
    for mem_item in relevant_memories:
        await context.ingest(ContextEntry(
            source="memory",
            content=mem_item.content,
            tags=["recalled", "cross_thread"],
            importance=mem_item.importance,
        ))

# Thread end: remember significant responses
async def _post_stream(response: str):
    # Auto-remember if significant (>50 chars)
    if len(response) > 50:
        await memory.remember(MemoryItem(
            content=response,
            source_thread=thread_id,
            importance=0.6,
        ))
```

---

## Implementations

### MemUMemory

```python
class MemUMemory(MemoryProtocol):
    """MemU memory store implementation."""

    def __init__(
        self,
        persist_dir: Path,
        chat_model: BaseChatModel,
        embed_model: Embeddings,
    ) -> None:
        self._memu_store = MemuMemoryStore(
            persist_dir=persist_dir,
            chat_model=chat_model,
            embed_model=embed_model,
        )

    async def remember(self, item: MemoryItem) -> str:
        return await self._memu_store.add_memory(
            content=item.content,
            metadata=item.metadata,
        )

    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        results = await self._memu_store.search_memory(
            query=query,
            limit=limit,
        )
        return [MemoryItem.model_validate(r) for r in results]

    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]:
        results = await self._memu_store.search_by_tags(
            tags=tags,
            limit=limit,
        )
        return [MemoryItem.model_validate(r) for r in results]
```

**Backend**: MemU memory store + configured chat/embedding models
**Persistence**: Files under `protocols.memory.persist_dir` (defaults to `$SOOTHE_HOME/memory/`)
**Features**: Semantic recall, tags, metadata

---

## Configuration

```yaml
protocols:
  memory:
    enabled: true
    persist_dir: $SOOTHE_HOME/memory/
    llm_chat_role: fast  # Model role for memory summarization
    llm_embed_role: embedding  # Model role for semantic search
```

---

## Implementation Status

- ✅ MemoryProtocol interface
- ✅ MemoryItem data model
- ✅ MemUMemory implementation
- ✅ Semantic recall (keyword + embedding)
- ✅ Tag-based recall
- ✅ Persistence integration
- ✅ Context integration at thread lifecycle
- ✅ Auto-remember significant responses (>50 chars)

---

## References

- RFC-000: System Conceptual Design
- RFC-400: ContextProtocol Architecture
- RFC-001: Core Modules Architecture (original Module 2)

---

## Changelog

### 2026-04-17
- Consolidated RFC-001 Module 2 (MemoryProtocol) with Context vs Memory separation principles from RFC-402
- Defined explicit population vs auto-memorization distinction
- Unified semantic recall with context integration flow
- Maintained cross-thread persistence and recall patterns
- Clarified ContextProtocol (within-thread) vs MemoryProtocol (cross-thread) separation

---

*MemoryProtocol cross-thread long-term memory with explicit population, semantic recall, and integration with ContextProtocol at thread lifecycle boundaries.*