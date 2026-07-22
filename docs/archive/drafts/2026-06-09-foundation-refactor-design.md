# Foundation and Core Modules Refactor Design

**Created**: 2026-06-09
**Status**: Draft
**Scope**: Architecture reorganization for three-layer separation

---

## Abstract

Refactor `soothe.core` into `soothe` with clear three-layer separation (CoreAgent, StrangeLoop, Autopilot). Define CoreAgentProtocol interface enabling future implementations. Merge GoalEngine with Autopilot as unified Layer 3. Move SootheRunner to top-level `soothe.runner` package.

---

## Motivation

### Current Problems

1. **Mixed layer responsibilities**: `soothe.core` contains 20+ subdirectories mixing all three layers plus shared utilities
2. **No explicit layer interfaces**: CoreAgent-Loop integration relies on implicit contract, not formal protocol
3. **CoreAgent not isolated**: CoreAgent code lives alongside Loop/Autopilot code, violating "core is unaware of higher layers" principle
4. **Scattered GoalEngine**: `goal_engine/` and `autopilot/` are separate but both serve Layer 3

### Goals

1. **Clear layer boundaries**: Each layer is self-contained in its own package
2. **CoreAgent isolation**: CoreAgent knows nothing about goals, plans, iterations
3. **Protocol-first design**: CoreAgentProtocol enables future implementations
4. **Foundation as comprehensive package**: Shared utilities + all three layers
5. **Runner as entry point**: Top-level package for daemon/CLI integration

---

## Proposed Architecture

### Directory Structure

