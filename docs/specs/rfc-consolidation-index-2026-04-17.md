# RFC Consolidation Index (2026-04-17)

**Consolidation Date**: 2026-04-17
**Consolidation Status**: Complete (Phases 1-2), Cross-references Updated (Phase 3)

---

## Overview

RFC consolidation merged 16 RFCs into 10 unified RFC drafts while maintaining backward compatibility through 16 alias files. This index documents the consolidation mapping and provides navigation to merged content.

---

## Merged RFCs (10 Unified RFC Drafts)

### 2XX Layer 2 - AgentLoop (4 merged RFCs)

| Merged RFC Draft | Original RFCs Merged | Lines | Location |
|------------------|---------------------|-------|----------|
| **RFC-200** (Core Loop) | RFC-200 + RFC-201 + RFC-202 | 372 | [Draft](../drafts/2026-04-17-rfc-200-agentloop-core-loop-merged.md) |
| **RFC-203** (State & Memory) | RFC-203 + RFC-204 + RFC-205 | 427 | [Draft](../drafts/2026-04-17-rfc-203-agentloop-state-management-merged.md) |
| **RFC-207** (Thread & Context) | RFC-207 + RFC-208 + RFC-209 + RFC-210 | 419 | [Draft](../drafts/2026-04-17-rfc-207-agentloop-thread-context-merged.md) |
| **RFC-213** (Reasoning Quality) | RFC-213 + RFC-214 | 264 | [Draft](../drafts/2026-04-17-rfc-213-agentloop-reasoning-quality-merged.md) |

### 4XX Core Protocols (6 merged RFCs)

| Merged RFC Draft | Original RFCs Merged | Lines | Location |
|------------------|---------------------|-------|----------|
| **RFC-400** (ContextProtocol) | RFC-001 Module 1 + RFC-401 | 379 | [Draft](../drafts/2026-04-17-rfc-400-context-protocol-retrieval-merged.md) |
| **RFC-402** (MemoryProtocol) | RFC-001 Module 2 + RFC-403 | 236 | [Draft](../drafts/2026-04-17-rfc-402-memory-protocol-merged.md) |
| **RFC-404** (PlannerProtocol) | RFC-001 Module 3 + RFC-405 | 238 | [Draft](../drafts/2026-04-17-rfc-404-planner-protocol-merged.md) |
| **RFC-406** (PolicyProtocol) | RFC-001 Module 4 + RFC-407 | 305 | [Draft](../drafts/2026-04-17-rfc-406-policy-protocol-merged.md) |
| **RFC-408** (DurabilityProtocol) | RFC-001 Module 5 + RFC-409 | 299 | [Draft](../drafts/2026-04-17-rfc-408-durability-protocol-merged.md) |
| **RFC-410** (RemoteAgentProtocol) | RFC-001 Module 6 + RFC-411-413 | 315 | [Draft](../drafts/2026-04-17-rfc-410-remote-agent-protocol-merged.md) |

**Total**: 10 merged RFCs, 3,254 lines (average 325 lines per RFC)

---

## Alias RFCs (16 Backward Compatibility Files)

### 2XX Layer 2 Aliases (8 files)

| Alias RFC | Redirects To | Original Content | Location |
|-----------|-------------|------------------|----------|
| RFC-201-alias | RFC-200 | AgentDecision merged into Core Loop | [Alias](./RFC-201-alias.md) |
| RFC-202-alias | RFC-200 | PlanResult merged into Core Loop | [Alias](./RFC-202-alias.md) |
| RFC-204-alias | RFC-203 | LoopState merged into State Management | [Alias](./RFC-204-alias.md) |
| RFC-205-alias | RFC-203 | CheckpointEnvelope merged into State | [Alias](./RFC-205-alias.md) |
| RFC-208-alias | RFC-207 | Goal Context Manager merged into Thread | [Alias](./RFC-208-alias.md) |
| RFC-209-alias | RFC-207 | Thread Relationship merged into Thread | [Alias](./RFC-209-alias.md) |
| RFC-210-alias | RFC-207 | Executor Coordination merged into Thread | [Alias](./RFC-210-alias.md) |
| RFC-214-alias | RFC-213 | Two-Phase Plan merged into Reasoning | [Alias](./RFC-214-alias.md) |

### 4XX Core Protocol Aliases (8 files)

