# Design Draft: Entity Model and State Management Consolidation

**Date**: 2026-06-16
**Author**: Design session via architectural analysis
**Status**: Draft for user validation
**Proposed RFC**: RFC-626
**Dependencies**: RFC-624 (Context Engine), RFC-625 (Autopilot Monitor Unification)
**Supersedes Portions**: RFC-302 (ContextProtocol), RFC-203 (LoopState)
**Implements**: RFC-303 (MemoryProtocol) — CE EpisodicSubmodule implements MemoryProtocol API

---

## Overview

This design consolidates all entity models and state containers under ContextEngine, eliminating dual ownership and synchronization complexity. The result: CE as sole entity owner, protocols become CE submodule interfaces, LoopState deleted, and unified retrieval APIs.

---

## 1. Problem Statement

### 1.1 Current State Fragmentation

| Entity | Current Owners | Issues |
|--------|---------------|--------|
| **Goals/Steps** | ContextEngine (GoalNode/StepNode) + deprecated GoalEngine remnants | ✅ CE authoritative (RFC-625 completed) |
| **Execution Ledger** | LedgerManager (CE) + ContextProtocol.entries | ❌ Dual ownership, unclear boundary |
| **Knowledge Accumulation** | ContextProtocol (unbounded ledger) + CE LedgerManager | ❌ Overlapping responsibilities |
| **Cross-thread Memory** | MemoryProtocol (protocol interface) + CE EpisodicSubmodule (implementation) | ⚠️ CE should leverage MemoryProtocol API |
| **Loop State** | LoopState (metrics + entity refs) + LoopGraphState (routing) + CE | ❌ Three containers, synchronization complexity |
| **Thread State** | ThreadState (daemon) + CoreAgent checkpoint + CE thread_id refs | ❌ Cross-process ownership unclear |

### 1.2 Integration Gaps Remaining (Post RFC-625)

1. **Checkpoint reads still exist**: `plan_assess.py:176`, `bounded_evidence_gather.py:47-49` read `checkpoint.goal_history` despite CE being authoritative (IG-491 documents this)

2. **Adapter deletion incomplete**: 3 adapters (Plan, Ledger, GoalContext) marked for deletion in Phase 4 but still referenced in tests

3. **Protocol-entity mismatch**: ContextProtocol designed for cognitive knowledge, but CE's LedgerManager duplicates message storage

4. **No unified entity identity**: "Goal" exists as `GoalNode` (CE), `Goal` (deprecated), `goal_history` entry (checkpoint) — conceptual confusion

### 1.3 Maintenance Burden Pattern

| IG | Issue | Root Cause |
|----|-------|------------|
| IG-483 | Adapter hardening + projection wiring | Dual ownership requires adapters |
| IG-491 | CE Phase 4 deep refinement | Checkpoint reads mixed with CE queries |
| IG-480 | LoopState backend replacement | State container overlap |

**Pattern**: Adapter fixes ongoing because dual systems persist. Consolidation eliminates this pattern permanently.

---

## 2. Proposed Solution: Full CE Consolidation

### 2.1 Core Principle

**ContextEngine becomes the sole entity model and state container** for all execution-level and cognitive-level entities. Other protocols become CE submodules with specialized retrieval interfaces.

### 2.2 Entity Model Unification