```
soothe/
├── foundation/                    # Foundation layers + shared utilities
│   ├── __init__.py               # Re-exports public API
│   │
│   ├── core/                      # Layer 1: CoreAgent runtime
│   │   ├── __init__.py           # Re-exports CoreAgent, create_soothe_agent
│   │   ├── agent/                 # CoreAgent implementation
│   │   │   ├── __init__.py
│   │   │   ├── _builder.py       # create_soothe_agent()
│   │   │   ├── _core.py          # CoreAgent class
│   │   │   ├── _patch.py         # LangGraph patches
│   │   │   └── execute_tool_filter.py
│   │   ├── context/              # Tool context registry (core-specific)
│   │   │   ├── __init__.py
│   │   │   ├── tool_registry.py
│   │   │   ├── trigger_registry.py
│   │   │   └── model_override.py
│   │   ├── security/             # Policy enforcement (core-specific)
│   │   │   ├── __init__.py
│   │   │   ├── validator.py
│   │   │   ├── policy.py
│   │   │   ├── enforcement.py
│   │   │   └── operation_security.py
│   │   ├── filesystem/           # Filesystem operations (core-specific)
│   │   │   ├── __init__.py
│   │   │   ├── langchain_adapter.py
│   │   │   └── workspace.py
│   │   └── quiz_messages.py      # Quiz/clarification messages
│   │
│   ├── loop/                      # Layer 2: StrangeLoop orchestration
│   │   ├── __init__.py           # Re-exports StrangeLoop, LoopState, PlanResult
│   │   ├── engine/               # Plan-Execute engine
│   │   │   ├── __init__.py
│   │   │   ├── strange_loop.py    # StrangeLoop main class
│   │   │   ├── executor.py      # Step execution
│   │   │   ├── synthesis.py     # Result synthesis
│   │   │   ├── anchor_manager.py
│   │   │   ├── context_window_manager.py
│   │   │   ├── checkpoint_copy.py
│   │   │   ├── goal_context_manager.py
│   │   │   ├── metadata_generator.py
│   │   │   ├── predecessor_branch_context.py
│   │   │   ├── scenario_classifier.py
│   │   │   ├── synthesis_projection.py
│   │   │   ├── thread_fork_manager.py
│   │   │   ├── thread_switch_policy.py
│   │   │   ├── tool_call_args.py
│   │   │   ├── tool_result_registry.py
│   │   │   ├── graph_interrupt.py
│   │   │   └── fallback_summary.py
│   │   ├── orchestrator/         # Graph nodes, routing
│   │   │   ├── __init__.py
│   │   │   ├── builder.py
│   │   │   ├── routing.py
│   │   │   ├── runner.py
│   │   │   ├── runtime_context.py
│   │   │   ├── state.py
│   │   │   ├── phase_scratch.py
│   │   │   ├── checkpointer.py
│   │   │   ├── evidence.py
│   │   │   └── nodes/           # Graph node implementations
│   │   ├── planning/             # Planner integration
│   │   │   ├── __init__.py
│   │   │   ├── manager.py
│   │   │   ├── phase.py
│   │   │   ├── simple_bypass.py
│   │   │   └── prompts/         # Planning prompts
│   │   ├── state/                # LoopState, schemas, persistence
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py       # LoopState, PlanResult, StepAction
│   │   │   ├── working_memory.py
│   │   │   ├── manager.py
│   │   │   └── persistence/     # State persistence
│   │   ├── clarification/        # Clarification handling
│   │   │   ├── __init__.py
│   │   │   ├── policy.py
│   │   │   ├── prompts.py
│   │   │   └── events.py
│   │   ├── utils/                # Loop utilities
│   │   │   ├── __init__.py
│   │   │   ├── messages.py
│   │   │   ├── reflection.py
│   │   │   ├── stream_normalize.py
│   │   │   └── events.py
│   │   ├── prompts/              # Prompt building (loop-specific)
│   │   │   ├── __init__.py
│   │   │   ├── builder.py
│   │   │   ├── context_xml.py
│   │   │   ├── fragments.py
│   │   │   ├── system_templates.py
│   │   │   ├── user_envelope.py
│   │   │   ├── project_instructions.py
│   │   │   └── plan_ledger_projection.py
│   │   └── intention/            # Intent classification (loop-specific)
│   │   │   ├── __init__.py
│   │   │   ├── classifier.py
│   │   │   ├── models.py
│   │   │   └── prompts.py
│   │
│   ├── autopilot/                 # Layer 3: Goal orchestration (merged)
│   │   ├── __init__.py           # Re-exports GoalEngine, AutopilotService
│   │   ├── engine/               # GoalEngine (goal lifecycle)
│   │   │   ├── __init__.py
│   │   │   ├── engine.py        # GoalEngine class
│   │   │   ├── models.py        # Goal, BackoffDecision, EvidenceBundle
│   │   │   ├── backoff_reasoner.py
│   │   │   ├── discovery.py     # Goal discovery from files
│   │   │   ├── criticality.py   # Criticality assessment
│   │   │   ├── consensus.py     # Goal completion evaluation
│   │   │   ├── semantic_risk_classifier.py
│   │   │   ├── relationship_detector.py
│   │   │   ├── semantic_relationship_detector.py
│   │   │   └── file_lock_registry.py
│   │   ├── service/              # AutopilotService (daemon dispatch)
│   │   │   ├── __init__.py
│   │   │   ├── service.py       # AutopilotService class
│   │   │   ├── worker_pool.py   # WorkerPool
│   │   │   ├── context_projector.py
│   │   │   ├── context_store.py
│   │   │   ├── durability_context_store.py
│   │   │   ├── loop_pool.py     # Legacy LoopPool (backcompat)
│   │   │   └── workspace_reservation.py
│   │   ├── scheduled_tasks.py    # SchedulerService
│   │   ├── proposal_queue.py     # Proposal queue
│   │   ├── webhooks.py           # Webhook handling
│   │   ├── dreaming.py           # Dreaming state
│   │   ├── writer.py             # Goal file updates
│   │   ├── __init__.py           # Package exports
│   │
│   ├── events/                    # Shared: Event system
│   │   ├── __init__.py
│   │   ├── constants.py          # Event type strings
│   │   ├── catalog.py            # Event models, registry
│   │   ├── visibility.py         # Event visibility helpers
│   │   ├── internal_bus.py       # InternalEventBus (RFC-222)
│   │   └── internal_events.py    # Internal event types
│   │
│   ├── workspace/                 # Shared: Workspace resolution
│   │   ├── __init__.py
│   │   ├── resolution.py         # Daemon/client workspace validation
│   │   ├── stream_resolution.py  # Unified stream resolution
│   │   ├── runtime_resolution.py # Tool execution resolution
│   │   ├── core_resolution.py    # Core workspace resolution
│   │   ├── loop_workspace.py     # Loop workspace utilities
│   │   ├── normalized_backend.py # WorkspaceAwareBackend
│   │   ├── framework_filesystem.py # FrameworkFilesystem singleton
│   │   ├── tool_path_resolution.py # Tool path resolution
│   │   ├── virtual_home.py       # Virtual home management
│   │   ├── context.py            # WorkspaceContext
│   │   └── migration.py          # Workspace migration
│   │
│   ├── persistence/               # Shared: Artifact store
│   │   ├── __init__.py
│   │   └── artifact_store.py     # RunArtifactStore
│   │
│   ├── base_events.py             # Base event types (existing)
│   ├── types.py                   # Shared types (existing)
│   └── ai_message.py              # AI message helpers (existing)
│
├── runner/                        # Top-level orchestrator (daemon-facing)
│   ├── __init__.py               # SootheRunner
│   ├── phases.py                 # Execution phases
│   ├── thread_manager.py         # Thread lifecycle
│   ├── resolver.py               # Protocol resolution
│   ├── concurrency.py            # Concurrency control
│   ├── artifact_store.py         # Run artifacts
│   ├── autopilot_worker.py       # Autopilot worker runner
│   ├── worker_utils.py           # Worker utilities
│   ├── worker_logging.py         # Worker logging
│   └── types.py                  # Runner types
│
├── protocols/                     # ALL abstract protocol interfaces
│   ├── __init__.py
│   ├── context.py                # ContextProtocol (existing)
│   ├── memory.py                 # MemoryProtocol (existing)
│   ├── planner.py                # PlannerProtocol (existing)
│   ├── policy.py                 # PolicyProtocol (existing)
│   ├── durability.py             # DurabilityProtocol (existing)
│   ├── concurrency.py            # ConcurrencyPolicy (existing)
│   ├── loop_planner.py           # LoopPlannerProtocol (existing)
│   ├── runner.py                 # LoopRunRequest, GoalDispatchEnvelope (existing)
│   ├── persistence.py            # AsyncPersistStore (existing)
│   │
│   ├── core_agent.py             # NEW: CoreAgentProtocol
│   ├── strange_loop.py             # NEW: StrangeLoopProtocol (optional)
│   └── autopilot.py              # NEW: AutopilotProtocol (optional)
│
├── backends/                      # Protocol implementations (unchanged)
├── config/                        # SootheConfig (unchanged)
├── middleware/                    # Soothe middlewares (unchanged)
├── mcp/                           # MCP integration (unchanged)
├── plugin/                        # Plugin system (unchanged)
├── toolkits/                      # Tools (unchanged)
├── subagents/                     # Subagents (unchanged)
├── skills/                        # Skills (unchanged)
├── logging/                       # Logging utilities (unchanged)
├── utils/                         # General utilities (unchanged)
```

