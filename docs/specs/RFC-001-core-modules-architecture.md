# RFC-001: Architecture Design for Core Protocol Modules

**RFC**: 001
**Title**: Architecture Design for Core Protocol Modules
**Status**: Implemented
**Created**: 2026-03-12
**Updated**: 2026-04-17 (RFC consolidation; retrieval module canonical in RFC-400)
**Related**: RFC-000, RFC-200, RFC-400, RFC-402

## Abstract

This RFC defines the architecture for eight core protocol modules that Soothe implements beyond what deepagents and the langchain ecosystem provide. Each module follows the pattern: **protocol (abstract) -> data models (Pydantic) -> default implementation (langchain-friendly) -> integration point**.

## Module 1: ContextProtocol (Cognitive Context Engineering)

The orchestrator's knowledge accumulator. Fundamentally different from conversation history (handled by deepagents' SummarizationMiddleware) -- this is structured knowledge that grows without bound and gets projected into bounded windows on demand.

### Protocol

```python
class ContextProtocol(Protocol):
    async def ingest(self, entry: ContextEntry) -> None: ...
    async def project(self, query: str, token_budget: int) -> ContextProjection: ...
    async def project_for_subagent(self, goal: str, token_budget: int) -> ContextProjection: ...
    async def summarize(self, scope: str | None = None) -> str: ...
    async def persist(self, thread_id: str) -> None: ...
    async def restore(self, thread_id: str) -> bool: ...
    def get_retrieval_module(self) -> ContextRetrievalModule: ...
```

**Extended methods**: `get_retrieval_module()` and the `ContextRetrievalModule` type are fully specified in [RFC-400](./RFC-400-context-protocol-architecture.md) (canonical retrieval surface). This RFC keeps the summary above aligned with implementations that expose goal-centric retrieval.

### Data Models

- `ContextEntry(source, content, timestamp, tags, importance)` -- unit of knowledge
- `ContextProjection(entries, summary, total_entries, token_count)` -- bounded view

### Design Principles

**Consciousness Concept**: ContextProtocol implements the architectural "consciousness" pattern identified in autonomous agent design: an unbounded knowledge ledger maintaining complete execution history (success/failure experience) with bounded projections for LLM reasoning. This separation ensures the orchestrator has full knowledge access while LLMs receive token-efficient context windows.

1. **Accumulate, never discard** -- ledger is append-only and unbounded
2. **Relevance-based projection** -- entries ranked by relevance to query, not just recency
3. **Purpose-scoped projections** -- different views for orchestrator reasoning vs subagent briefing
4. **Hierarchical summarization** -- entries summarized at multiple levels
5. **Subagent isolation** -- subagents receive projections, not full context; return results only

### Goal-centric retrieval (canonical: RFC-400)

`ContextRetrievalModule`, `retrieve_by_goal_relevance(...)`, algorithm-version notes, and default wiring for `KeywordContext` / `VectorContext` are defined in **[RFC-400](./RFC-400-context-protocol-architecture.md)**. RFC-001 references that document as the **single authoritative** copy of the retrieval API to avoid schema drift.

**Typical call pattern** (Layer 2 runner or runner integration assembling Plan / Execute context):

```python
retrieval = context.get_retrieval_module()
relevant_history = retrieval.retrieve_by_goal_relevance(
    goal_id=state.current_goal_id,
    execution_context={"iteration": state.iteration},
    limit=10,
)
```

**Design principle**: Retrieval algorithms evolve behind a stable module API; `ingest` / `project` contracts stay stable.

### Implementations

| Name | Backend | Persistence | Description |
|------|---------|-------------|-------------|
| `KeywordContext` | Keyword/tag matching | JSON or RocksDB via `PersistStore` | Lightweight, no embedding deps. Default for `context_backend=keyword`. |
| `VectorContext` | VectorStoreProtocol + Embeddings | Delegated to VectorStore | Semantic projection. Requires `vector_store_provider` config. |

### Persistence Integration

Context persistence is automatic when a `context_persist_dir` is configured (defaults to `$SOOTHE_HOME/context/`). The `SootheRunner` calls:
- `context.restore(thread_id)` during pre-stream when resuming a thread
- `context.persist(thread_id)` during post-stream after ingestion