```
┌─────────────────────────────────────────────────────────────┐
│ ContextEngine (Unified Entity Owner)                         │
│                                                               │
│  ├─ GoalStepDAG                                               │
│  │   ├─ GoalNode (goal entity with lineage)                  │
│  │   ├─ StepNode (step entity with execution record)         │
│  │   └─ StepExecution (CoreAgent execution trace)            │
│                                                               │
│  ├─ LedgerManager (unified message ledger)                   │
│  │   ├─ Execution messages (tool results, agent responses)   │
│  │   ├─ Cognitive messages (reflection, reasoning)           │
│  │   └─ Projection API (bounded retrieval)                   │
│                                                               │
│  ├─ CognitiveSubmodule (replaces ContextProtocol)            │
│  │   ├─ Knowledge scoring (importance + relevance)           │
│  │   ├─ Semantic retrieval (embedding-based search)          │
│  │   └─ Goal-centric projection (for prompts)                │
│                                                               │
│  ├─ EpisodicSubmodule (implements MemoryProtocol)            │
│  │   ├─ Episode summary (distilled goal outcomes)            │
│  │   ├─ Procedure extraction (reusable skills)               │
│  │   ├─ Cross-thread recall (semantic search)                │
│  │   └─ Leverages MemoryProtocol API for external memory     │
│                                                               │
│  ┌─ External Memory (via MemoryProtocol interface) ────────┐ │
│  │ MemoryProtocol provides protocol interface for:         │ │
│  │   • External memory systems (MemUMemory, Mem0, etc.)    │ │
│  │   • Pluggable memory backends                           │ │
│  │   • Cross-thread memory integration                      │ │
│  │ CE's EpisodicSubmodule implements MemoryProtocol API    │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                               │
│  ├─ PersistenceBackend (pluggable)                           │
│  │   ├─ SqliteContextPersistence (default)                   │
│  │   ├─ PgsqlContextPersistence (production)                 │
│  │   └─ Lossless serialization (RFC-624 Phase 3a)            │
│                                                               │
│  └─ PlanningSubmodule (already exists)                       │
│      ├─ StepPlanningSubengine                                │
│      ├─ GoalPlanningSubengine                                │
│      └─ GoalScheduler                                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 State Container Simplification

| Current | After Consolidation |
|---------|---------------------|
| `LoopState` (metrics + entity refs) | **Deleted** → metrics move to CE wave tracking |
| `LoopGraphState` (routing channels) | **Retained** → thin routing-only TypedDict |
| `ThreadState` (daemon) | **Retained** → daemon-specific, no entity overlap |
| `ContextProtocol.entries` | **Migrated** → CE LedgerManager.entries() |
| `MemoryProtocol` | **Retained** → protocol interface for external memory integration |
| `CE EpisodicSubmodule` | **Implements** → MemoryProtocol API, internal persistence |
| `checkpoint.goal_history` | **Deleted** → CE GoalStepDAG is authoritative |

**Result**: One entity owner (CE), three thin state facades (routing, daemon, metrics).

---

## 3. Key Design Decisions

### 3.1 Decision 1: Cognitive vs Execution Ledger Merge

**Options**:
- **Option A**: Keep separate ledgers (ContextProtocol for cognitive, CE for execution)
- **Option B**: Unified ledger in CE with phase tagging

**Chosen**: **Option B — Unified Ledger**

**Rationale**:
- Execution messages and cognitive knowledge share same retrieval needs (goal-centric projection)
- Phase tagging (`execute`, `plan`, `reflect`, `compacted`) enables filtered retrieval
- Eliminates dual ingestion logic (StrangeLoop writes to both)
- ContextProtocol becomes retrieval interface, not storage

**Migration Path**:
```
ContextProtocol.ingest(entry) → CE.ingest_cognitive(entry, phase="reflect")
ContextProtocol.project(query, budget) → CE.cognitive.project(query, budget)
```

**API Changes**:
```python
class ContextEngine:
    def ingest_cognitive(self, entry: ContextEntry, phase: str = "reflect") -> None:
        """Ingest cognitive knowledge into unified ledger with phase tag."""
        self._ledger.record_message(
            SystemMessage(content=entry.content),
            phase=phase
        )
        # Track cognitive entry metadata separately for retrieval scoring
        self._cognitive_entries.append(entry)
    
    def get_ledger_entries(self, phases: list[str] | None = None) -> list[tuple[BaseMessage, str]]:
        """Unified retrieval with phase filtering."""
        return self._ledger.entries(phases)
