# MemoryProtocol

**RFC**: 402  
**Module**: RFC-000 Module 2  
**Location**: `packages/soothe/src/soothe/protocols/memory.py`  
**Status**: Implemented  

## Overview

MemoryProtocol defines the interface for **cross-thread long-term memory** in Soothe. Unlike ContextProtocol (within-thread) and MemoryMiddleware (static AGENTS.md files), MemoryProtocol provides semantically queryable, explicitly populated long-term knowledge storage that survives beyond individual thread executions.

## Purpose

- **Cross-thread persistence**: Knowledge that should survive beyond a single thread
- **Semantic retrieval**: Query by relevance using embeddings
- **Explicit population**: Manually curated, not auto-memorized
- **Thread-scoped sources**: Track which thread created each memory item

## Protocol Interface

```python
@runtime_checkable
class MemoryProtocol(Protocol):
    """Protocol for cross-thread long-term memory.
    
    Memory is explicitly populated (not auto-memorized) and semantically
    queryable. Separate from ContextProtocol (within-thread) and
    MemoryMiddleware (static AGENTS.md files).
    """

    async def remember(self, item: MemoryItem) -> str:
        """Store a memory item.
        
        Args:
            item: The memory item to persist.
            
        Returns:
            The item's unique ID.
        """
        ...

    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Retrieve items by semantic relevance.
        
        Args:
            query: The search query.
            limit: Maximum number of items to return.
            
        Returns:
            Matching items ordered by relevance.
        """
        ...

    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]:
        """Retrieve items matching all specified tags.
        
        Args:
            tags: Tags that items must match (AND logic).
            limit: Maximum number of items to return.
            
        Returns:
            Matching items ordered by importance.
        """
        ...

    async def forget(self, item_id: str) -> bool:
        """Remove a memory item.
        
        Args:
            item_id: The item's unique ID.
            
        Returns:
            True if the item was found and removed.
        """
        ...

    async def update(self, item_id: str, content: str) -> None:
        """Update an existing memory item's content.
        
        Args:
            item_id: The item's unique ID.
            content: New content to replace the existing content.
            
        Raises:
            KeyError: If no item with the given ID exists.
        """
        ...
```

## Data Models

### MemoryItem

```python
class MemoryItem(BaseModel):
    """A unit of long-term knowledge.
    
    Args:
        id: Unique identifier (auto-generated UUID if not provided).
        content: The knowledge content (text).
        source_thread: Thread that created this item (for traceability).
        created_at: Creation timestamp (auto-generated).
        tags: Categorical tags for filtering and recall.
        importance: Priority weight from 0.0 to 1.0 (affects retrieval ranking).
        metadata: Arbitrary key-value metadata.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    source_thread: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tags: list[str] = Field(default_factory=list)
    importance: float = 0.5  # Default medium importance
    metadata: dict[str, Any] = Field(default_factory=dict)
```

**Key Fields**:
- **id**: UUID identifier for retrieval and deletion
- **content**: The actual knowledge text
- **source_thread**: Traceability to originating thread
- **importance**: Retrieval ranking weight (0.0 = low, 1.0 = critical)

## Backend Implementations

### MemUMemory

**Status**: Current implementation  
**Location**: `packages/soothe/src/soothe/backends/memory/memu_adapter.py`  
**Dependencies**: MemU internal memory store

MemUMemory adapts the internal MemU memory store to the MemoryProtocol interface. It uses configured chat and embedding model roles for intelligent memory operations.

**Features**:
- LLM-assisted memory categorization
- Configurable memory directories
- Embedding-based semantic search
- Importance-weighted retrieval
- Rich metadata support

**Configuration**:
```yaml
protocols:
  memory:
    enabled: true
    persist_dir: ~/.soothe/memory
    llm_chat_role: planner  # Model role for memory operations
    embedding_role: embedding  # Model role for embeddings
```

**Implementation Example**:
```python
class MemUMemory(MemoryProtocol):
    """MemoryProtocol implementation wrapping MemuMemoryStore."""
    
    def __init__(self, config: SootheConfig) -> None:
        # Create LLM adapter from LangChain models
        chat_model = config.create_chat_model(
            config.agent.protocols.memory.llm_chat_role
        )
        embedding_model = config.create_embedding_model()
        
        llm_adapter = LangChainLLMAdapter(
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
        
        # Resolve memory directory
        memory_dir = Path(config.agent.protocols.memory.persist_dir)
        
        # Create MemuMemoryStore
        self._store = MemuMemoryStore(
            memory_dir=str(memory_dir),
            agent_id=config.agent.name,
            user_id="default_user",
            llm_client=llm_adapter,
            enable_embeddings=True,
        )
```

