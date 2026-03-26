# Skillify Agent Implementation Guide

**Guide**: IG-011
**Title**: Skillify Agent Implementation
**Created**: 2026-03-13
**Related RFCs**: RFC-0001, RFC-0002, RFC-0003, RFC-0004

## Overview

This guide describes how to implement the Skillify agent as a Soothe-compatible CompiledSubAgent with a background indexing loop and a retrieval-only LangGraph. It translates RFC-0004 into concrete implementation steps, file organization, and API signatures.

## Prerequisites

- [x] RFC-0004 (Skillify Architecture Design)
- [x] VectorStoreProtocol implemented (IG-006)
- [x] SootheConfig with SkillifyConfig section (Phase 5 wiring)
- [x] Embedding model configured via model router

## File Structure

```text
src/soothe/subagents/skillify/
  __init__.py       # create_skillify_subagent() factory, LangGraph, indexer lifecycle
  models.py         # SkillRecord, SkillSearchResult, SkillBundle
  warehouse.py      # SkillWarehouse: scan, parse SKILL.md, compute hashes
  indexer.py         # SkillIndexer: background asyncio.Task, embed + upsert
  retriever.py       # SkillRetriever: embed query, search, rank
```

## Module APIs

### models.py

```python
class SkillRecord(BaseModel):
    id: str
    name: str
    description: str
    path: str
    tags: list[str] = []
    status: Literal["indexed", "stale", "error"] = "indexed"
    indexed_at: datetime
    content_hash: str

class SkillSearchResult(BaseModel):
    record: SkillRecord
    score: float

class SkillBundle(BaseModel):
    query: str
    results: list[SkillSearchResult]
    total_indexed: int
```

### warehouse.py

```python
class SkillWarehouse:
    def __init__(self, paths: list[str]) -> None: ...

    def scan(self) -> list[SkillRecord]:
        """Scan all warehouse paths and return SkillRecords.

        For each directory containing SKILL.md:
        1. Parse YAML frontmatter for name, description, tags
        2. Compute SHA-256 of SKILL.md content -> content_hash
        3. Compute deterministic id from absolute path
        """
        ...

    @staticmethod
    def parse_skill_md(path: Path) -> tuple[dict, str]:
        """Parse SKILL.md into (frontmatter_dict, body_text)."""
        ...

    @staticmethod
    def content_hash(content: str) -> str:
        """SHA-256 hex digest of content."""
        ...
```

### indexer.py

```python
class SkillIndexer:
    def __init__(
        self,
        warehouse: SkillWarehouse,
        vector_store: VectorStoreProtocol,
        embeddings: Embeddings,
        interval_seconds: int = 300,
        collection: str = "soothe_skillify",
        embedding_dims: int = 1536,
    ) -> None: ...

    async def start(self) -> None:
        """Start the background indexing loop as an asyncio.Task."""
        ...

    async def stop(self) -> None:
        """Cancel the background task and wait for cleanup."""
        ...

    async def run_once(self) -> dict[str, int]:
        """Run a single indexing pass. Returns {"new": N, "changed": N, "deleted": N}."""
        # 1. warehouse.scan() -> current records
        # 2. Compare content_hash with stored _hash_cache
        # 3. For new/changed: embed and upsert
        # 4. For deleted (in cache but not on disk): delete from vector store
        # 5. Update _hash_cache
        ...

    async def _index_loop(self) -> None:
        """Perpetual loop: run_once() then sleep(interval)."""
        ...
```

### retriever.py

```python
class SkillRetriever:
    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        embeddings: Embeddings,
        top_k: int = 10,
    ) -> None: ...

    async def retrieve(self, query: str) -> SkillBundle:
        """Embed query, search vector store, return ranked SkillBundle."""
        # 1. Generate embedding for query
        # 2. vector_store.search(query, vector, limit=top_k)
        # 3. Map VectorRecords to SkillSearchResults
        # 4. Assemble SkillBundle
        ...
```

### __init__.py

```python
def create_skillify_subagent(
    model: str | BaseChatModel | None = None,
    *,
    config: SootheConfig | None = None,
    **kwargs: Any,
) -> CompiledSubAgent:
    """Create Skillify CompiledSubAgent with background indexer.

    1. Resolve warehouse paths from config
    2. Create VectorStore, Embeddings from config
    3. Create SkillWarehouse, SkillIndexer, SkillRetriever
    4. Start background indexer
    5. Build retrieval LangGraph
    6. Return CompiledSubAgent with runnable
    """
    ...
```

LangGraph structure:

```python
class SkillifyState(dict):
    messages: Annotated[list, add_messages]

def _build_skillify_graph(retriever: SkillRetriever) -> CompiledGraph:
    # Nodes: parse_query -> retrieve -> format_response
    # parse_query: extract query text from messages[-1].content
    # retrieve: call retriever.retrieve(query)
    # format_response: serialize SkillBundle as AIMessage
    ...
```

## Wiring Steps

1. **config.py**: Add `SkillifyConfig` to `SootheConfig` (see Phase 5)
2. **agent.py**: Add `"skillify": create_skillify_subagent` to `_SUBAGENT_FACTORIES`; pass `config=config` in factory kwargs
3. **subagents/__init__.py**: Export `create_skillify_subagent`
4. **config.py default subagents**: Add `"skillify": SubagentConfig(enabled=False)`

## Background Loop Lifecycle

- `create_skillify_subagent()` starts the indexer via `indexer.start()`
- The indexer reference is stored on the CompiledSubAgent dict as `_skillify_indexer` for external stop access
- `SootheRunner` or agent cleanup should call `indexer.stop()` on shutdown
- First indexing pass runs immediately (no initial delay)
- Subsequent passes run after `index_interval_seconds` sleep
- Errors in individual skill indexing are logged and skipped (graceful degradation)

## Testing Strategy

### Unit Tests

- `SkillWarehouse.scan()` with fixture directories containing valid/invalid SKILL.md
- `SkillWarehouse.parse_skill_md()` with various frontmatter formats
- `SkillIndexer.run_once()` with mocked VectorStore and Embeddings
- `SkillRetriever.retrieve()` with mocked VectorStore search results
- Change detection: verify only new/changed skills are re-embedded

### Integration Tests

- End-to-end: seed warehouse, start indexer, wait for pass, query retriever, verify results
- Graceful degradation: retriever returns empty bundle when index unavailable

## Verification Checklist

- [ ] Skillify is routable as a Soothe CompiledSubAgent
- [ ] Background indexer starts on creation and stops cleanly
- [ ] Only changed skills are re-embedded (hash-based diff)
- [ ] Retrieval returns ranked SkillBundle with correct scores
- [ ] Custom events for index/retrieve are emitted
- [ ] Graceful degradation when vector store is unavailable

## Related Documents

- [RFC-0004](../specs/RFC-0004.md) -- Skillify Architecture Design
- [IG-006](./006-vectorstore-router-persistence.md) -- VectorStore, Router, Persistence
