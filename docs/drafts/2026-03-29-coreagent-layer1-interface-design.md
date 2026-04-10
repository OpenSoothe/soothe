# CoreAgent Layer 1 Interface Design

**Date**: 2026-03-29
**RFC**: RFC-100 (Layer 1 CoreAgent Runtime Architecture)
**Status**: Draft

## Problem Statement

`create_soothe_agent()` returns a raw `CompiledStateGraph` with ad-hoc protocol attachments (`agent.soothe_context`, `agent.soothe_memory`, etc.). This violates RFC-100's requirement for a self-contained Layer 1 module with a clear exposed interface.

**Specific issues:**
1. No type safety for protocol access - magic string attributes
2. `goal_engine` and `goal_tools` attached to Layer 1, but belong to Layer 3
3. No encapsulation of Layer 1-specific behavior
4. Factory return type is `CompiledStateGraph`, not a Soothe-specific type

## Design

### CoreAgent Class

A wrapper class with explicit typed properties, delegating execution to the underlying graph:

```python
class CoreAgent:
    """Layer 1 CoreAgent runtime (RFC-100).

    Self-contained module wrapping CompiledStateGraph with explicit
    typed protocol properties. Pure execution runtime - no goal
    infrastructure (Layer 3 responsibility).

    Attributes:
        graph: Underlying CompiledStateGraph
        config: SootheConfig used to create this agent
        context: ContextProtocol instance (or None)
        memory: MemoryProtocol instance (or None)
        planner: PlannerProtocol instance (or None)
        policy: PolicyProtocol instance (or None)
        subagents: List of configured subagents

    Execution Interface:
        astream(input, config) -> AsyncIterator[StreamChunk]

        config.configurable may include Layer 2 hints:
            - soothe_step_tools: suggested tools (advisory)
            - soothe_step_subagent: suggested subagent (advisory)
            - soothe_step_expected_output: expected result (advisory)
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        config: SootheConfig,
        context: ContextProtocol | None = None,
        memory: MemoryProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
        subagents: list[SubAgent | CompiledSubAgent] = [],
    ) -> None:
        self._graph = graph
        self._config = config
        self._context = context
        self._memory = memory
        self._planner = planner
        self._policy = policy
        self._subagents = subagents

    # --- Explicit typed properties ---
    @property
    def graph(self) -> CompiledStateGraph:
        return self._graph

    @property
    def config(self) -> SootheConfig:
        return self._config

    @property
    def context(self) -> ContextProtocol | None:
        return self._context

    @property
    def memory(self) -> MemoryProtocol | None:
        return self._memory

    @property
    def planner(self) -> PlannerProtocol | None:
        return self._planner

    @property
    def policy(self) -> PolicyProtocol | None:
        return self._policy

    @property
    def subagents(self) -> list[SubAgent | CompiledSubAgent]:
        return self._subagents

    # --- Execution interface ---
    async def astream(
        self,
        input: str | dict,
        config: RunnableConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Execute with Layer 1 streaming interface.

        Args:
            input: User query or execution instruction
            config: RunnableConfig with thread_id and optional Layer 2 hints

        Returns:
            AsyncIterator of StreamChunk events
        """
        return self._graph.astream(input, config or {})

    # --- Factory method ---
    @classmethod
    def create(cls, config: SootheConfig, **kwargs) -> CoreAgent:
        """Factory method - delegates to create_soothe_agent()."""
        return create_soothe_agent(config, **kwargs)
```

### Factory Function Change

`create_soothe_agent()` returns `CoreAgent` instead of `CompiledStateGraph`:

```python
def create_soothe_agent(
    config: SootheConfig | None = None,
    *,
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    context: ContextProtocol | None = None,
    memory_store: MemoryProtocol | None = None,
    planner: PlannerProtocol | None = None,
    policy: PolicyProtocol | None = None,
) -> CoreAgent:  # Changed from CompiledStateGraph
    # ... existing assembly logic ...

    # REMOVED: goal_engine and goal_tools (Layer 3 responsibility)
    # goal_engine = resolve_goal_engine(config)
    # goal_tools = resolve_goal_tools(goal_engine)

    config_tools = resolve_tools(...)
    all_tools = [*config_tools]  # No goal_tools
    if tools:
        all_tools.extend(tools)

    graph = create_deep_agent(...)

    return CoreAgent(
        graph=graph,
        config=config,
        context=resolved_context,
        memory=resolved_memory,
        planner=resolved_planner,
        policy=resolved_policy,
        subagents=all_subagents,
    )
```

### Removed from Layer 1

The following are **NOT** part of CoreAgent (Layer 3 responsibility):

- `goal_engine: GoalEngine` - Goal lifecycle management
- `goal_tools: list[BaseTool]` - Goal management tools
- `soothe_goal_engine` attribute attachment

Layer 3 (`SootheRunner` or autonomous loop) resolves GoalEngine and goal_tools independently.

### Backward Compatibility

**Breaking changes for consumers:**

| Before | After |
|--------|-------|
| `agent.soothe_context` | `agent.context` |
| `agent.soothe_memory` | `agent.memory` |
| `agent.soothe_planner` | `agent.planner` |
| `agent.soothe_policy` | `agent.policy` |
| `agent.soothe_config` | `agent.config` |
| `agent.soothe_subagents` | `agent.subagents` |
| `agent.soothe_goal_engine` | **REMOVED** (Layer 3) |

**Execution unchanged:**
- `agent.astream(input, config)` - Still works (delegates to graph)
- `agent.graph.invoke(...)` - Access underlying graph for advanced operations

### Module Exports

```python
# src/soothe/core/__init__.py
__all__ = ["CoreAgent", "create_soothe_agent", "SootheRunner"]
```

## Three-Layer Separation

After this change, the layer boundaries are clean:

```
Layer 3: Autonomous Goal Management (RFC-200)
  └─ GoalEngine, goal_tools, SootheRunner orchestration

Layer 2: Agentic Goal Execution (RFC-201)
  └─ AgentLoop with ACT/VERIFY/DECIDE phases
  └─ Calls CoreAgent.astream() for ACT phase

Layer 1: CoreAgent Runtime (RFC-100) ← This design
  └─ CompiledStateGraph + typed protocols
  └─ Pure execution: tools, subagents, middlewares
  └─ NO goal infrastructure
```

## Implementation Files

| File | Change |
|------|--------|
| `src/soothe/core/agent.py` | Add CoreAgent class, update factory |
| `src/soothe/core/__init__.py` | Export CoreAgent |
| `src/soothe/cognition/agent_loop/executor.py` | Type hint: `CompiledStateGraph` → `CoreAgent` |
| `src/soothe/core/runner/__init__.py` | Type hint updates |
| `tests/unit/test_core_agent.py` | New test file |

## Success Criteria

- CoreAgent class with explicit typed interface
- Factory returns CoreAgent instance
- goal_engine and goal_tools removed from Layer 1
- All `soothe_*` attribute access replaced with properties
- All tests passing