```

---

### 3.2 Decision 2: MemoryProtocol Protocol Interface

**Options**:
- **Option A**: MemoryProtocol remains separate, recalled at thread start
- **Option B**: Memory becomes CE EpisodicSubmodule, MemoryProtocol deleted (not chosen)
- **Option C**: MemoryProtocol retained as protocol interface, CE EpisodicSubmodule implements it

**Chosen**: **Option C — MemoryProtocol as Protocol Interface, CE Implements**

**Rationale**:
- MemoryProtocol is a **protocol interface** for external memory integration (MemUMemory, Mem0, etc.)
- CE's EpisodicSubmodule **implements** MemoryProtocol API for internal persistence
- Allows pluggable external memory backends while CE provides default implementation
- Dreaming coordinator (RFC-625) writes to CE episodic store via MemoryProtocol API
- Preserves extensibility for future memory systems

**Architecture**:
```
MemoryProtocol (interface)
    │
    ├── MemUMemory (external implementation)
    ├── Mem0 (external implementation)
    └── CE EpisodicSubmodule (internal implementation)
            ├── Episode summary storage (SQLite/PostgreSQL)
            ├── Procedure extraction (reusable skills)
            └── Cross-thread recall (semantic search)
```

**API Contract**:
```python
# MemoryProtocol remains as interface (RFC-303)
class MemoryProtocol(Protocol):
    async def remember(self, item: MemoryItem) -> str:
        """Store a memory item, return ID."""
        ...
    
    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Recall relevant memories by query."""
        ...
    
    async def forget(self, item_id: str) -> bool:
        """Forget a memory item."""
        ...

# CE EpisodicSubmodule implements MemoryProtocol
class EpisodicSubmodule(MemoryProtocol):
    """CE's internal episodic memory implementation of MemoryProtocol."""
    
    async def remember(self, item: MemoryItem) -> str:
        """Store episode via MemoryProtocol API."""
        # Convert MemoryItem to EpisodeSummary if needed
        return await self._store.store(item)
    
    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Recall episodes via MemoryProtocol API."""
        return await self._store.search(query, limit)
    
    async def forget(self, item_id: str) -> bool:
        """Forget episode via MemoryProtocol API."""
        return await self._store.delete(item_id)
    
    # Extended API for CE-specific operations
    async def remember_episode(self, summary: EpisodeSummary) -> str:
        """Store distilled goal outcome as episodic memory."""
        return await self._store.store_episode(summary)
```

**Integration Point** (Thread Start):
```python
# soothe/runner/__init__.py
async def _pre_stream(thread_id: str, query: str, memory: MemoryProtocol):
    # CE load restores goal DAG and ledger
    await ce.load(loop_id)
    
    # Use MemoryProtocol API for cross-thread memory recall
    # (memory could be CE's EpisodicSubmodule or external implementation)
    relevant_memories = await memory.recall(query, limit=5)
    for mem in relevant_memories:
        await ce.ingest_cognitive(
            ContextEntry(
                source="memory_recall",
                content=mem.content,
                tags=["cross_thread", "memory"],
            )
        )
```

---

### 3.3 Decision 3: LoopState Elimination

**Options**:
- **Option A**: Retain LoopState as metrics facade
- **Option B**: Delete LoopState, metrics move to CE wave tracking

**Chosen**: **Option B — Delete LoopState**

**Rationale**:
- LoopState entity refs (`current_goal_id`, `goal_text`) duplicate CE GoalNode
- Metrics (`last_wave_tool_call_count`, `iteration`) belong to CE execution tracking
- StrangeLoop accesses CE directly (Phase 4 already wired)
- LoopGraphState sufficient for routing (no entity data needed)

**Metrics Migration**:
```python
class ContextEngine:
    # Add wave tracking property
    @property
    def wave_metrics(self) -> WaveMetrics:
        """Execution metrics from last Execute wave."""
        return self._wave_metrics
    
    def record_wave_metrics(self, metrics: WaveMetrics) -> None:
        """Called by Executor after each Execute wave."""
        self._wave_metrics = metrics
```

**WaveMetrics Data Structure**:
```python
class WaveMetrics(BaseModel):
    """Metrics from a single Execute wave."""
    tool_call_count: int = 0
    subagent_task_count: int = 0
    hit_subagent_cap: bool = False
    output_length: int = 0
    error_count: int = 0
    tokens_used: int = 0
```

**StrangeLoop Access Pattern** (Post-Consolidation):
```python
# Current (with LoopState)
metrics = state.last_wave_tool_call_count

# After consolidation
metrics = ce.wave_metrics.tool_call_count
```

---

### 3.4 Decision 4: Persistence Backend Unification

**Options**:
- **Option A**: Keep dual persistence (LangGraph checkpointer for CoreAgent, CE for StrangeLoop)
- **Option B**: CE owns all persistence, CoreAgent checkpoint becomes CE thread record

**Chosen**: **Option A — Keep Dual Persistence**

**Rationale**:
- LangGraph checkpointer is CoreAgent-native, deep integration
- Thread/loop isolation principle (RFC-215) enforces separation
- CE owns loop-level data (goals, steps, ledger)
- CoreAgent owns thread-level data (message history, checkpoints)
- Cross-reference via `checkpoint_anchors` table (RFC-215 already defines this)

**Persistence Ownership Matrix**:

| Data Type | Owner | Backend | Scope |
|-----------|-------|---------|-------|
| Goals/Steps | CE | SqliteContextPersistence | Loop-scoped |
| Execution Ledger | CE | LedgerManager (in-memory + spill) | Loop-scoped |
| Episodic Memory | CE | EpisodicStore (sqlite/pgsql) | Cross-loop |
| CoreAgent Messages | LangGraph | Checkpointer (sqlite/memory) | Thread-scoped |
| Thread History | LangGraph | Checkpointer | Thread-scoped |

**Cross-Reference Mechanism** (RFC-215):
```sql
CREATE TABLE checkpoint_anchors (
    anchor_id INTEGER PRIMARY KEY,
    loop_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    thread_id TEXT NOT NULL,  -- Cross-reference
    checkpoint_id TEXT NOT NULL,
    anchor_type TEXT NOT NULL,
    ...
);
```

**Result**: No change to persistence architecture, aligns with RFC-215 thread/loop isolation.

---

## 4. Module Structure Changes

### 4.1 New Submodules

**`soothe/context/cognitive.py`**:
```python
"""Cognitive knowledge retrieval submodule (replaces ContextProtocol)."""

class CognitiveSubmodule:
    """Retrieval interface for cognitive knowledge in unified ledger."""
    
    def __init__(self, ledger: LedgerManager, embedding_model: Embeddings | None = None):
        self._ledger = ledger
        self._embedding_model = embedding_model
        self._algorithm_version = "v2_unified"  # Evolvable
    
    def project(self, query: str, token_budget: int) -> ContextProjection:
        """Project bounded view for orchestrator reasoning."""
        # Combine execution + cognitive entries, score by relevance
        entries = self._ledger.entries(phases=["execute", "plan", "reflect"])
        scored = self._score_entries(entries, query)
        bounded = self._truncate_to_budget(scored, token_budget)
        return ContextProjection(entries=bounded, ...)
    
    def retrieve_by_goal_relevance(self, goal_id: str, limit: int) -> list[ContextEntry]:
        """Goal-centric retrieval for StrangeLoop."""
        # Implementation matches RFC-302 ContextRetrievalModule API
        ...
```

**`soothe/context/episodic/store.py`** (already exists from RFC-625, enhanced):
```python
class EpisodicStore:
    """Episodic memory store with unified persistence."""
    
    async def store(self, summary: EpisodeSummary) -> str:
        """Store episode summary with semantic embedding."""
        if self._embedding_model:
            embedding = await self._embedding_model.aembed_query(summary.summary_text)
            summary.embedding = embedding
        # Persist via CE backend
        await self._persistence.store_episode(summary)
        return summary.id
    
    async def search(self, query: str, limit: int) -> list[EpisodeSummary]:
        """Semantic search across episode summaries."""
        # Use embedding if available, otherwise keyword search
        ...
```

### 4.2 Deleted Modules

| Module | Location | Reason |
|--------|----------|--------|
| `LoopState` | `foundation/sloop/state/schemas.py` | Metrics moved to CE |
| `ContextProtocol` | `protocols/context.py` | Replaced by CognitiveSubmodule |
| `goal_history` field | `state/schemas.py` CheckpointSchema | CE GoalStepDAG authoritative |

### 4.3 Retained Modules

| Module | Location | Reason |
|--------|----------|--------|
| `MemoryProtocol` | `protocols/memory.py` | Protocol interface for external memory integration (RFC-303) |
| `CE EpisodicSubmodule` | `context/episodic/store.py` | Implements MemoryProtocol API for persistent episodic memory |

### 4.4 Modified Modules

**`soothe/context/engine.py`**:
- Add `CognitiveSubmodule` and `EpisodicSubmodule` to composition
- Add `wave_metrics` property for wave tracking
- Add `ingest_cognitive()` API
- Expose unified `get_ledger_entries(phases)` API

**`soothe/sloop/engine/executor.py`**:
- Replace `state.last_wave_*` with `ce.wave_metrics.*`
- Replace dual ledger writes with single CE call
- Delete LoopState parameter from constructor

**`soothe/sloop/nodes/*.py`**:
- Replace `state.current_goal_id` with `ce.get_active_goal().id`
- Replace `checkpoint.goal_history` reads with `ce.get_all_goals()`
- All graph nodes read from CE public API

---

## 5. Implementation Phases

### Phase 5: LoopState Deletion (Week 1-2)

**Objective**: Eliminate LoopState, metrics move to CE wave tracking.

| Task | Files | Validation |
|------|-------|------------|
| Create WaveMetrics model | `context/models.py` | Model defined |
| Add wave_metrics to CE | `context/engine.py` | Property accessible |
| Executor writes wave metrics | `loop/engine/executor.py` | `ce.record_wave_metrics()` called |
| Delete LoopState class | `loop/state/schemas.py` | Class deleted |
| Update graph nodes | `orchestrator/nodes/*.py` | Read from CE, not LoopState |

**Acceptance Criteria**:
- `grep -r "class LoopState" packages/soothe/src/soothe/sloop/` returns zero matches
- LoopGraphState remains but has no entity fields
- All tests pass with CE metrics access

---

### Phase 6: ContextProtocol → CognitiveSubmodule (Week 3-4)

**Objective**: ContextProtocol replaced by CE cognitive retrieval interface.

| Task | Files | Validation |
|------|-------|------------|
| Create CognitiveSubmodule | `context/cognitive.py` | Class defined |
| Add ingest_cognitive() to CE | `context/engine.py` | API public |
| LedgerManager phase filtering | `context/ledger.py` | `entries(phases)` works |
| StrangeLoop ingestion unified | `loop/engine/executor.py` | Single write path |
| Delete ContextProtocol class | `protocols/context.py` | Class deleted |
| Update all imports | `runner/*.py`, `middleware/*.py` | Import CE cognitive |

**Acceptance Criteria**:
- `grep -r "class ContextProtocol" packages/soothe/src/soothe/protocols/` returns zero matches
- CE cognitive.project() produces same output as old ContextProtocol.project()
- Integration tests validate prompt context unchanged

---

### Phase 7: CE EpisodicSubmodule Implements MemoryProtocol (Week 5-6)

**Objective**: CE EpisodicSubmodule implements MemoryProtocol API for persistent episodic memory; MemoryProtocol retained as protocol interface.

| Task | Files | Validation |
|------|-------|------------|
| Enhance EpisodicStore | `context/episodic/store.py` | Implements MemoryProtocol API |
| Add episodic submodule to CE | `context/engine.py` | CE.episodic property returns MemoryProtocol-compliant object |
| Runner recalls via MemoryProtocol API | `runner/__init__.py` | `_pre_stream` uses memory.recall() (MemoryProtocol interface) |
| Update dreaming coordinator | `autopilot/dreaming.py` | Writes via MemoryProtocol API (remember()) |
| Update imports to use MemoryProtocol | `protocols/memory.py` | EpisodicSubmodule imported as MemoryProtocol implementation |

**Acceptance Criteria**:
- CE EpisodicSubmodule implements all MemoryProtocol methods (remember, recall, recall_by_tags, forget)
- Thread start injects episodic recall into CE ledger via MemoryProtocol API
- Dreaming distillation persists to CE episodic store via MemoryProtocol API
- External memory implementations (MemUMemory, Mem0) still work via MemoryProtocol interface

---

### Phase 8: Entity Identity Consolidation (Week 7-8)

**Objective**: Remove all dual entity forms, checkpoint.goal_history deleted.

| Task | Files | Validation |
|------|-------|------------|
| Delete goal_history field | `loop/state/schemas.py` | Field removed from CheckpointSchema |
| Replace checkpoint reads | `orchestrator/nodes/plan_assess.py` | CE query only |
| Remove checkpoint fallback | `orchestrator/nodes/bounded_evidence_gather.py` | No fallback logic |
| Unified entity tests | `tests/unit/context/` | One goal = one GoalNode |
| Update RFCs | `docs/specs/RFC-*.md` | Superseded sections marked |

**Acceptance Criteria**:
- `grep -r "goal_history" packages/soothe/src/soothe/sloop/` returns zero matches
- All entity reads/writes via CE public API
- Checkpoint is purely metadata (loop_id, thread_ids, status)
- RFC-302, RFC-303, RFC-203 updated with superseded notices

---

## 6. API Migration Guide

### 6.1 StrangeLoop Migration

**Current Pattern**:
```python
# executor.py (current)
state.last_wave_tool_call_count = tool_count
state.iteration += 1
await context.ingest(ContextEntry(...))  # ContextProtocol
await memory.remember(MemoryItem(...))  # MemoryProtocol
```

**After Consolidation**:
```python
# executor.py (Phase 5-7)
ce.record_wave_metrics(WaveMetrics(tool_call_count=tool_count, ...))
# Iteration tracked in CE GoalStepDAG
await ce.ingest_cognitive(ContextEntry(...), phase="execute")
await ce.episodic.remember_episode(EpisodeSummary(...))
```

### 6.2 Graph Node Migration

**Current Pattern** (plan_assess.py):
```python
# Check if continuation mode with prior goals
if (
    state.iteration == 0
    and ctx.continue_loop_mode
    and len(ctx.checkpoint.goal_history) >= 2  # checkpoint read
):
    return "continue_assess"
```

**After Consolidation**:
```python
# Check if continuation mode with prior completed goals
if (
    ce.iteration == 0  # CE iteration property
    and ctx.continue_loop_mode
    and any(g.status == "completed" for g in ce.get_all_goals())  # CE query
):
    return "continue_assess"
```

### 6.3 Runner Migration

**Current Pattern** (_pre_stream):
```python
# Restore context
await context.restore(thread_id)

# Recall memory (separate system)
relevant_memories = await memory.recall(goal, limit=5)

# Inject into context
for mem_item in relevant_memories:
    await context.ingest(ContextEntry(
        source="memory",
        content=mem_item.content,
        ...
    ))
```

**After Consolidation**:
```python
# CE load restores goal DAG, ledger, episodic memory
await ce.load(loop_id)

# Episodic recall integrated into CE
relevant_episodes = await ce.episodic.recall(goal, limit=5)

# Inject via unified ingest
for episode in relevant_episodes:
    await ce.ingest_cognitive(ContextEntry(
        source="episodic_recall",
        content=episode.summary_text,
        ...
    ), phase="episodic_inject")
```

---

## 7. Architectural Benefits

| Benefit | Current Problem | After Consolidation |
|---------|----------------|---------------------|
| **Single entity identity** | Goal exists in 3 forms (GoalNode, Goal, goal_history) | One `GoalNode` in CE |
| **Unified retrieval** | ContextProtocol + CE LedgerManager dual writes | CE cognitive + ledger retrieval |
| **Simplified state** | LoopState + CE + checkpoint triple overlap | CE + thin routing facades |
| **Clear persistence** | Multiple backends per entity type | CE persistence for loop entities, LangGraph for threads |
| **Protocol clarity** | Context/Memory vs CE overlap | Protocols become CE submodule interfaces |
| **Maintenance burden** | Adapter fixes ongoing (IG-483, IG-491) | Direct CE access, no adapters |

---

## 8. Risk Mitigation

| Risk | Mitigation Strategy |
|------|---------------------|
| Breaking StrangeLoop behavior | Phase 3d behavioral equivalence test suite (RFC-624) ensures safety; run full integration tests per phase |
| Protocol API compatibility | Protocols become thin wrappers over CE submodules during transition period (2 weeks per protocol) |
| Persistence migration complexity | Keep dual persistence (Decision 4), no backend rewrite needed |
| Rollback safety | Each phase has independent validation checkpoint; git branch per phase allows rollback |
| Documentation drift | Update RFC superseded notices in same commit as code deletion |
| Test coverage gaps | Add entity identity tests in Phase 8 (one goal = one GoalNode) |

---

## 9. Validation Questions

**User must approve the following design decisions:**

1. ✅ **ContextEngine as sole entity owner** — Goals, steps, ledger, cognitive knowledge consolidated in CE; episodic memory in CE via MemoryProtocol API implementation?

2. ✅ **Unified ledger with phase tagging** — Execution and cognitive messages merged in LedgerManager with phase filtering?

3. ✅ **LoopState deletion** — Metrics move to CE wave tracking, LoopGraphState remains routing-only?

4. ✅ **ContextProtocol → CognitiveSubmodule** — ContextProtocol deleted, CE CognitiveSubmodule handles cognitive retrieval; **MemoryProtocol retained** as protocol interface, CE EpisodicSubmodule implements it?

5. ✅ **Keep dual persistence** — CE for loop entities, LangGraph checkpointer for CoreAgent threads (no change to RFC-215)?

6. ✅ **8-week phased rollout** — Phase 5-8 with validation checkpoints per phase, independent rollback per phase?

---

## 10. Next Steps Upon Approval

1. **Create RFC-626 draft**: Document entity consolidation design in `docs/specs/RFC-626-entity-state-consolidation.md`

2. **Update superseded RFCs**:
   - RFC-302: Mark ContextProtocol sections superseded by CE CognitiveSubmodule
   - RFC-303: Update MemoryProtocol to document CE EpisodicSubmodule as implementation
   - RFC-203: Mark LoopState sections superseded by CE metrics

3. **Create IG-496 implementation guide**: Detailed file changes and test updates per phase

4. **Begin Phase 5 implementation**: LoopState deletion with wave metrics migration

5. **Update RFC index**: Add RFC-626 to `docs/specs/rfc-index.md` with dependencies

---

## 11. Files Modified Summary

| Category | Files Added | Files Modified | Files Deleted |
|----------|-------------|----------------|---------------|
| **Entity Models** | `context/cognitive.py` | `context/models.py` (WaveMetrics) | - |
| **State Containers** | - | - | `loop/state/schemas.py` (LoopState) |
| **Protocols** | - | `protocols/memory.py` (retained as interface) | `protocols/context.py` |
| **Engine Integration** | - | `context/engine.py`, `context/ledger.py`, `context/episodic/store.py` | - |
| **StrangeLoop Nodes** | - | `executor.py`, `plan_assess.py`, `bounded_evidence_gather.py` | - |
| **Runner** | - | `runner/__init__.py` | - |
| **Tests** | `tests/unit/context/test_entity_identity.py` | All existing tests updated | - |
| **Documentation** | `docs/specs/RFC-626-*.md` | RFC-302, RFC-303, RFC-203, RFC-000 | - |

**Estimated Total Changes**: ~35 files modified, ~5 files deleted, ~3 files added.

---

## 12. Timeline

| Phase | Duration | Start Date | End Date | Milestone |
|-------|----------|------------|----------|-----------|
| Phase 5 | 2 weeks | Week 1 | Week 2 | LoopState deleted, CE metrics active |
| Phase 6 | 2 weeks | Week 3 | Week 4 | ContextProtocol deleted, CE cognitive active |
| Phase 7 | 2 weeks | Week 5 | Week 6 | CE EpisodicSubmodule implements MemoryProtocol API, episodic persistence active |
| Phase 8 | 2 weeks | Week 7 | Week 8 | Entity identity unified, checkpoint.goal_history deleted |

**Total Duration**: 8 weeks (6 work weeks + 2 validation/integration weeks)

---

**Awaiting user validation to proceed with RFC-626 creation and Phase 5 implementation.**