# RFC Merge Proposal - Compact Design (≤800 Lines per RFC)

**Objective**: Consolidate related RFCs within 2XX (Layer 2) and 4XX (Core Protocols) to reduce fragmentation while maintaining <800 lines per merged RFC

**Constraints**:
1. Merged RFC ≤800 lines
2. Only merge truly related designs (same component/subsystem)
3. Preserve architectural separation (don't merge cross-layer)
4. Proposal stage only (no direct merge execution)

---

## 2XX Layer 2 - AgentLoop Merge Plan

### Current State: 15 RFCs (Fragmented)

```
RFC-200: Plan-Execute Loop Core
RFC-201: AgentDecision & Batch Execution
RFC-202: PlanResult & Goal-Directed Evaluation
RFC-203: Loop Working Memory
RFC-204: Loop State & Wave Metrics
RFC-205: Loop Unified State Checkpoint
RFC-206: Prompt Architecture
RFC-207: Thread Lifecycle & Multi-Thread
RFC-208: Goal Context Manager
RFC-209: Thread Relationship Module
RFC-210: Executor Thread Coordination
RFC-211: Tool Result Optimization
RFC-212: Subagent Parallel Spawning
RFC-213: Reasoning Quality Progressive Actions
RFC-214: Reason Phase Robustness
```

**Issue**: Core loop logic split across 3 RFCs (200-202), state management split across 3 RFCs (203-205), thread management split across 4 RFCs (207-210)

---

### Proposed Merges for 2XX

#### Merge 1: AgentLoop Core Loop Architecture (RFC-200)

**Merge Source**: RFC-200 + RFC-201 + RFC-202
**New Title**: "AgentLoop Plan-Execute Loop Architecture"
**Estimated Lines**: ~500-600 lines

**Merge Logic**:
- RFC-200 (Core): Plan → Execute loop structure (~200 lines)
- RFC-201 (Decision): AgentDecision batch execution (~150 lines)
- RFC-202 (Result): PlanResult goal-directed evaluation (~150 lines)

**Combined Content**:
```
## Plan-Execute Loop Model
  ├─ Loop Structure (from RFC-200)
  ├─ Iteration Semantics (from RFC-200)
  
## AgentDecision Model (from RFC-201)
  ├─ StepAction
  ├─ Execution Mode (parallel/sequential/dependency)
  
## PlanResult Model (from RFC-202)
  ├─ Status (continue/replan/done)
  ├─ Goal Progress + Confidence
  ├─ Evidence Summary
  
## Integration Flow
  ├─ PLAN Phase (from RFC-200)
  ├─ EXECUTE Phase (from RFC-200)
  ├─ Decision Logic (from RFC-201)
  ├─ Result Evaluation (from RFC-202)
```

**Benefits**:
- Core loop logic unified in single RFC
- Decision + Result models co-located with loop structure
- Clear component boundary: "AgentLoop Core" vs "State" vs "Thread"

---

#### Merge 2: AgentLoop State Management (RFC-203)

**Merge Source**: RFC-203 + RFC-204 + RFC-205
**New Title**: "AgentLoop State & Memory Architecture"
**Estimated Lines**: ~400-500 lines

**Merge Logic**:
- RFC-203 (Working Memory): Bounded scratchpad (~200 lines)
- RFC-204 (Loop State): Wave metrics + state model (~100 lines)
- RFC-205 (Checkpoint): Unified checkpoint (~100 lines)

**Combined Content**:
```
## LoopState Model (from RFC-204)
  ├─ Wave Execution Metrics
  ├─ Context Window Metrics
  
## Loop Working Memory (from RFC-203)
  ├─ Bounded Scratchpad
  ├─ Spill Artifacts
  ├─ Runs-Local Files
  
## Unified State Checkpoint (from RFC-205)
  ├─ CheckpointEnvelope
  ├─ Progressive Persistence
  ├─ Recovery Restoration
  
## State Flow
  ├─ Iteration State Tracking
  ├─ Working Memory Lifecycle
  ├─ Checkpoint Persistence
```

**Benefits**:
- State management unified (LoopState + WorkingMemory + Checkpoint)
- Memory hierarchy clear: working memory (bounded) vs checkpoint (durable)
- Separate from thread lifecycle (next merge)

---

#### Merge 3: AgentLoop Thread Lifecycle & Context (RFC-207)

**Merge Source**: RFC-207 + RFC-208 + RFC-209 + RFC-210
**New Title**: "AgentLoop Thread Management & Goal Context"
**Estimated Lines**: ~600-700 lines

**Merge Logic**:
- RFC-207 (Thread Lifecycle): Multi-thread spanning (~150 lines)
- RFC-208 (Goal Context Manager): Previous goal injection (~200 lines)
- RFC-209 (Thread Relationship): Similarity module (~150 lines)
- RFC-210 (Executor Coordination): Thread coordination (~100 lines)

**Combined Content**:
```
## Thread Lifecycle (from RFC-207)
  ├─ Multi-Thread Spanning
  ├─ Thread Health Metrics
  ├─ Thread Switch Detection
  
## Goal Context Manager (from RFC-208)
  ├─ Previous Goal Injection
  ├─ Plan vs Execute Context
  ├─ Thread Switch Recovery
  
## Thread Relationship Module (from RFC-209)
  ├─ Goal Similarity Computation
  ├─ Context Construction Strategies
  
## Executor Coordination (from RFC-210)
  ├─ Thread Assignment Logic
  ├─ Event-Driven Monitoring
  
## Thread Management Flow
  ├─ Thread Switching Logic
  ├─ Goal Context Provisioning
  ├─ Similarity-Based Context Construction
```

**Benefits**:
- Thread lifecycle unified with goal context (tight coupling)
- Executor coordination co-located with thread management
- Clear separation: Thread management vs Core loop vs State

---

#### Merge 4: AgentLoop Reasoning & Optimization (RFC-213)

**Merge Source**: RFC-213 + RFC-214
**New Title**: "AgentLoop Reasoning Quality & Robustness"
**Estimated Lines**: ~300-400 lines

**Merge Logic**:
- RFC-213 (Progressive Actions): Reasoning quality (~150 lines)
- RFC-214 (Two-Phase Plan): StatusAssessment + PlanGeneration (~150 lines)

**Combined Content**:
```
## Reasoning Quality Progressive Actions (from RFC-213)
  ├─ Progressive Plan Decisions
  ├─ Evidence-Driven Strategy
  
## Two-Phase Plan Architecture (from RFC-214)
  ├─ Phase 1: StatusAssessment
  ├─ Phase 2: PlanGeneration
  ├─ Token Efficiency
  
## Reasoning Flow
  ├─ Two-Phase Plan Process
  ├─ Progressive Action Strategy
```

**Benefits**:
- Reasoning quality unified (progressive + two-phase)
- Clear component: Reasoning optimization separate from core loop

---

#### No Merge: Standalone RFCs

**RFC-206: Prompt Architecture** (Stand-alone)
- **Reason**: Cross-cutting concern (Plan + Execute prompts), not specific to one component
- **Keep Separate**: ~200 lines, architectural prompt patterns

**RFC-211: Tool Result Optimization** (Stand-alone)
- **Reason**: Specific to evidence flow, not core loop or thread management
- **Keep Separate**: ~150 lines, tool aggregation logic

**RFC-212: Subagent Parallel Spawning** (Stand-alone)
- **Reason**: Specific to concurrency pattern, belongs in concurrency (5XX) category
- **Recommend Move**: Move to 5XX Concurrency category (RFC-512)

---

### 2XX Consolidated Result

| Original | Merged Into | Lines | Status |
|----------|-------------|-------|--------|
| RFC-200 + 201 + 202 | **RFC-200** (Core Loop) | ~550 | ✅ Merge |
| RFC-203 + 204 + 205 | **RFC-203** (State Management) | ~450 | ✅ Merge |
| RFC-207 + 208 + 209 + 210 | **RFC-207** (Thread & Context) | ~650 | ✅ Merge |
| RFC-213 + 214 | **RFC-213** (Reasoning Quality) | ~350 | ✅ Merge |
| RFC-206 | **RFC-206** (Prompt Architecture) | ~200 | ✅ Standalone |
| RFC-211 | **RFC-211** (Tool Result) | ~150 | ✅ Standalone |
| RFC-212 | Move to **5XX** (Concurrency) | - | 🔄 Recategorize |

**Total 2XX RFCs**: 15 → 7 (53% reduction)
**All merged RFCs**: <800 lines ✅

---

## 4XX Core Protocols Merge Plan

### Current State: 14 RFCs (Highly Fragmented)

```
RFC-400: ContextProtocol
RFC-401: ContextRetrievalModule
RFC-402: MemoryProtocol
RFC-403: Context vs Memory Separation
RFC-404: PlannerProtocol
RFC-405: Two-Phase Plan Architecture
RFC-406: PolicyProtocol
RFC-407: Permission Structure
RFC-408: DurabilityProtocol
RFC-409: CheckpointEnvelope
RFC-410: RemoteAgentProtocol
RFC-411: LangGraphRemoteAgent
RFC-412: ACP Remote Agent
RFC-413: A2A Remote Agent
```

**Issue**: Context split across 2 RFCs (400-401), Context/Memory separation standalone (403), Planner split across 2 RFCs (404-405), Policy split across 2 RFCs (406-407), Durability split across 2 RFCs (408-409), Remote split across 4 RFCs (410-413)

---

### Proposed Merges for 4XX

#### Merge 1: ContextProtocol & Retrieval Architecture (RFC-400)

**Merge Source**: RFC-400 + RFC-401
**New Title**: "ContextProtocol: Unbounded Knowledge & Goal-Centric Retrieval"
**Estimated Lines**: ~500-600 lines

**Merge Logic**:
- RFC-400 (ContextProtocol): ingest/project (~300 lines)
- RFC-401 (RetrievalModule): goal-centric retrieval (~200 lines)

**Combined Content**:
```
## ContextProtocol Interface (from RFC-400)
  ├─ ingest(entry)
  ├─ project(query, budget)
  ├─ persist(thread_id)
  
## Design Principles (from RFC-400)
  ├─ Unbounded Accumulation
  ├─ Relevance-Based Projection
  ├─ Subagent Isolation
  
## ContextRetrievalModule (from RFC-401)
  ├─ retrieve_by_goal_relevance()
  ├─ Algorithm Versions (v1_keyword, v2_embedding, hybrid)
  ├─ Stable API Boundary
  
## Integration
  ├─ ContextProtocol.get_retrieval_module()
  ├─ Goal-Centric Retrieval Flow
```

**Benefits**:
- Context architecture unified (protocol + retrieval module)
- Goal-centric retrieval co-located with protocol definition
- Clear component: Context "consciousness" architecture

---

#### Merge 2: MemoryProtocol & Context Separation (RFC-402)

**Merge Source**: RFC-402 + RFC-403
**New Title**: "MemoryProtocol: Cross-Thread Memory & Context Separation"
**Estimated Lines**: ~400-500 lines

**Merge Logic**:
- RFC-402 (MemoryProtocol): Cross-thread memory (~200 lines)
- RFC-403 (Separation): Context vs Memory principles (~200 lines)

**Combined Content**:
```
## MemoryProtocol Interface (from RFC-402)
  ├─ remember(item)
  ├─ recall(query)
  ├─ recall_by_tags()
  
## Design Principles (from RFC-402)
  ├─ Cross-Thread Persistence
  ├─ Semantic Recall
  
## Context vs Memory Separation (from RFC-403)
  ├─ Context: Within-Thread Knowledge
  ├─ Memory: Cross-Thread Knowledge
  ├─ Integration Patterns
  ├─ Distinct Persistence
  
## Memory Integration Flow
  ├─ Thread Start: recall → ingest
  ├─ Thread End: remember significant responses
```

**Benefits**:
- Memory architecture unified with separation principles
- Context/Memory distinction co-located with Memory definition
- Clear boundary: Context (unbounded) vs Memory (explicit populate)

---

#### Merge 3: PlannerProtocol & Two-Phase Architecture (RFC-404)

**Merge Source**: RFC-404 + RFC-405
**New Title**: "PlannerProtocol: Plan Creation & Two-Phase Reasoning"
**Estimated Lines**: ~450-550 lines

**Merge Logic**:
- RFC-404 (PlannerProtocol): create_plan/revise_plan (~250 lines)
- RFC-405 (Two-Phase): StatusAssessment + PlanGeneration (~200 lines)

**Combined Content**:
```
## PlannerProtocol Interface (from RFC-404)
  ├─ create_plan(goal, context)
  ├─ revise_plan(plan, reflection)
  ├─ reflect(plan, step_results)
  
## Two-Phase Plan Architecture (from RFC-405)
  ├─ Phase 1: StatusAssessment
  ├─ Phase 2: PlanGeneration
  ├─ Token Efficiency
  ├─ LLMPlanner Implementation
  
## Integration
  ├─ create_plan() → Two-Phase Execution
  ├─ Plan Context Building
```

**Benefits**:
- Planner architecture unified (protocol + implementation pattern)
- Two-phase reasoning co-located with planner definition
- Clear component: Planning architecture

---

#### Merge 4: PolicyProtocol & Permission Architecture (RFC-406)

**Merge Source**: RFC-406 + RFC-407
**New Title**: "PolicyProtocol: Permission Checking & Scope Matching"
**Estimated Lines**: ~400-500 lines

**Merge Logic**:
- RFC-406 (PolicyProtocol): check/narrow_for_child (~200 lines)
- RFC-407 (Permission Structure): Permission model + scope matching (~200 lines)

**Combined Content**:
```
## PolicyProtocol Interface (from RFC-406)
  ├─ check(action, context)
  ├─ narrow_for_child(parent, child_name)
  
## Permission Structure (from RFC-407)
  ├─ Permission(category, action, scope)
  ├─ PermissionSet Collection
  ├─ Scope-Aware Matching
  ├─ PolicyProfile Configuration
  
## ConfigDrivenPolicy Implementation (from RFC-406)
  ├─ Evaluation Logic
  ├─ Permission Inheritance
  
## Integration
  ├─ Action Request → Policy Check
  ├─ Permission Set Narrowing
```

**Benefits**:
- Policy architecture unified (protocol + permission model)
- Scope matching co-located with policy definition
- Clear component: Permission architecture

---

#### Merge 5: DurabilityProtocol & Checkpoint Architecture (RFC-408)

**Merge Source**: RFC-408 + RFC-409
**New Title**: "DurabilityProtocol: Thread Lifecycle & Progressive Checkpoint"
**Estimated Lines**: ~500-600 lines

**Merge Logic**:
- RFC-408 (DurabilityProtocol): Thread lifecycle (~250 lines)
- RFC-409 (CheckpointEnvelope): Progressive checkpoint (~250 lines)

**Combined Content**:
```
## DurabilityProtocol Interface (from RFC-408)
  ├─ create_thread(metadata)
  ├─ resume_thread(thread_id)
  ├─ suspend_thread(thread_id)
  ├─ archive_thread(thread_id)
  
## Thread Lifecycle (from RFC-408)
  ├─ ThreadInfo Model
  ├─ ThreadMetadata
  ├─ ThreadFilter
  
## CheckpointEnvelope (from RFC-409)
  ├─ Progressive Checkpoint Model
  ├─ Goal/Plan/Step State Serialization
  ├─ Recovery Restoration
  
## Integration
  ├─ Thread Lifecycle → Checkpoint Persistence
  ├─ Recovery Flow
```

**Benefits**:
- Durability architecture unified (protocol + checkpoint model)
- Progressive checkpoint co-located with thread lifecycle
- Clear component: Persistence architecture

---

#### Merge 6: RemoteAgentProtocol Architecture (RFC-410)

**Merge Source**: RFC-410 + RFC-411 + RFC-412 + RFC-413
**New Title**: "RemoteAgentProtocol: Remote Invocation & Backend Implementations"
**Estimated Lines**: ~600-700 lines

**Merge Logic**:
- RFC-410 (RemoteAgentProtocol): Protocol interface (~150 lines)
- RFC-411 (LangGraphRemoteAgent): Primary implementation (~200 lines)
- RFC-412 (ACP): Planned backend (~100 lines stub)
- RFC-413 (A2A): Planned backend (~100 lines stub)

**Combined Content**:
```
## RemoteAgentProtocol Interface (from RFC-410)
  ├─ invoke(task, context)
  ├─ stream(task, context)
  ├─ health_check()
  
## LangGraphRemoteAgent Implementation (from RFC-411)
  ├─ LangGraph RemoteGraph Integration
  ├─ Current Implementation Status
  
## Planned Backends (from RFC-412, 413)
  ├─ ACP Remote Agent (Stub)
  ├─ A2A Remote Agent (Stub)
  
## Future: CompiledSubAgent Wrapping
  ├─ Uniform Delegation Envelope
```

**Benefits**:
- Remote agent architecture unified (protocol + all implementations)
- Planned backends co-located with protocol
- Clear component: Remote agent invocation

---

### 4XX Consolidated Result

| Original | Merged Into | Lines | Status |
|----------|-------------|-------|--------|
| RFC-400 + 401 | **RFC-400** (Context + Retrieval) | ~550 | ✅ Merge |
| RFC-402 + 403 | **RFC-402** (Memory + Separation) | ~450 | ✅ Merge |
| RFC-404 + 405 | **RFC-404** (Planner + Two-Phase) | ~500 | ✅ Merge |
| RFC-406 + 407 | **RFC-406** (Policy + Permissions) | ~450 | ✅ Merge |
| RFC-408 + 409 | **RFC-408** (Durability + Checkpoint) | ~550 | ✅ Merge |
| RFC-410 + 411 + 412 + 413 | **RFC-410** (RemoteAgent + Backends) | ~650 | ✅ Merge |

**Total 4XX RFCs**: 14 → 6 (57% reduction)
**All merged RFCs**: <800 lines ✅

---

## Overall Consolidation Summary

### Before Consolidation

| Category | Original RFC Count | Fragmentation |
|----------|-------------------|---------------|
| 2XX Layer 2 | 15 | Highly fragmented (core loop split across 3, state split across 3, thread split across 4) |
| 4XX Core Protocols | 14 | Highly fragmented (each protocol split across 2-4 RFCs) |
| **Total** | 29 | - |

### After Consolidation

| Category | Consolidated RFC Count | Reduction | All <800 Lines |
|----------|------------------------|-----------|----------------|
| 2XX Layer 2 | 7 | 53% (8 RFCs merged) | ✅ Yes |
| 4XX Core Protocols | 6 | 57% (8 RFCs merged) | ✅ Yes |
| **Total** | 13 | 55% (16 RFCs merged) | ✅ All <800 |

---

## Merge Quality Assurance

### Line Count Verification

| Merged RFC | Estimated Lines | Constraint (<800) | Status |
|------------|-----------------|-------------------|--------|
| RFC-200 (Core Loop) | ~550 | ✅ | PASS |
| RFC-203 (State Management) | ~450 | ✅ | PASS |
| RFC-207 (Thread & Context) | ~650 | ✅ | PASS |
| RFC-213 (Reasoning Quality) | ~350 | ✅ | PASS |
| RFC-400 (Context + Retrieval) | ~550 | ✅ | PASS |
| RFC-402 (Memory + Separation) | ~450 | ✅ | PASS |
| RFC-404 (Planner + Two-Phase) | ~500 | ✅ | PASS |
| RFC-406 (Policy + Permissions) | ~450 | ✅ | PASS |
| RFC-408 (Durability + Checkpoint) | ~550 | ✅ | PASS |
| RFC-410 (RemoteAgent + Backends) | ~650 | ✅ | PASS |

**Result**: All merged RFCs <800 lines ✅

---

### Architectural Coherence Verification

| Merge | Components Merged | Architectural Boundary | Status |
|-------|-------------------|------------------------|--------|
| RFC-200 | Loop + Decision + Result | ✅ AgentLoop Core Loop | COHERENT |
| RFC-203 | Working Memory + LoopState + Checkpoint | ✅ AgentLoop State | COHERENT |
| RFC-207 | Thread Lifecycle + Goal Context + Relationships | ✅ Thread Management | COHERENT |
| RFC-213 | Progressive Actions + Two-Phase | ✅ Reasoning Quality | COHERENT |
| RFC-400 | ContextProtocol + RetrievalModule | ✅ Context Architecture | COHERENT |
| RFC-402 | MemoryProtocol + Context Separation | ✅ Memory Architecture | COHERENT |
| RFC-404 | PlannerProtocol + Two-Phase Plan | ✅ Planner Architecture | COHERENT |
| RFC-406 | PolicyProtocol + Permission Structure | ✅ Policy Architecture | COHERENT |
| RFC-408 | DurabilityProtocol + CheckpointEnvelope | ✅ Durability Architecture | COHERENT |
| RFC-410 | RemoteAgentProtocol + Implementations | ✅ Remote Agent Architecture | COHERENT |

**Result**: All merges architecturally coherent ✅

---

## Migration Strategy

### Phase 1: Create Merged RFC Drafts

For each merge proposal:
1. Create merged RFC draft in `docs/drafts/`
2. Combine content from source RFCs
3. Remove duplicate sections (status, dependencies, created dates)
4. Update cross-references within merged content
5. Verify line count <800
6. Mark merged RFC as "Draft" status

### Phase 2: Create Alias RFCs

For each source RFC merged:
1. Create alias file preserving original number
2. Mark status: "Alias - Merged into RFC-XXX"
3. Redirect to merged RFC location
4. Preserve backward compatibility

### Phase 3: Update Cross-References

1. Update RFC-000 dependencies section
2. Update all RFC text references to merged RFCs
3. Update IG implementation guide references
4. Update index documents

### Phase 4: Update Index & History

1. `rfc-index.md`: Document merges with both original and merged numbers
2. `rfc-history.md`: Record merge decisions
3. Update `rfc-namings.md` if terminology changed

### Phase 5: Deprecate Source RFCs

1. Mark source RFC aliases as "Deprecated - Merged"
2. Archive original source RFC files (preserve history)
3. Keep aliases for backward compatibility (permanent)

---

## Standalone RFC Recommendations

### 2XX Standalone RFCs (Keep Separate)

| RFC | Title | Reason | Lines |
|-----|-------|--------|-------|
| RFC-206 | Prompt Architecture | Cross-cutting concern (Plan + Execute prompts) | ~200 |
| RFC-211 | Tool Result Optimization | Specific to evidence flow, not core loop | ~150 |
| RFC-212 | Subagent Parallel Spawning | **Move to 5XX Concurrency** (better categorization) | ~150 |

**Recommendation**: RFC-212 should move to 5XX (RFC-512) - concurrency pattern better fits execution control category.

### 4XX Standalone RFCs (None)

All 4XX protocol RFCs logically merged into unified protocol architecture RFCs. No standalone protocol RFCs recommended.

---

## Comparison: Original vs Consolidated

### 2XX Layer 2

| Metric | Original | Consolidated | Improvement |
|--------|----------|-------------|-------------|
| RFC Count | 15 | 7 | 53% reduction |
| Average Lines | ~150 (fragmented) | ~450 (cohesive) | Better coherence |
| Core Loop Coverage | 3 separate RFCs | 1 unified RFC | ✅ |
| State Coverage | 3 separate RFCs | 1 unified RFC | ✅ |
| Thread Coverage | 4 separate RFCs | 1 unified RFC | ✅ |

### 4XX Core Protocols

| Metric | Original | Consolidated | Improvement |
|--------|----------|-------------|-------------|
| RFC Count | 14 | 6 | 57% reduction |
| Average Lines | ~150 (fragmented) | ~500 (cohesive) | Better coherence |
| Protocol Coverage | Each split across 2-4 RFCs | Each unified in 1 RFC | ✅ |

---

## Final Recommendation

**Proceed with RFC Merge Plan**:

✅ **2XX Layer 2**: 15 → 7 RFCs (8 merges, all <800 lines)
✅ **4XX Core Protocols**: 14 → 6 RFCs (8 merges, all <800 lines)
✅ **Total Reduction**: 29 → 13 RFCs (55% reduction)
✅ **Architectural Coherence**: All merges logically unified
✅ **Line Count Constraint**: All merged RFCs <800 lines

**Next Actions**:
1. Create merged RFC drafts (10 drafts, one per merged RFC)
2. Verify line counts during draft creation
3. Execute migration strategy (Phase 1-5)
4. Update architecture review report with consolidated RFC mapping

---

**Merge Plan Complete**: 16 RFCs consolidated, 10 merged RFCs proposed, all <800 lines, all architecturally coherent.