## Module 2: MemoryProtocol (Cross-Thread Long-Term Memory)

Persistent knowledge that survives across threads. Separate from ContextProtocol (within-thread) and deepagents' MemoryMiddleware (static AGENTS.md files).

### Protocol

```python
class MemoryProtocol(Protocol):
    async def remember(self, item: MemoryItem) -> str: ...
    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]: ...
    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]: ...
    async def forget(self, item_id: str) -> bool: ...
    async def update(self, item_id: str, content: str) -> None: ...
```

### Data Models

- `MemoryItem(id, content, source_thread, created_at, tags, importance, metadata)`

### Design Principles

1. **Auto-memorization for significant responses** -- `SootheRunner` auto-stores responses >50 chars
2. **Semantic recall** -- `recall(query)` retrieves by keyword or semantic relevance
3. **Integration with ContextProtocol** -- recalled items are ingested into context at thread start

### Implementations

| Name | Backend | Persistence | Description |
|------|---------|-------------|-------------|
| `MemUMemory` | MemU memory store + configured chat/embedding models | Files under `protocols.memory.persist_dir` (defaults to `$SOOTHE_HOME/memory/`) | Current default `MemoryProtocol` implementation resolved by `resolve_memory()`. Supports semantic recall, tags, and metadata. |

### Persistence Integration

Memory persistence is automatic when `protocols.memory.persist_dir` is configured (defaults to `$SOOTHE_HOME/memory/`). The `MemUMemory` implementation:
- Initializes a `MemuMemoryStore` rooted at the configured persist directory
- Persists memory records through the MemU store on each `remember()` call
- Serves `recall()` and `recall_by_tags()` through the MemU adapter
- Is invoked by `SootheRunner` during post-stream for significant agent responses

### Configuration

```yaml
protocols:
  memory:
    enabled: true
    persist_dir: null      # defaults to $SOOTHE_HOME/memory/
    llm_chat_role: fast
    llm_embed_role: embedding
```


## Module 3: PlannerProtocol

### Protocol

```python
class PlannerProtocol(Protocol):
    async def create_plan(self, goal: str, context: PlanContext) -> Plan: ...
    async def revise_plan(self, plan: Plan, reflection: str) -> Plan: ...
    async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection: ...
```

### Data Models

- `Plan(goal, steps, current_index, status, concurrency)`
- `PlanStep(id, description, execution_hint, status, result, depends_on)`
- `PlanContext(recent_messages, available_capabilities, completed_steps)`
- `Reflection(assessment, should_revise, feedback)`

**Note**: RFC-200 introduces `StepScheduler` for DAG-based step execution using `PlanStep.depends_on`. Plans with multiple steps are iterated via a runner-driven step loop. `StepReport` and `GoalReport` models are added for progressive result recording.

### Implementations

- `LLMPlanner` -- single LLM call with structured output for tasks of all complexity levels, implements two-phase architecture (StatusAssessment + PlanGeneration) for token efficiency per RFC-604

**Architectural evolution**:
- IG-028: DirectPlanner → SimplePlanner
- IG-036: Removed SubagentPlanner indirection
- IG-149: Implemented RFC-604 two-phase Plan architecture
- IG-150: Removed ClaudePlanner and AutoPlanner, consolidated to LLMPlanner, merged cognition.planning into cognition.agent_loop module

**Module location**: `src/soothe/cognition/agent_loop/planner.py` (after IG-150 consolidation)

## Module 4: PolicyProtocol

### Protocol

```python
class PolicyProtocol(Protocol):
    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision: ...
    def narrow_for_child(self, parent_permissions: PermissionSet, child_name: str) -> PermissionSet: ...
```

### Data Models

- `Permission(category, action, scope)` -- structured permission with fine-grained scope
- `PermissionSet` -- collection with scope-aware matching (glob patterns, negation)
- `ActionRequest(action_type, tool_name, tool_args)` -- what is being requested
- `PolicyDecision(verdict, reason, matched_permission)` -- allow/deny/need_approval
- `PolicyProfile(name, permissions, approvable, deny_rules)` -- named configuration