---

## CoreAgentProtocol Definition

```python
# soothe/protocols/core_agent.py
from typing import Protocol, Any, runtime_checkable
from collections.abc import AsyncIterator

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph

    from soothe.config import SootheConfig


@runtime_checkable
class CoreAgentProtocol(Protocol):
    """Layer 1 runtime interface - unaware of Loop or Autopilot concepts.

    CoreAgent provides pure execution runtime for:
    - Tool invocation
    - Subagent delegation (via deepagents task tool)
    - Middleware processing
    - Streaming execution

    This protocol enables alternative CoreAgent implementations while
    keeping the execution contract stable for Loop/Autopilot layers.

    Implementation requirements:
    - Must support config.configurable hints:
      - thread_id: Thread identifier for persistence
      - workspace: Thread-specific workspace path
      - soothe_step_subagent: Advisory subagent hint
      - soothe_step_expected_output: Advisory expected result
    - Must apply Soothe middleware stack (policy, prompts, hints, workspace)
    - Must return streaming results compatible with LangGraph stream modes
    """

    @property
    def graph(self) -> CompiledStateGraph:
        """Underlying LangGraph for advanced operations.

        Note: This property is implementation-specific. Alternative
        implementations may not use LangGraph and should raise
        NotImplementedError or return a compatible adapter.
        """
        ...

    async def astream(
        self,
        input: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
    ) -> AsyncIterator[Any]:
        """Execute with streaming interface.

        Args:
            input: User text (normalized to HumanMessage) or LangGraph
                state dict with 'messages' key.
            config: RunnableConfig with:
                - configurable.thread_id: Thread identifier
                - configurable.workspace: Thread workspace path
                - configurable.soothe_step_subagent: Subagent hint (optional)
                - configurable.soothe_step_expected_output: Result hint (optional)
            stream_mode: Stream modes - ["messages", "updates", "custom"]
            subgraphs: Include subgraph events in stream

        Returns:
            AsyncIterator yielding stream chunks. Chunk format depends
            on stream_mode:
            - "messages": (message_metadata, message_chunk)
            - "updates": (node_name, update_dict)
            - "custom": custom event dicts
        """
        ...

    @classmethod
    def create(cls, config: SootheConfig, **kwargs: Any) -> CoreAgentProtocol:
        """Factory method for creating CoreAgent instances.

        Args:
            config: SootheConfig with provider/model settings
            **kwargs: Implementation-specific arguments

        Returns:
            CoreAgentProtocol instance ready for execution
        """
        ...
```

