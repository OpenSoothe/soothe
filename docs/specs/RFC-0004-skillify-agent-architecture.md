# RFC-0004: Skillify Agent Architecture Design

**RFC**: 0004
**Title**: Skillify Agent Architecture Design
**Status**: Implemented
**Created**: 2026-03-13
**Updated**: 2026-03-27
**Related**: RFC-0001, RFC-0002, RFC-0003

## Abstract

This RFC defines the architecture of the Skillify agent, a Soothe-compatible subagent responsible for skill warehouse indexing and semantic retrieval. Skillify operates as two decoupled runtime concerns: a **background indexing loop** that continuously curates a vector index of SKILL.md-compliant skill packages, and a **retrieval CompiledSubAgent** that serves on-demand skill bundles for user goals or downstream agents (notably Weaver).

## Motivation

The current Soothe stack can use skills through deepagents `SkillsMiddleware`, but it lacks a subsystem that semantically indexes and retrieves skills from a large, heterogeneous warehouse. A dedicated Skillify architecture enables:

- Semantic retrieval of relevant skills for downstream planning, execution, and agent generation
- Background indexing that keeps the vector store in sync with a growing warehouse without user intervention
- Durable provenance and lifecycle metadata for every indexed skill
- Policy-governed access to external or restricted skills
- Decoupling of warehouse curation from retrieval so each can evolve independently

## Design Principles

### Background indexing, foreground retrieval

Indexing runs as an autonomous background `asyncio.Task` on a configurable interval. It scans, hashes, embeds, and upserts without any user request. The CompiledSubAgent graph handles only retrieval, keeping the subagent response path fast and deterministic.

### Hash-based change detection

Each skill's content is SHA-256 hashed. On each indexing pass, only skills whose hash differs from the stored hash are re-embedded, minimizing embedding API calls and vector store writes. Skill identifiers are derived deterministically from the absolute path using a truncated SHA-256 hex digest.

### Protocol-first integration

Skillify depends on `VectorStoreProtocol` for storage and search, `PolicyProtocol` for access control, and `Embeddings` (langchain) for embedding generation. All are injected via `SootheConfig`, not hard-coded.

### Reuse deepagents skill format

Skill packages MUST comply with deepagents `SkillsMiddleware` format: a directory containing `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown body. Skillify reads this format but does not modify warehouse contents.

## Data Models

```python
class SkillRecord(BaseModel):
    """Metadata for a single indexed skill."""
    id: str                        # deterministic: first 16 hex chars of SHA-256(path)
    name: str                      # from SKILL.md frontmatter
    description: str               # from SKILL.md frontmatter
    path: str                      # absolute filesystem path to skill directory
    tags: list[str] = []           # from SKILL.md frontmatter (optional)
    status: Literal["indexed", "stale", "error"] = "indexed"
    indexed_at: datetime
    content_hash: str              # SHA-256 of SKILL.md content

class SkillSearchResult(BaseModel):
    """A single result from a retrieval query."""
    record: SkillRecord
    score: float                   # cosine similarity [0, 1]

class SkillBundle(BaseModel):
    """Response payload for a retrieval request."""
    query: str
    results: list[SkillSearchResult]
    total_indexed: int
```

## Architecture

### Background Indexing Loop

The `SkillIndexer` class manages a perpetual indexing loop as an `asyncio.Task`:

```
┌──────────────────────────────────────────────────────────┐
│  SkillIndexer (asyncio.Task)                             │
│                                                          │
│  loop:                                                   │
│    1. ensure_collection() / bootstrap_hash_cache()       │
│    2. SkillWarehouse.scan() → list[SkillRecord]          │
│    3. For each record:                                   │
│       a. Compare content_hash with cached hash           │
│       b. If changed or new: embed → upsert VectorStore   │
│    4. Delete vector records no longer present on disk    │
│    5. Emit soothe.subagent.skillify.* index events       │
│    6. Sleep(index_interval_seconds)                      │
│                                                          │
│  Lifecycle: start() / stop() / run_once()                │
└──────────────────────────────────────────────────────────┘
```

The indexer holds an in-memory dict mapping `skill_id → content_hash` for fast diff. On startup it ensures the configured collection exists, bootstraps its hash cache from `VectorStoreProtocol.list_records()`, and marks readiness after the first successful pass.

### Retrieval CompiledSubAgent

The retrieval graph is exposed as a `CompiledSubAgent`, but the compiled LangGraph currently contains a single `retrieve` node:

```
[START] → retrieve → [END]
```

That `retrieve` node performs the full retrieval path internally:

- extracts the retrieval objective from the incoming message history
- emits progress events
- waits briefly for initial indexing readiness when needed
- generates the query embedding with the configured embedding model
- calls `VectorStoreProtocol.search()`
- maps vector records back to `SkillSearchResult` objects
- formats the returned `SkillBundle` as an `AIMessage`

State schema:

```python
class SkillifyState(dict):
    messages: Annotated[list, add_messages]