| Alias RFC | Redirects To | Original Content | Location |
|-----------|-------------|------------------|----------|
| RFC-401-alias | RFC-400 | ContextRetrievalModule merged into Context | [Alias](./RFC-401-alias.md) |
| RFC-403-alias | RFC-402 | Context vs Memory Separation merged | [Alias](./RFC-403-alias.md) |
| RFC-405-alias | RFC-404 | Two-Phase Pattern merged into Planner | [Alias](./RFC-405-alias.md) |
| RFC-407-alias | RFC-406 | Permission Structure merged into Policy | [Alias](./RFC-407-alias.md) |
| RFC-409-alias | RFC-203 | CheckpointEnvelope moved to Layer 2 | [Alias](./RFC-409-alias.md) |
| RFC-411-alias | RFC-410 | LangGraphRemoteAgent merged into Remote | [Alias](./RFC-411-alias.md) |
| RFC-412-alias | RFC-410 | ACP Remote Agent merged into Remote | [Alias](./RFC-412-alias.md) |
| RFC-413-alias | RFC-410 | A2A Remote Agent merged into Remote | [Alias](./RFC-413-alias.md) |

**Total**: 16 alias RFCs preserving backward compatibility

---

## Consolidation Mapping Table

### Complete Original → Merged Mapping

| Original RFC | Merged Into | Status | Notes |
|--------------|-------------|--------|-------|
| RFC-200 (GoalEngine) | **KEPT** (updated with BackoffReasoner) | Active | Layer 3 core RFC, enhanced 2026-04-17 |
| RFC-201 (AgentDecision) | RFC-200 (merged) | Alias | Core loop unified |
| RFC-202 (PlanResult) | RFC-200 (merged) | Alias | Core loop unified |
| RFC-203 (Working Memory) | RFC-203 (merged) | Draft | State management unified |
| RFC-204 (LoopState) | RFC-203 (merged) | Alias | State management unified |
| RFC-205 (Checkpoint) | RFC-203 (merged) | Alias | State management unified |
| RFC-206 (Prompt Arch) | **KEPT** | Draft | Standalone (cross-cutting) |
| RFC-207 (Thread Lifecycle) | RFC-207 (merged) | Draft | Thread management unified |
| RFC-208 (Goal Context) | RFC-207 (merged) | Alias | Thread management unified |
| RFC-209 (Thread Relationship) | RFC-207 (merged) | Alias | Thread management unified |
| RFC-210 (Executor Coord) | RFC-207 (merged) | Alias | Thread management unified |
| RFC-211 (Tool Result) | **KEPT** | Draft | Standalone (specific evidence flow) |
| RFC-212 (Subagent Parallel) | **KEPT** (recategorize to 5XX) | Draft | Move to Concurrency category |
| RFC-213 (Progressive Actions) | RFC-213 (merged) | Draft | Reasoning quality unified |
| RFC-214 (Two-Phase Plan) | RFC-213 (merged) | Alias | Reasoning quality unified |
| RFC-001 Module 1 (Context) | RFC-400 (merged) | Draft | Protocol unified with retrieval |
| RFC-001 Module 2 (Memory) | RFC-402 (merged) | Draft | Protocol unified with separation |
| RFC-001 Module 3 (Planner) | RFC-404 (merged) | Draft | Protocol unified with pattern |
| RFC-001 Module 4 (Policy) | RFC-406 (merged) | Draft | Protocol unified with permissions |
| RFC-001 Module 5 (Durability) | RFC-408 (merged) | Draft | Protocol unified (thread lifecycle only) |
| RFC-001 Module 6 (Remote) | RFC-410 (merged) | Draft | Protocol unified with backends |
| RFC-001 Module 7 (Concurrency) | **KEPT** in RFC-001 | Active | Configuration model |
| RFC-001 Module 8 (VectorStore) | **KEPT** in RFC-001 | Active | Persistence backend |
| RFC-001 Module 9 (PersistStore) | **KEPT** in RFC-001 | Active | Implementation detail |
| RFC-401 (Retrieval Module) | RFC-400 (merged) | Alias | Context unified |
| RFC-403 (Context/Memory Separation) | RFC-402 (merged) | Alias | Memory unified |
| RFC-405 (Two-Phase Pattern) | RFC-404 (merged) | Alias | Planner unified |
| RFC-407 (Permission Structure) | RFC-406 (merged) | Alias | Policy unified |
| RFC-409 (CheckpointEnvelope) | RFC-203 (moved to Layer 2) | Alias | Execution state belongs in Layer 2 |
| RFC-411 (LangGraphRemote) | RFC-410 (merged) | Alias | Remote unified |
| RFC-412 (ACP Remote) | RFC-410 (merged) | Alias | Remote unified |
| RFC-413 (A2A Remote) | RFC-410 (merged) | Alias | Remote unified |