---

## StrangeLoopProtocol Definition (Optional)

```python
# soothe/protocols/strange_loop.py
from typing import Protocol, runtime_checkable

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgentProtocol
    from soothe.sloop.state.schemas import LoopState, PlanResult


@runtime_checkable
class StrangeLoopProtocol(Protocol):
    """Layer 2 StrangeLoop interface - Plan-Execute orchestration.

    StrangeLoop executes single goals through iterative refinement:
    - Plan: LLM reasoning with goal-directed evaluation
    - Execute: Step execution via CoreAgentProtocol
    - Judge: Progress assessment toward goal

    This protocol enables alternative StrangeLoop implementations while
    maintaining CoreAgent isolation (Loop knows Core, Core doesn't know Loop).
    """

    async def run_iteration(
        self,
        state: LoopState,
    ) -> PlanResult:
        """Execute one Plan-Execute iteration.

        Args:
            state: LoopState with goal, iteration count, plan context

        Returns:
            PlanResult with status (continue/replan/done), evidence,
            and optional next steps.
        """
        ...

    @classmethod
    def create(
        cls,
        config: SootheConfig,
        core_agent: CoreAgentProtocol,
    ) -> StrangeLoopProtocol:
        """Factory method requiring CoreAgentProtocol dependency.

        Args:
            config: SootheConfig with loop settings
            core_agent: CoreAgentProtocol instance for execution

        Returns:
            StrangeLoopProtocol instance ready for iteration.
        """
        ...
```

---

## AutopilotProtocol Definition (Optional)