```

### Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| `SkillWarehouse` | `warehouse.py` | Scan configured directories, parse SKILL.md frontmatter, compute content hashes and deterministic path IDs |
| `SkillIndexer` | `indexer.py` | Background loop, collection/bootstrap readiness, change detection, embed + upsert/delete via VectorStoreProtocol |
| `SkillRetriever` | `retriever.py` | Policy-check retrieval requests, wait for readiness, embed query, search VectorStore, and assemble results |
| `create_skillify_subagent` | `__init__.py` | Build the single-node retrieval LangGraph, start background indexer when an event loop is running, return CompiledSubAgent |
| Data models | `models.py` | `SkillRecord`, `SkillSearchResult`, `SkillBundle` |
| Events | `events.py` | Skillify retrieval/index progress events under `soothe.subagent.skillify.*` |

## Filesystem Layout

```
~/.soothe/agents/skillify/
  warehouse/                    # canonical skill artifacts (user-managed)
    skill-name-1/
      SKILL.md
      ...
    skill-name-2/
      SKILL.md
      ...
```

Additional warehouse paths can be configured via `skillify.warehouse_paths[]`. The default path is `~/.soothe/agents/skillify/warehouse/`.

## Integration Contracts

### VectorStoreProtocol

- Collection name: `soothe_skillify` (configurable)
- Vector payload: `{"skill_id": str, "name": str, "description": str, "path": str, "tags": list[str], "content_hash": str}`
- Embedding input: concatenation of skill name, description, and first 500 chars of SKILL.md body
- Vector dimensions: from `SootheConfig.embedding_dims`

### PolicyProtocol

- Retrieval requests are checked with action type `skillify_retrieve`
- The current retriever passes the query through `PolicyProtocol` before search
- Warehouse-path allowlisting is defined by configured scan roots, but the retriever/indexer does not perform a separate path-review policy pass beyond normal retrieval policy checks

### Embedding Model

- Uses `SootheConfig.create_embedding_model()` (the `embedding` role from the model router)

## Configuration Surface

```python
class SkillifyConfig(BaseModel):
    enabled: bool = False
    warehouse_paths: list[str] = []   # additional paths beyond default
    index_interval_seconds: int = 300
    index_collection: str = "soothe_skillify"
    retrieval_top_k: int = 10
```

Default warehouse path: `SOOTHE_HOME / "agents" / "skillify" / "warehouse"` (always included).

## Observability

Custom stream events emitted by Skillify:

| Event Type | Fields | When |
|------------|--------|------|
| `soothe.subagent.skillify.index_started` | `collection` | Background indexing is started |
| `soothe.subagent.skillify.index_updated` | `new`, `changed`, `deleted`, `total` | An indexing pass completes with changes |
| `soothe.subagent.skillify.index_unchanged` | `total` | An indexing pass completes with no changes |
| `soothe.subagent.skillify.index_failed` | standard event envelope only | Indexing startup or pass fails |
| `soothe.subagent.skillify.indexing_pending` | `query` | Retrieval arrives before the first index pass is ready |
| `soothe.subagent.skillify.retrieve_started` | `query` | Retrieval request received |
| `soothe.subagent.skillify.retrieve_completed` | `query`, `result_count`, `top_score` | Results returned |
| `soothe.subagent.skillify.retrieve_not_ready` | `message` | Retrieval returns an indexing-in-progress message after bounded wait |

## Architectural Constraints

- Skillify MUST run as a Soothe `CompiledSubAgent` (retrieval graph) plus a background `asyncio.Task` (indexer).
- Skill packages MUST be deepagents-compatible (`SKILL.md` with YAML frontmatter).
- Indexing MUST use Soothe vector store abstractions (`VectorStoreProtocol`).
- Embedding MUST use the configured langchain `Embeddings` model.
- The background loop MUST be stoppable for clean shutdown.
- Retrieval SHOULD degrade gracefully by returning either an informative indexing-in-progress message or an empty bundle when embedding/search fails.

## Dependencies

- RFC-0001 (System Conceptual Design)
- RFC-0002 (Core Modules Architecture Design) -- VectorStoreProtocol, PolicyProtocol
- RFC-0003 (CLI TUI Architecture Design) -- stream event format

## Related Documents

- [RFC-0001](./RFC-0001.md)
- [RFC-0002](./RFC-0002.md)
- [RFC-0003](./RFC-0003.md)
- [RFC-0005](./RFC-0005.md) -- Weaver (primary consumer of Skillify retrieval)
- [IG-011](../impl/011-skillify-agent-implementation.md)
