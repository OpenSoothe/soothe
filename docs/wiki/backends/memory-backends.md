# Memory Backends

MemoryProtocol implementations for cross-thread persistent memory.

---

## Overview

Memory backends implement `MemoryProtocol` for storing and retrieving knowledge that persists across conversation threads. Unlike context (within-thread), memory survives thread boundaries and provides long-term knowledge accumulation.

---

## MemoryProtocol Interface

### Core Operations

```python
class MemoryProtocol(Protocol):
    """Cross-thread long-term memory."""
    
    async def remember(self, item: MemoryItem) -> str:
        """Store a memory item."""
        
    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Recall memories by query."""
        
    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]:
        """Recall memories by tags."""
        
    async def forget(self, item_id: str) -> bool:
        """Remove a memory."""
        
    async def update(self, item_id: str, content: str) -> None:
        """Update memory content."""
```

---

## Available Backends

### MemUMemory

LLM-powered semantic memory with embeddings and intelligent clustering.

#### Features

- **Semantic Recall**: Query memories by semantic similarity
- **LLM Integration**: Uses LLM for memory clustering and suggestions
- **Embedding Support**: Automatic embedding generation for memories
- **Tag-based Recall**: Retrieve memories by tags
- **Theory of Mind**: Advanced memory relationship detection
- **Auto-memorization**: Automatically stores significant responses

#### Architecture

```
MemUMemory Backend Architecture
├─ LLM Adapter
│  ├─ Chat model for clustering/suggestions
│  ├─ Embedding model for semantic search
│  └─ LangChain integration
│
├─ Memory Store
│  ├─ File-based persistence
│  ├─ Memory agent for management
│  ├─ Recall agent for retrieval
│  └─ Embedding cache
│
├─ Memory Actions
│  ├─ Add activity memory
│  ├─ Cluster memories
│  ├─ Generate suggestions
│  ├─ Link related memories
│  ├─ Theory of mind analysis
│  └─ Update with suggestions
│
└─ Configuration
   ├─ Memory directory
   ├─ Agent ID
   ├─ User ID
   ├─ LLM client
   └─ Embedding enable
```

#### Implementation

```python
class MemUMemory(MemoryProtocol):
    """MemoryProtocol implementation wrapping MemuMemoryStore."""
    
    def __init__(self, config: SootheConfig):
        """Initialize MemU memory backend."""
        
        # Create LLM adapter from LangChain models
        chat_model = config.create_chat_model(config.agent.protocols.memory.llm_chat_role)
        embedding_model = config.create_embedding_model()
        
        llm_adapter = LangChainLLMAdapter(
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
        
        # Resolve memory directory
        memory_dir = Path(config.agent.protocols.memory.persist_dir or "~/.soothe/memory")
        
        # Create MemuMemoryStore
        self._store = MemuMemoryStore(
            memory_dir=str(memory_dir),
            agent_id=config.agent.name,
            user_id="default_user",
            llm_client=llm_adapter,
            enable_embeddings=True,
        )
    
    async def remember(self, item: MemoryItem) -> str:
        """Store a memory item."""
        # Convert to MemU format
        memu_item = convert_to_memu_format(item)
        
        # Store with embeddings
        item_id = await self._store.add_memory(memu_item)
        
        return item_id
    
    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Recall memories by query."""
        # Semantic search
        memu_items = await self._store.search_memories(query, limit=limit)
        
        # Convert to Soothe format
        items = [convert_to_soothe_format(item) for item in memu_items]
        
        return items
```

#### Configuration

```yaml
protocols:
  memory:
    enabled: true
    backend: memu              # MemUMemory backend
    
    # Persistence
    persist_dir: ~/.soothe/memory  # Memory storage directory
    
    # LLM integration
    llm_chat_role: fast        # Chat model for clustering/suggestions
    llm_embed_role: embedding  # Embedding model for semantic search
    
    # Features
    enable_embeddings: true    # Enable embedding generation
    enable_clustering: true    # Enable memory clustering
    enable_suggestions: true   # Enable suggestion generation
```