---

## Key Architectural Decisions

### Layer 2 vs Core Protocols Separation

**2XX Layer 2 RFCs contain**:
- AgentLoop execution implementations (CheckpointEnvelope, Two-Phase execution patterns)
- Layer-specific state management (LoopState, Working Memory)
- Thread lifecycle spanning logic

**4XX Core Protocols contain**:
- Protocol interfaces only (no Layer 2 implementation details)
- Cross-layer protocol primitives (Context, Memory, Planner, Policy, Durability, RemoteAgent)
- Runtime-agnostic definitions

**Corrected Overlaps**:
- CheckpointEnvelope moved from RFC-409 (DurabilityProtocol) to RFC-203 (Layer 2) - execution state belongs in Layer 2
- Two-Phase execution pattern documented in RFC-404 as implementation guidance, actual execution in RFC-200 (Layer 2)

---

## Implementation Guidance

### Using Merged RFCs

**For Implementation**:
- Use merged RFC drafts (10 unified RFCs in `docs/drafts/`)
- All implementation content preserved with better organization
- Architectural coherence improved (related designs unified)

**For Reference**:
- Original RFCs still available in `docs/specs/` (preserved for history)
- Alias RFCs provide backward compatibility (permanent)
- RFC-001 consolidation note added for navigation

**For Cross-References**:
- Update code/docstrings to use merged RFC numbers
- Example: "RFC-201" → "RFC-200 (merged, see RFC-201-alias)"
- Maintain backward compatibility through aliases

---

## 5-Phase Execution Status

| Phase | Status | Progress | Files Created |
|-------|--------|----------|---------------|
| **Phase 1** | ✅ Complete | 100% | 10 merged RFC drafts |
| **Phase 2** | ✅ Complete | 100% | 16 alias RFCs |
| **Phase 3** | ✅ Complete | 100% | Cross-references updated (RFC-000, RFC-001 notes added) |
| **Phase 4** | ✅ Complete | 100% | Index documents updated (this document) |
| **Phase 5** | ⚠️ Pending | 0% | Deprecation marking (optional) |

**Total Progress**: 90% complete (Phases 1-4 done)
**Files Created**: 27 files (10 drafts + 16 aliases + 1 consolidation index)

---

## Benefits Achieved

### Consolidation Results

- **RFC count reduction**: 29 → 13 RFCs (55% reduction)
- **Fragmentation eliminated**: Core loop, state, thread, each protocol unified
- **Architectural coherence**: Related designs co-located
- **Line constraint satisfied**: All merged RFCs <800 lines
- **Backward compatibility**: All 16 aliases preserve original numbers
- **No breaking changes**: Aliases permanent, originals preserved

---

## Next Actions

**Phase 5 Optional**:
- Mark alias RFCs as "Alias - Deprecated" (optional deprecation step)
- Archive original source RFCs to `docs/specs/archive/` (optional)
- Update implementation guides to use merged RFCs (can be done during implementation)

**Proceed to Implementation**:
- Use merged RFC drafts for IG-184 implementation
- Cross-references functional through aliases
- Consolidation complete and ready for production use

---

## Documents Created

1. ✅ RFC Merge Proposal (original plan document)
2. ✅ 10 Merged RFC Drafts (Phase 1)
3. ✅ 16 Alias RFCs (Phase 2)
4. ✅ RFC-000 Dependencies Update (Phase 3)
5. ✅ RFC-001 Consolidation Note (Phase 3)
6. ✅ **RFC Consolidation Index** (Phase 4, this document)
7. ✅ 5-Phase Progress Summary (overall tracking)

---

**Consolidation Complete**: 10 merged RFCs created, 16 aliases for backward compatibility, all cross-references updated, architectural separation verified. Ready for implementation.