### Default Implementation

`ConfigDrivenPolicy` -- reads profiles from config. Evaluation: deny rules -> granted permissions -> approvable set -> default deny.

## Module 5: DurabilityProtocol

### Protocol

```python
class DurabilityProtocol(Protocol):
    async def create_thread(self, metadata: ThreadMetadata, thread_id: str | None = None) -> ThreadInfo: ...
    async def resume_thread(self, thread_id: str) -> ThreadInfo: ...
    async def suspend_thread(self, thread_id: str) -> None: ...
    async def archive_thread(self, thread_id: str) -> None: ...
    async def update_thread_metadata(self, thread_id: str, metadata: dict[str, Any] | ThreadMetadata) -> None: ...
    async def list_threads(self, thread_filter: ThreadFilter | None = None) -> list[ThreadInfo]: ...
```

State persistence for checkpoints, artifacts, and recovery data is handled by the RFC-200 persistence components rather than by `DurabilityProtocol` directly.

### Data Models

- `ThreadInfo(thread_id, status, created_at, updated_at, metadata)`
- `ThreadMetadata(tags, plan_summary, policy_profile, labels, priority, category)`
- `ThreadFilter(status, tags, created_after, created_before)`

## Module 6: RemoteAgentProtocol

### Protocol

```python
class RemoteAgentProtocol(Protocol):
    async def invoke(self, task: str, context: dict[str, Any] | None = None) -> str: ...
    async def stream(self, task: str, context: dict[str, Any] | None = None) -> AsyncIterator[str]: ...
    async def health_check(self) -> bool: ...
```

### Implementations

- `ACPRemoteAgent` -- planned ACP endpoint adapter
- `A2ARemoteAgent` -- planned A2A peer adapter
- `LangGraphRemoteAgent` -- implemented adapter for langgraph `RemoteGraph`

Future: remote backends will be wrapped as deepagents `CompiledSubAgent` instances for uniform `task`-tool access. Current state: `LangGraphRemoteAgent` is accessed through `RemoteAgentProtocol` directly; wrapper unification is deferred until the broader remote-agent surface is implemented.

## Module 7: ConcurrencyPolicy

### Data Model

```python
class ConcurrencyPolicy(BaseModel):
    max_parallel_subagents: int = 1
    max_parallel_tools: int = 3
    max_parallel_steps: int = 1
    max_parallel_goals: int = 1
    global_max_llm_calls: int = 5
    step_parallelism: Literal["sequential", "dependency", "max"] = "dependency"
```

Steps declare dependencies via `depends_on`, forming a DAG. The orchestrator schedules independent steps in parallel within configured limits.

**Note**: RFC-200 introduces `ConcurrencyController` in `core/concurrency.py` that enforces these limits via `asyncio.Semaphore` at goal, step, and global LLM call levels.

## Module 8: VectorStoreProtocol

### Protocol

```python
class VectorStoreProtocol(Protocol):
    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None: ...
    async def insert(self, vectors, payloads, ids) -> None: ...
    async def search(self, query, vector, limit, filters) -> list[VectorRecord]: ...
    async def delete(self, record_id: str) -> None: ...
    async def update(self, record_id, vector, payload) -> None: ...
    async def get(self, record_id: str) -> VectorRecord | None: ...
    async def list_records(self, filters, limit) -> list[VectorRecord]: ...
    async def delete_collection(self) -> None: ...
    async def reset(self) -> None: ...
```

### Data Models

- `VectorRecord(id, score, payload)` -- a stored vector with metadata

### Implementations

- `PGVectorStore` -- async via psycopg v3, HNSW/DiskANN indexes
- `WeaviateVectorStore` -- async via weaviate-client v4
- `InMemoryVectorStore` -- in-memory for testing and small datasets

## Module 9: PersistStore (Persistence Backend)

Low-level key-value persistence used by `KeywordContext` and other persistence-backed components. Memory persistence is currently handled by the MemU store rather than a `StoreBackedMemory` implementation.

### Protocol

```python
class PersistStore(Protocol):
    def save(self, key: str, data: Any) -> None: ...
    def load(self, key: str) -> Any | None: ...
    def delete(self, key: str) -> None: ...
    def close(self) -> None: ...
```