#### Usage Example

```python
from soothe.backends.memory import MemUMemory
from soothe.protocols.memory import MemoryItem
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("config.yml")
memory = MemUMemory(config)

# Remember a memory
item = MemoryItem(
    content="User prefers concise responses",
    tags=["user_preference", "communication"],
    importance=0.8
)
item_id = await memory.remember(item)

# Recall memories
memories = await memory.recall("user preferences", limit=5)

# Recall by tags
tagged_memories = await memory.recall_by_tags(["user_preference"], limit=10)

# Update memory
await memory.update(item_id, "User prefers concise responses with code examples")

# Forget memory
await memory.forget(item_id)
```

---

## Memory Data Model

### MemoryItem

Memory items store structured knowledge:

```python
class MemoryItem(BaseModel):
    """Memory item data model."""
    
    id: str                          # Unique identifier
    content: str                     # Memory content
    source_thread: str               # Origin thread ID
    created_at: datetime             # Creation timestamp
    tags: list[str] = []             # Classification tags
    importance: float = 0.5          # Importance score (0-1)
    metadata: dict[str, Any] = {}    # Additional metadata
```

---

## Auto-Memorization

### Integration with SootheRunner

SootheRunner automatically stores significant responses:

```python
async def post_stream_processing(self, response: str):
    """Post-stream processing."""
    
    # Auto-memorize significant responses (>50 chars)
    if len(response) > 50:
        item = MemoryItem(
            content=response,
            source_thread=self.thread_id,
            tags=["auto-memorized"],
            importance=self._calculate_importance(response)
        )
        
        await self.memory.remember(item)
```

---

## Performance Characteristics

### MemUMemory Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `remember()` | ~500-1000ms | LLM calls for clustering, embedding generation |
| `recall()` | ~100-200ms | Embedding generation + search |
| `recall_by_tags()` | ~50-100ms | Tag-based filtering |
| `update()` | ~500-1000ms | LLM processing |
| `forget()` | ~10-20ms | File deletion |

### Optimization Tips

- **Batch Operations**: Group multiple `remember()` calls
- **Embedding Caching**: Cache embeddings for repeated queries
- **Selective Memorization**: Only memorize significant content
- **Tag Optimization**: Use meaningful, consistent tags

---

## Persistence

### File Structure

Memories are stored in files:

```
~/.soothe/memory/
├─ agent_id/
│  ├─ memories/
│  │  ├─ memory_001.json
│  │  ├─ memory_002.json
│  │  └─ ...
│  ├─ embeddings/
│  │  ├─ embeddings_cache.json
│  │  └─ ...
│  ├─ clusters/
│  │  ├─ cluster_data.json
│  │  └─ ...
│  ├─ suggestions/
│  │  ├─ suggestions.json
│  │  └─ ...
│  └─ index.json         # Memory index
```

### Memory File Format

```json
{
  "id": "mem_abc123",
  "content": "User prefers concise responses",
  "source_thread": "thread_xyz",
  "created_at": "2026-06-06T10:30:00Z",
  "tags": ["user_preference", "communication"],
  "importance": 0.8,
  "metadata": {
    "embedding": [0.1, 0.2, ...],
    "cluster_id": "cluster_001",
    "related_memories": ["mem_def456"]
  }
}
```

---

## Advanced Features

### Memory Clustering

Automatic clustering groups related memories:

```python
await memory._store.cluster_memories()

# Clusters contain:
# - Related memories by semantic similarity
# - Common themes and patterns
# - Temporal relationships
```

### Theory of Mind

Advanced relationship detection:

```python
await memory._store.run_theory_of_mind()

# Analysis includes:
# - User intent understanding
# - Behavioral patterns
# - Preference evolution
# - Contextual relationships
```

