# Memory Backends

Cross-thread long-term memory via `MemoryProtocol`. Unlike context (which is within-thread and ephemeral), memory survives thread boundaries and accumulates knowledge across conversations. Memory backends provide the semantic recall that makes Soothe agents *learn* from past interactions.

---

## What Memory Backends Do

Memory backends store, retrieve, and organize knowledge that persists across conversation threads. The core operations are:

- **`remember()`** — Store a memory item with content, tags, importance score, and source thread.
- **`recall()`** — Retrieve memories by semantic similarity to a query string.
- **`recall_by_tags()`** — Retrieve memories matching specific tags (faster, no embedding needed).
- **`update()`** — Modify memory content (triggers re-processing).
- **`forget()`** — Remove a memory permanently.

The critical distinction: memory is *semantic* (query by meaning, not exact keywords) and *persistent* (survives thread completion). When a thread is archived, its significant interactions are consolidated into memory.

---

## Available Backends

### MemUMemory

The sole `MemoryProtocol` implementation — an LLM-powered semantic memory store with embeddings, clustering, and theory-of-mind analysis.

**What it does**: Wraps `MemuMemoryStore` (an internal memU implementation) and adapts it to `MemoryProtocol`. Every `remember()` call generates an embedding for the content; every `recall()` computes query embeddings and searches by similarity.

**Key capabilities**:
- **Semantic recall**: Queries match by meaning, not keywords. Powered by embedding vectors.
- **LLM-driven clustering**: Automatically groups related memories into clusters, surfacing common themes and temporal relationships.
- **Theory of mind**: Analyzes user intent, behavioral patterns, preference evolution, and contextual relationships across memories.
- **Proactive suggestions**: Generates suggestions for related topics, memory gaps, and tag refinements.
- **Auto-memorization**: SootheRunner automatically stores significant responses (>50 chars) with computed importance scores.
- **Tag-based recall**: Fast filtering without embedding computation (~50-100ms vs ~100-200ms for semantic).

**When to use**: This is the only memory backend — use it whenever cross-thread memory is enabled. The decision is *whether* to enable memory, not *which* backend to choose.

**Minimal config**:
```yaml
protocols:
  memory:
    enabled: true
    backend: memu
    persist_dir: ~/.soothe/memory
    llm_chat_role: fast        # for clustering/suggestions
    llm_embed_role: embedding  # for semantic search
```

Source: `packages/soothe/src/soothe/backends/memory/memu_adapter.py`

---

## Architecture & Data Flow

MemUMemory composes three layers:

1. **LLM Adapter** (`LangChainLLMAdapter`) — Bridges LangChain chat and embedding models to the memU store. The chat model handles clustering and suggestion generation; the embedding model generates vectors for semantic search.

2. **Memory Store** (`MemuMemoryStore`) — File-based persistence with an embedding cache. Stores memories as JSON files organized by agent ID, with separate directories for memories, embeddings, clusters, and suggestions.

3. **Memory Actions** — Background operations: add activity memory, cluster memories, generate suggestions, link related memories, theory-of-mind analysis, and update with suggestions.

**Recall flow**: Query → generate embedding → similarity search over stored embeddings → return ranked memories. The embedding cache avoids regenerating embeddings for repeated queries.

**Integration with context**: Before each stream, SootheRunner recalls relevant memories (via `recall(goal, limit=5)`) and ingests them into the thread's context as `ContextEntry` objects with source=`memory`.

---

## Performance Characteristics

| Operation | Latency | Bottleneck |
|-----------|---------|------------|
| `remember()` | ~500-1000ms | LLM calls (clustering) + embedding generation |
| `recall()` | ~100-200ms | Embedding generation + similarity search |
| `recall_by_tags()` | ~50-100ms | Tag filtering only (no embeddings) |
| `update()` | ~500-1000ms | LLM re-processing |
| `forget()` | ~10-20ms | File deletion |

**`remember()` is expensive** because it may trigger LLM clustering and suggestion generation. Batch multiple `remember()` calls where possible, and use selective memorization (only significant content).

---

## Production Gotchas

1. **LLM dependency**: Memory operations require both a chat model and an embedding model. If LLM services are unavailable, `remember()` fails. Consider a fallback to simple storage (without clustering) on LLM errors.

2. **Latency on first recall**: The first `recall()` after startup may be slower as the embedding cache warms up. Subsequent recalls with similar queries benefit from caching.

3. **File-based storage**: Memories persist as JSON files under `persist_dir`. There is no database backend — large memory stores (10,000+ items) may experience degraded listing performance. Monitor the `index.json` size.

4. **User ID scoping**: `MemuMemoryStore` scopes memories by `user_id`, which is set to the thread's `source_thread` on each `remember()` call. Ensure consistent ID usage to avoid fragmenting memories across scopes.

5. **No built-in memory limits**: Memories accumulate without automatic pruning. Use `forget()` for explicit cleanup, or implement importance-based eviction.

6. **Embedding dimension must match**: The embedding model's vector dimension is fixed at store creation. Switching embedding models requires re-generating all stored embeddings.

---

## Optimization Tips

- **Batch `remember()` calls** to amortize LLM clustering overhead.
- **Cache embeddings** for repeated queries (built into MemuMemoryStore).
- **Use `recall_by_tags()`** when you know the category — it's 2-4× faster than semantic recall.
- **Use meaningful, consistent tags** — they enable fast filtering and cluster organization.
- **Selective memorization**: Only store content above an importance threshold. SootheRunner auto-memorizes responses >50 chars; tune this threshold for your use case.

---

## Related Documentation

- **[Backends Overview](README.md)** — Backend layer introduction
- **[Vector Store Backends](vector-store-backends.md)** — Semantic search engine
- **[Durability Backends](durability-backends.md)** — Triggers memory consolidation on archive
- **[Context System](../core/context.md)** — Where recalled memories are ingested