### Implementations

| Name | Description |
|------|-------------|
| `JsonPersistStore` | One JSON file per key under a directory. Simple and portable. |
| `RocksDBPersistStore` | RocksDB-backed. High throughput for large datasets. |

### Factory

```python
def create_persist_store(persist_dir: str | None, backend: str = "json") -> PersistStore | None
```

Returns `None` if `persist_dir` is `None` (disabling persistence).

## Integration: How Protocols Wire Together

`create_soothe_agent()` is the wiring point:

1. Load `SootheConfig` with multi-provider model router
2. Instantiate protocol implementations based on config
3. Resolve models per role (`default`, `think`, `fast`, `embedding`)
4. Wire context and policy as middleware; resolve memory and planner as attached protocol components
5. Assemble built-in and configured subagents, tools, skills, and middleware for `create_deep_agent()`
6. Call `create_deep_agent()` with the assembled stack
7. Return the compiled agent with protocol instances attached (`soothe_context`, `soothe_memory`, `soothe_planner`, `soothe_policy`, etc.)

### Context + Memory Flow

```
[Thread start / resume]
  DurabilityProtocol.create_thread() or resume_thread()
  ContextProtocol.restore(thread_id)         -- restore persisted thread context when resuming
  MemoryProtocol.recall(goal)                -- recall relevant cross-thread memories
  ContextProtocol.ingest(recalled memories)  -- merge recalled memory into current thread context

[Before LLM call]
  ContextProtocol.project(goal, token_budget) -> inject bounded context into enriched input

[After agent response]
  ContextProtocol.ingest(source="agent", content=response)
  ContextProtocol.persist(thread_id)         -- persist updated context ledger
  MemoryProtocol.remember(response)          -- store significant responses in long-term memory

[Thread suspend / archive]
  ThreadContextManager.persist_context()     -- persist context during lifecycle transitions
  DurabilityProtocol.suspend_thread() / archive_thread()
```

Current implementation detail: query-time context restore/persist happens in `SootheRunner`, while suspend/archive persistence is handled by `ThreadContextManager`.

### Persistence Directory Layout

All persistence is under `$SOOTHE_HOME` (default `~/.soothe`):

```
$SOOTHE_HOME/
├── context/          # KeywordContext persistence (one JSON per thread)
├── memory/           # MemUMemory persistence (MemU memory store files)
├── threads/          # Thread JSONL logs (one per thread)
├── logs/             # Application logs (soothe.log, rotating)
├── history.json      # Input history
├── soothe.sock       # Legacy (removed in v0.2)
└── config/           # User config files
    └── config.yml
```


---

## RFC Protocol Module Extraction (2026-04-17)

**Important**: This RFC's protocol modules have been extracted into dedicated RFC specifications:

| Module | Protocol | RFC | Status |
|--------|----------|-----|--------|
| **Module 1** | ContextProtocol | [RFC-400](./RFC-400-context-protocol-architecture.md) | Draft |
| **Module 2** | MemoryProtocol | [RFC-402](./RFC-402-memory-protocol-architecture.md) | Draft |
| **Module 3** | PlannerProtocol | [RFC-404](./RFC-404-planner-protocol-architecture.md) | Draft |
| **Module 4** | PolicyProtocol | [RFC-406](./RFC-406-policy-protocol-architecture.md) | Draft |
| **Module 5** | DurabilityProtocol | [RFC-408](./RFC-408-durability-protocol-architecture.md) | Draft |
| **Module 6** | RemoteAgentProtocol | [RFC-410](./RFC-410-remote-agent-protocol-architecture.md) | Draft |
| **Module 7** | ConcurrencyPolicy | Stayed in RFC-001 | — |
| **Module 8** | VectorStoreProtocol | Stayed in RFC-001 | — |

**Numbering Scheme**:
- **4xx**: Core protocol definitions (400-410)
- **45x**: Daemon and communication layer (450-454)

**Migration**: Protocol content moved to dedicated RFCs. RFC-001 preserved for architectural overview and remaining modules (ConcurrencyPolicy, VectorStoreProtocol, PersistStore). Use dedicated RFCs for implementation details.