```python
# soothe/protocols/autopilot.py
from typing import Protocol, runtime_checkable

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.autopilot.engine_models import Goal


@runtime_checkable
class AutopilotProtocol(Protocol):
    """Layer 3 Autopilot interface - Goal lifecycle and dispatch.

    Autopilot manages:
    - Goal DAG orchestration (create, schedule, dependencies)
    - Goal lifecycle (pending, active, completed, failed)
    - Backoff reasoning on failure
    - Dispatch to StrangeLoop workers

    This protocol enables alternative Autopilot implementations while
    maintaining StrangeLoop isolation (Autopilot dispatches to Loop,
    Loop doesn't know Autopilot internals).
    """

    def get_next_ready_goal(self) -> Goal | None:
        """Get next goal ready for execution (DAG-satisfied).

        Returns:
            Goal with dependencies satisfied, or None.
        """
        ...

    def complete_goal(self, goal_id: str, plan_result: PlanResult) -> None:
        """Mark goal completed with Layer 2 evidence."""
        ...

    async def fail_goal(
        self,
        goal_id: str,
        evidence: EvidenceBundle,
    ) -> BackoffDecision | None:
        """Mark goal failed, apply backoff reasoning."""
        ...

    @classmethod
    def create(cls, config: SootheConfig) -> AutopilotProtocol:
        """Factory method for creating Autopilot instances."""
        ...
```

---

## Module Migration Summary

| Current Location | New Location | Layer Affinity |
|------------------|--------------|----------------|
| `soothe.core.agent/` | `soothe.core.agent/` | Core |
| `soothe.core.context/` | `soothe.core.context/` | Core |
| `soothe.core.security/` | `soothe.security/` | Core |
| `soothe.core.filesystem/` | `soothe.filesystem/` | Core |
| `soothe.core.quiz_messages.py` | `soothe.core.quiz_messages.py` | Core |
| `soothe.core.loop/` | `soothe.sloop/` | Loop |
| `soothe.core.prompts/` | `soothe.sloop.prompts/` | Loop |
| `soothe.core.intention/` | `soothe.sloop.intention/` | Loop |
| `soothe.core.goal_engine/` | `soothe.autopilot/` | Autopilot |
| `soothe.core.autopilot/` | `soothe.autopilot/` | Autopilot |
| `soothe.core.events/` | `soothe.events/` | Shared |
| `soothe.core.workspace/` | `soothe.workspace/` | Shared |
| `soothe.core.persistence/` | `soothe.persistence/` | Shared |
| `soothe.core.runner/` | `soothe.runner/` | Top-level |
| `soothe.core.resolver/` | `soothe.runner.resolver/` | Runner-owned |
| `soothe.base_events.py` | `soothe.base_events.py` | Unchanged |
| `soothe.types.py` | `soothe.types.py` | Unchanged |
| `soothe.ai_message.py` | `soothe.ai_message.py` | Unchanged |

---

## Import Path Changes

### Before → After

| Before | After |
|--------|-------|
| `from soothe.core import CoreAgent` | `from soothe.core import CoreAgent` |
| `from soothe.core.agent import create_soothe_agent` | `from soothe.core.agent import create_soothe_agent` |
| `from soothe.core.loop import StrangeLoop` | `from soothe.sloop import StrangeLoop` |
| `from soothe.core.loop.state.schemas import LoopState` | `from soothe.sloop.state.schemas import LoopState` |
| `from soothe.core.goal_engine import GoalEngine` | `from soothe.autopilot import GoalEngine` |
| `from soothe.core.autopilot import AutopilotService` | `from soothe.autopilot import AutopilotService` |
| `from soothe.core import SootheRunner` | `from soothe.runner import SootheRunner` |
| `from soothe.core.events import GOAL_CREATED` | `from soothe.events import GOAL_CREATED` |
| `from soothe.core.workspace import resolve_daemon_workspace` | `from soothe.workspace import resolve_daemon_workspace` |

### Backward Compatibility

Lazy imports in `soothe.core.__init__.py` will redirect to new locations:

```python
# soothe/core/__init__.py (backward compatibility shim)
"""Deprecated - use soothe imports instead."""

def __getattr__(name: str) -> Any:
    import warnings
    warnings.warn(
        f"soothe.core.{name} is deprecated. Use soothe imports.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Redirect to new locations
    if name == "CoreAgent":
        from soothe.core import CoreAgent
        return CoreAgent
    if name == "create_soothe_agent":
        from soothe.core.agent import create_soothe_agent
        return create_soothe_agent
    # ... etc
```