### Historical Backends

**Note**: Earlier implementations included `KeywordMemory` and `VectorMemory` backends. These have been superseded by MemUMemory, which provides a unified, intelligent memory system.

## Usage Patterns

### Storing Memory

```python
from soothe.protocols import MemoryItem, MemoryProtocol

memory: MemoryProtocol = resolve_memory(config)

# Store important finding from thread
item = MemoryItem(
    content="Project uses PostgreSQL for persistence with separate databases",
    source_thread="thread_abc123",
    tags=["architecture", "database", "postgresql"],
    importance=0.8,
    metadata={"category": "technical", "verified": True}
)

item_id = await memory.remember(item)
```

### Semantic Retrieval

```python
# Retrieve relevant memories for new thread
memories = await memory.recall(
    query="database configuration",
    limit=5
)

for mem in memories:
    print(f"[{mem.importance:.2f}] {mem.content}")
    # Ingest into current thread's context
```

### Tag-Based Filtering

```python
# Retrieve all architecture-related memories
arch_memories = await memory.recall_by_tags(
    tags=["architecture"],
    limit=10
)

# Retrieve PostgreSQL-specific memories
pg_memories = await memory.recall_by_tags(
    tags=["postgresql", "database"],
    limit=5
)
```

### Memory Lifecycle

```python
# Update existing memory
await memory.update(
    item_id="mem_xyz789",
    content="Updated: Project now uses PostgreSQL 15 with connection pooling"
)

# Remove outdated memory
await memory.forget(item_id="mem_old123")
```

## Integration with Other Protocols

### Memory ↔ Context Integration

Memory and Context work together:

```
Thread A (past):
  ... work ...
  → memory.remember(findings)    ← Stored with source_thread="A"

Thread B (new):
  → memory.recall("related topic")  ← Retrieves findings from A
  → context.ingest(recalled_items)   ← Merged into current context
  ... work using recalled knowledge ...
  → memory.remember(new_findings)    ← Stored with source_thread="B"
```

**Key Differences**:
- **Context**: Within-thread, bounded projections, conversation-scoped
- **Memory**: Cross-thread, persistent indefinitely, knowledge-scoped

### Memory ↔ Durability Integration

Memory is separate from DurabilityProtocol:

- **Durability**: Thread lifecycle state (metadata, status)
- **Memory**: Knowledge content (findings, learnings)

Memory persists through MemU's own storage system, not via `AsyncPersistStore`.

## Configuration

### Memory Protocol Settings

```yaml
# config/config.template.yml
agent:
  protocols:
    memory:
      enabled: true
      persist_dir: ~/.soothe/memory  # Storage location
      llm_chat_role: planner  # LLM role for categorization
      embedding_role: embedding  # Embedding role for semantic search
```

### Resolution

```python
from soothe.core.resolver import resolve_memory

# Resolve memory protocol from config
memory = resolve_memory(config)

# Returns: MemoryProtocol implementation (MemUMemory)
```

## Testing

### Unit Tests

**Location**: `packages/soothe/tests/unit/backends/memory/test_memory_memu.py`

Tests verify:
- MemoryItem creation and storage
- Semantic recall accuracy
- Tag-based filtering
- Update and delete operations
- Thread-scoped source tracking

### Integration Tests

Memory integration tests verify:
- Cross-thread knowledge persistence
- Context ingestion after recall
- Configuration resolution
- Backend initialization

## Design Rationale

### Why Separate Memory from Context?

**RFC-000 Principle 4**: Unbounded context, bounded projection.

- **Context** is thread-scoped and conversation-focused
- **Memory** is cross-thread and knowledge-focused
- Different persistence scopes, different retrieval strategies

### Why Explicit Population?

Not every tool result should be memorized:
- Avoid noise from temporary findings
- Curate important, reusable knowledge
- Manual selection ensures quality

### Why Semantic Retrieval?

Keyword matching alone misses conceptual relationships:
- "database optimization" should find "PostgreSQL tuning"
- Embeddings capture semantic similarity
- Importance weighting prioritizes critical knowledge

## Specification Reference

- **RFC-402**: Memory Protocol Architecture (full specification)
- **RFC-300**: Context and Memory Architecture Design (superseded)
- **RFC-000**: System Conceptual Design (protocol philosophy)

## Related Documentation

- [Context Protocol](context.md) (future, not implemented yet)
- [Durability Protocol](durability.md)
- [VectorStore Protocol](vector-store.md)
- [Backend Implementation Guide](../backends.md)