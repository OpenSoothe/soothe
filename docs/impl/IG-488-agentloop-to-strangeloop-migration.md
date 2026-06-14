# IG-488: AgentLoop → StrangeLoop Name Migration

## Scope
Rename `AgentLoop` to `StrangeLoop` (short alias: `Sloop`) across the entire codebase.

## Naming Decisions
| Old | New |
|-----|-----|
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

## Status
- [x] Phase 1: Core Python (classes, protocols, files) - DONE
  - Classes renamed: `agent_loop.py` → `strange_loop.py`, `manager.py` → `sloop_manager.py`
  - RuntimeContext updated: `agent_loop` field → `strange_loop` field
  - Orchestrator builder/runner updated
- [x] Phase 2: Events - DONE
  - Event classes renamed: `Agentic*` → `StrangeLoop*`
  - Event registrations updated in catalog.py
  - Exports updated in `__init__.py`
- [x] Phase 3: Tests - DONE
  - Mock patch paths updated to new module paths
  - Test imports updated to use `StrangeLoop*` names
- [x] Phase 4: Backward Compatibility Removal - DONE
  - Removed all `Agentic* = StrangeLoop*` aliases from catalog.py
  - Removed `Agentic*` exports from `__init__.py`
  - Removed `_STRANGE_LOOP_CHECKPOINT_STATUSES` alias
  - Updated SDK comment to use `StrangeLoopStepCompletedEvent`
  - Updated runner imports to use `StrangeLoop*` event names
- [x] Phase 5: Go Client - DONE
  - Updated `client/go/events.go`: `EventAgentLoop*` → `EventStrangeLoop*`
  - Updated event namespace: `soothe.cognition.agent_loop.*` → `soothe.cognition.strange_loop.*`
  - Updated comments referencing AgentLoop
- [x] Phase 6: TypeScript Client - DONE
  - Updated `client/typescript/src/events.ts`: `EventAgentLoop*` → `EventStrangeLoop*`
  - Updated `ESSENTIAL_EVENT_TYPES` set
  - Updated exports in `index.ts`
  - Updated comments in `client.ts` and `protocol.ts`
  - Updated tests in `test/events.test.ts`
- [x] Phase 7: Documentation - DONE
  - Wiki, analysis docs, and cross-references updated to StrangeLoop terminology
- [x] Phase 8: Scripts/Diagrams - DONE
  - Renamed `visualize_strange_loop_graph.py` and diagram assets

## Verification
Run `./scripts/verify_finally.sh` - all checks pass.