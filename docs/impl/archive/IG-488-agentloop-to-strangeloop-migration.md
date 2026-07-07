# IG-488: AgentLoop → StrangeLoop Name Migration

## Scope
Renamed `AgentLoop` to `StrangeLoop` (short alias: `Sloop`) across the entire codebase.

> **Historical Context**: This migration was completed on 2025-06-14. The `AgentLoop` naming originated from early design iterations and was replaced with `StrangeLoop` to better reflect the self-referential, recursive nature of the orchestration pattern. All references below document the completed transformation.

## Naming Mapping (Completed Migration)

The following table documents the naming changes that were applied:

| Original Name | Migrated Name |
|---------------|---------------|
| `AgentLoop` class | `StrangeLoop` (alias: `Sloop`) |
| `AgentLoopProtocol` | `StrangeLoopProtocol` |
| `agent_loop.py` file | `strange_loop.py` |
| `manager.py` (state) | `sloop_manager.py` |
| `AgentLoopStateManager` | `StrangeLoopStateManager` |
| `AgentLoopCheckpoint` | `StrangeLoopCheckpoint` |
| `AgenticLoopStartedEvent` | `StrangeLoopStartedEvent` |
| `AgenticLoopCompletedEvent` | `StrangeLoopCompletedEvent` |
| `AgenticPlanDecisionEvent` | `StrangeLoopPlanDecisionEvent` |
| `AgenticStepStartedEvent` | `StrangeLoopStepStartedEvent` |
| `AgenticStepQueuedEvent` | `StrangeLoopStepQueuedEvent` |
| `AgenticStepCompletedEvent` | `StrangeLoopStepCompletedEvent` |
| `ContextCompactionEvent` | `StrangeLoopContextCompactionEvent` |
| Event namespace `soothe.cognition.agent_loop.*` | `soothe.cognition.strange_loop.*` |

## Completed Migration Phases

All phases of this migration were completed and verified:

### Phase 1: Core Python (classes, protocols, files)
- Renamed `agent_loop.py` → `strange_loop.py`, `manager.py` → `sloop_manager.py`
- Updated RuntimeContext: `agent_loop` field → `strange_loop` field
- Updated Orchestrator builder/runner

### Phase 2: Events
- Renamed event classes: `Agentic*` → `StrangeLoop*`
- Updated event registrations in catalog.py
- Updated exports in `__init__.py`

### Phase 3: Tests
- Updated mock patch paths to new module paths
- Updated test imports to use `StrangeLoop*` names

### Phase 4: Backward Compatibility Removal
- Removed all `Agentic* = StrangeLoop*` aliases from catalog.py
- Removed `Agentic*` exports from `__init__.py`
- Removed `_STRANGE_LOOP_CHECKPOINT_STATUSES` alias
- Updated SDK comment to use `StrangeLoopStepCompletedEvent`
- Updated runner imports to use `StrangeLoop*` event names

### Phase 5: Go Client
- Updated `client/go/events.go`: `EventAgentLoop*` → `EventStrangeLoop*`
- Updated event namespace: `soothe.cognition.agent_loop.*` → `soothe.cognition.strange_loop.*`
- Updated comments referencing AgentLoop

### Phase 6: TypeScript Client
- Updated `client/typescript/src/events.ts`: `EventAgentLoop*` → `EventStrangeLoop*`
- Updated `ESSENTIAL_EVENT_TYPES` set
- Updated exports in `index.ts`
- Updated comments in `client.ts` and `protocol.ts`
- Updated tests in `test/events.test.ts`

### Phase 7: Documentation
- Updated Wiki, analysis docs, and cross-references to StrangeLoop terminology

### Phase 8: Scripts/Diagrams
- Renamed `visualize_strange_loop_graph.py` and diagram assets

## Verification
All changes were verified with `./scripts/verify_finally.sh` - all checks passed.