### Suggestion Generation

Proactive memory suggestions:

```python
await memory._store.generate_suggestions()

# Suggestions include:
# - Related topics to explore
# - Memory gaps to fill
# - Importance updates
# - Tag refinements
```

---

## Comparison Table

### Memory Backend Comparison

| Feature | MemUMemory |
|---------|-----------|
| Storage Type | File-based |
| Search Type | Semantic + Tag |
| LLM Integration | ✅ |
| Embeddings | ✅ |
| Clustering | ✅ |
| Suggestions | ✅ |
| Theory of Mind | ✅ |
| Async Operations | ✅ |
| External Dependencies | LLM models, embedding models |

---

## Error Handling

### Common Errors

```python
try:
    await memory.remember(item)
except MemoryBackendError as e:
    logger.error(f"Memory backend error: {e}")
    
    # Handle specific errors:
    if "embedding_failed" in str(e):
        # Retry without embeddings
        await memory.remember(item_without_embedding)
    
    elif "llm_error" in str(e):
        # Fallback to simple storage
        await memory._store.add_memory_simple(item)
```

---

## Integration with Context

### Memory → Context Flow

Memories are automatically ingested into context:

```python
async def pre_stream_processing(self):
    """Pre-stream processing."""
    
    # Recall relevant memories
    memories = await self.memory.recall(self.goal, limit=5)
    
    # Ingest into context
    for memory in memories:
        entry = ContextEntry(
            source="memory",
            content=memory.content,
            tags=memory.tags,
            importance=memory.importance
        )
        await self.context.ingest(entry)
```

---

## Testing

### Unit Testing

```python
import pytest

@pytest.mark.asyncio
async def test_memu_memory():
    """Test MemU memory backend."""
    config = create_test_config()
    memory = MemUMemory(config)
    
    # Test remember
    item = MemoryItem(content="test", tags=["test"])
    item_id = await memory.remember(item)
    assert item_id is not None
    
    # Test recall
    items = await memory.recall("test", limit=5)
    assert len(items) > 0
    
    # Test recall by tags
    items = await memory.recall_by_tags(["test"])
    assert len(items) > 0
    
    # Test forget
    result = await memory.forget(item_id)
    assert result is True
```

---

## Configuration Examples

### Basic Configuration

```yaml
protocols:
  memory:
    enabled: true
    backend: memu
    persist_dir: ~/.soothe/memory
```

### Advanced Configuration

```yaml
protocols:
  memory:
    enabled: true
    backend: memu
    persist_dir: ~/.soothe/memory
    
    # LLM settings
    llm_chat_role: fast
    llm_embed_role: embedding
    
    # Feature flags
    enable_embeddings: true
    enable_clustering: true
    enable_suggestions: true
    enable_theory_of_mind: true
    
    # Performance tuning
    batch_size: 10
    embedding_cache_size: 1000
```

---

## Related Documentation

- **[Backends Overview](README.md)** - Backend layer introduction
- **[Durability Backends](durability-backends.md)** - Thread lifecycle
- **[Vector Store Backends](vector-store-backends.md)** - Semantic search
- **[Context Protocol](../architecture/protocols.md#context)** - Context integration
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Memory protocol spec

---

## API Reference

### MemUMemory Class

```python
class MemUMemory(MemoryProtocol):
    """MemoryProtocol implementation wrapping MemuMemoryStore."""
    
    def __init__(self, config: SootheConfig) -> None: ...
    
    async def remember(self, item: MemoryItem) -> str: ...
    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]: ...
    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]: ...
    async def forget(self, item_id: str) -> bool: ...
    async def update(self, item_id: str, content: str) -> None: ...
```

---

## See Also

- **[Memory Protocol](../architecture/protocols.md)** - Protocol definition
- **[Protocol Resolver](../core/resolver.md)** - Backend resolution
- **[Context System](../core/context.md)** - Context integration