---

## Implementation Phases

### Phase 1: Create Protocol Interfaces (Low Risk)

1. Add `soothe.protocols/core_agent.py` with CoreAgentProtocol
2. Add `soothe.protocols/strange_loop.py` with StrangeLoopProtocol
3. Add `soothe.protocols/autopilot.py` with AutopilotProtocol
4. Update protocol `__init__.py` exports
5. Verify existing implementations satisfy protocols

**Duration**: ~1 day
**Risk**: Low (additive changes only)

### Phase 2: Create Foundation Package Structure (Medium Risk)

1. Create `soothe/core/`, `loop/`, `autopilot/` directories
2. Create `soothe.runner/` directory
3. Create package `__init__.py` files with re-exports
4. Move shared utilities (events, workspace, persistence)
5. Run tests to verify no import breakage

**Duration**: ~2 days
**Risk**: Medium (directory moves, import updates)

### Phase 3: Move Layer Modules (High Risk)

1. Move `soothe.core.agent/` → `soothe.core.agent/`
2. Move `soothe.core.loop/` → `soothe.sloop/`
3. Move `soothe.core.goal_engine/` → `soothe.autopilot/`
4. Move `soothe.core.autopilot/` → `soothe.autopilot/`
5. Move `soothe.core.runner/` → `soothe.runner/`
6. Update all internal imports across packages
7. Run full test suite

**Duration**: ~3-4 days
**Risk**: High (many import changes, circular dependency risk)

### Phase 4: Update External Consumers (Medium Risk)

1. Update `soothe_daemon/` imports
2. Update `soothe_cli/` imports
3. Update `soothe_sdk/` imports (if any cross-package refs)
4. Update `middleware/`, `toolkits/`, `subagents/` imports
5. Update test imports
6. Add backward compatibility shim to `soothe.core.__init__.py`

**Duration**: ~2 days
**Risk**: Medium (external package updates)

### Phase 5: Cleanup and Documentation (Low Risk)

1. Remove old empty `soothe.core/` directories
2. Update `docs/specs/` RFC references
3. Update `CLAUDE.md` architecture section
4. Update `soothe.core/README.md` → deprecation notice
5. Create `soothe/README.md`
6. Run verification script

**Duration**: ~1 day
**Risk**: Low

---

## Testing Strategy

### Unit Tests

1. Protocol satisfaction tests - verify CoreAgent implements CoreAgentProtocol
2. Import path tests - verify new paths resolve correctly
3. Backward compatibility tests - verify shim redirects work

### Integration Tests

1. Runner integration - verify SootheRunner works with new imports
2. Daemon integration - verify daemon starts with new structure
3. Autopilot integration - verify GoalEngine dispatch works

### Verification Script

Run `./scripts/verify_finally.sh` after each phase:
- Format check passes
- Lint passes (zero errors)
- Unit tests pass (900+ tests)

---

## Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Circular imports | Build failure | Import analysis before moves, lazy imports |
| Missing import updates | Runtime errors | Comprehensive grep, phased migration |
| Test breakage | CI failure | Run tests after each move batch |
| External consumer breakage | Integration failure | Backward compatibility shim |
| RFC/documentation drift | Confusion | Update docs in Phase 5 |

---

## Success Criteria

1. **Clear layer boundaries**: Each layer package is self-contained
2. **CoreAgent isolation**: No imports of loop/autopilot concepts in core
3. **Protocol interface**: CoreAgentProtocol defined and implemented
4. **All tests pass**: `./scripts/verify_finally.sh` succeeds
5. **Backward compatible**: Existing imports work via shim
6. **Documentation updated**: RFCs reflect new structure

---

## References

- RFC-000: System Conceptual Design (three-layer architecture)
- RFC-201: StrangeLoop Plan-Execute Loop Architecture
- RFC-200: Autonomous Goal Management Loop
- RFC-100: CoreAgent runtime (implicit in agent/ module)
- IG-276: Core Directory Refactoring (prior work)