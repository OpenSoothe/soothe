# IG-100: CoreAgent Self-Contained Module with Clear Interface

**Implementation Guide**: IG-100
**RFC**: RFC-100 (Layer 1 CoreAgent Runtime Architecture)
**Status**: Approved
**Created**: 2026-03-29
**Design Draft**: [2026-03-29-coreagent-layer1-interface-design.md](../drafts/2026-03-29-coreagent-layer1-interface-design.md)

## Overview

Implement CoreAgent as a self-contained Layer 1 module per RFC-100. The current factory returns a raw `CompiledStateGraph` with ad-hoc `soothe_*` attributes. This guide formalizes a proper CoreAgent class with explicit typed properties and removes goal infrastructure (Layer 3 responsibility).

## Design Summary

**CoreAgent class** wraps `CompiledStateGraph` with:
- Explicit typed properties: `graph`, `config`, `context`, `memory`, `planner`, `policy`, `subagents`
- Execution interface: `astream(input, config)` delegating to graph
- **NO goal infrastructure** (removed from Layer 1)

**Factory change**: `create_soothe_agent()` returns `CoreAgent` instead of `CompiledStateGraph`

## Implementation Tasks

### Task 1: Create CoreAgent Class

Add `CoreAgent` class to `src/soothe/core/agent.py`:

```python
class CoreAgent:
    """Layer 1 CoreAgent runtime (RFC-100)."""

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

    @property
    def graph(self) -> CompiledStateGraph: ...
    @property
    def config(self) -> SootheConfig: ...
    @property
    def context(self) -> ContextProtocol | None: ...
    @property
    def memory(self) -> MemoryProtocol | None: ...
    @property
    def planner(self) -> PlannerProtocol | None: ...
    @property
    def policy(self) -> PolicyProtocol | None: ...
    @property
    def subagents(self) -> list[SubAgent | CompiledSubAgent]: ...

    async def astream(self, input, config) -> AsyncIterator[StreamChunk]:
        return self._graph.astream(input, config or {})

    @classmethod
    def create(cls, config: SootheConfig, **kwargs) -> CoreAgent: ...
```

### Task 2: Update Factory Function

Modify `create_soothe_agent()`:

1. Remove `goal_engine = resolve_goal_engine(config)`
2. Remove `goal_tools = resolve_goal_tools(goal_engine)`
3. Remove `goal_tools` from `all_tools` list
4. Remove `agent.soothe_goal_engine = goal_engine` attachment
5. Return `CoreAgent(...)` instead of raw graph
6. Remove `soothe_*` attribute attachments (use CoreAgent properties)

### Task 3: Update Module Exports

```python
# src/soothe/core/__init__.py
__all__ = ["CoreAgent", "create_soothe_agent", "SootheRunner"]
```

### Task 4: Update Consumer Type Hints

Update files that reference `CompiledStateGraph` for CoreAgent:

- `src/soothe/cognition/agent_loop/executor.py`: `core_agent: CompiledStateGraph` → `core_agent: CoreAgent`
- `src/soothe/core/runner/__init__.py`: Update type hints
- Other consumers using `agent.soothe_*` → use `agent.context`, `agent.memory`, etc.

### Task 5: Write Unit Tests

Create `tests/unit/test_core_agent.py`:

- Test CoreAgent instantiation with protocols
- Test property access returns correct values
- Test `astream()` delegates to graph
- Test factory returns CoreAgent instance
- Test missing protocols return None

## Files Modified

| File | Change |
|------|--------|
| `src/soothe/core/agent.py` | Add CoreAgent class, update factory |
| `src/soothe/core/__init__.py` | Export CoreAgent |
| `src/soothe/cognition/agent_loop/executor.py` | Type hint update |
| `src/soothe/core/runner/__init__.py` | Type hint update |
| `tests/unit/test_core_agent.py` | New test file |

## Breaking Changes

| Before | After |
|--------|-------|
| `agent.soothe_context` | `agent.context` |
| `agent.soothe_memory` | `agent.memory` |
| `agent.soothe_planner` | `agent.planner` |
| `agent.soothe_policy` | `agent.policy` |
| `agent.soothe_config` | `agent.config` |
| `agent.soothe_subagents` | `agent.subagents` |
| `agent.soothe_goal_engine` | **REMOVED** |

## Success Criteria

- [ ] CoreAgent class defined with all properties
- [ ] Factory returns CoreAgent instance
- [ ] goal_engine/goal_tools removed from Layer 1
- [ ] Module exports updated
- [ ] Consumer type hints updated
- [ ] Unit tests passing
- [ ] Full verification: `./scripts/verify_finally.sh`