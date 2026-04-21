# AgentLoop Communication Utilities Architectural Correction

> Implementation guide for converting goal "tools" to AgentLoop internal utilities.
>
> **Crate/Module**: `packages/soothe/src/soothe/cognition/agent_loop/`
> **Source**: RFC-204 (Layer 2 ↔ Layer 3 Communication), RFC-200 (Goal Pull Architecture)
> **Related RFCs**: RFC-001, RFC-201
> **Language**: Python 3.11+

---

## 1. Overview

### 1.1 Critical Architectural Discovery

**Current Design Violations**:
- Goal communication utilities inherit `BaseTool` (Layer 1 abstraction)
- They're located in `tools/goals/` (Layer 1 tool infrastructure)
- GoalsPlugin returns empty list (designed for runtime binding, but never bound)
- `create_agent_loop_tools()` defined but **never called** in production

**Root Cause Analysis**:
These utilities were incorrectly classified as "tools" because RFC-204 §1.2 uses the word "tools":

> "Layer 2 can query and propose updates through **tools**"

But RFC-204 meant **communication utilities**, not **BaseTool implementations** for CoreAgent invocation.

### 1.2 Architectural Correct Classification

| Layer | Component Type | Purpose | Abstraction |
|-------|---------------|---------|-------------|
| Layer 1 | CoreAgent Tools | Execute steps | `BaseTool` (langchain) |
| Layer 2 | AgentLoop Utilities | Plan/Reason helpers | Internal classes |
| Layer 2 ↔ Layer 3 | Communication Utilities | Query/Propose | Internal helper classes |
| Layer 3 | GoalEngine Service | Goal state provider | Service API methods |

**Goal Communication Utilities** are:
- **NOT** Layer 1 execution tools (never invoked by CoreAgent)
- **NOT** BaseTool implementations (wrong abstraction)
- **ARE** AgentLoop internal helpers for Layer 2 ↔ Layer 3 communication
- **ARE** used directly by AgentLoop (not through tool registry)

---

## 2. Architectural Violation Evidence

### 2.1 Never Used as BaseTools

**Evidence**:

```bash
# No production usage
$ grep -r "create_agent_loop_tools" packages/soothe/src/soothe --include="*.py"
packages/soothe/src/soothe/tools/goals/__init__.py  # Export only
packages/soothe/src/soothe/tools/goals/implementation.py  # Definition only
# NEVER called in production code!

# GoalsPlugin returns empty list
class GoalsPlugin:
    def get_tools(self) -> list[Any]:
        return self._tools  # Empty!

# No BaseTool usage in cognition layer
$ grep -r "BaseTool" packages/soothe/src/soothe/cognition
# (empty result - cognition layer doesn't use BaseTool)
```

**Analysis**:
- `create_agent_loop_tools()` defined but never called
- GoalsPlugin designed for "runtime binding" but binding never happens
- Cognition layer has no other BaseTool usage (correct separation)

### 2.2 Wrong Abstraction

**BaseTool Design**:
```python
class GetRelatedGoalsTool(BaseTool):
    name: str = "get_related_goals"
    description: str = "..."

    def _run(self, query: str):
        # Sync wrapper for async method
        return _run_async(self._arun(query=query))

    async def _arun(self, query: str):
        # Actual implementation
        goals = await self.goal_engine.list_goals()
        ...
```

**Problem**: `_run()` and `_arun()` are BaseTool methods designed for CoreAgent invocation via `.invoke()` or `.astream()`. But these utilities are never invoked that way.

**Actual Usage Pattern** (tests only):
```python
tool = GetRelatedGoalsTool(goal_engine=engine)
result = await tool._arun(query="Fix database")
# Direct method call, NOT tool.invoke() or tool.astream()
```

They're used as **regular async helper methods**, not as LangChain tools.

---

## 3. Correct Architecture Design

### 3.1 Module Structure

**Move from**:
```
packages/soothe/src/soothe/tools/goals/
├── implementation.py  # BaseTool classes (WRONG)
└── __init__.py        # GoalsPlugin (WRONG)
```

**Move to**:
```
packages/soothe/src/soothe/cognition/agent_loop/
├── communication.py   # NEW: Goal communication utilities
│   ├── GoalCommunicationHelper class
│   ├── get_related_goals() method
│   ├── get_goal_progress() method
│   ├── report_progress() method
│   ├── suggest_goal() method
│   ├── flag_blocker() method
│   ├── get_world_info() method
│   ├── search_memory() method
│   └── add_finding() method
│
└── agent_loop.py      # Uses communication.py helpers
```

### 3.2 Class Design

**Before (WRONG)**:
```python
class GetRelatedGoalsTool(BaseTool):
    """RFC-204: Query goals that might inform the current goal."""

    name: str = "get_related_goals"
    description: str = "Find goals related to current work..."
    goal_engine: GoalEngine = Field(exclude=True)

    def _run(self, query: str = "") -> dict[str, Any]:
        if not query:
            return {"error": "query is required"}
        return _run_async(self._arun(query=query))

    async def _arun(self, query: str = "") -> dict[str, Any]:
        goals = await self.goal_engine.list_goals()
        related = [g for g in goals if query.lower() in g.description.lower()]
        return {"related_goals": [{"id": g.id, "description": g.description} for g in related]}
```

**After (CORRECT)**:
```python
class GoalCommunicationHelper:
    """Helper for Layer 2 ↔ Layer 3 goal communication (RFC-204)."""

    def __init__(self, goal_engine: GoalEngine) -> None:
        self._goal_engine = goal_engine

    async def get_related_goals(self, query: str) -> dict[str, Any]:
        """Get goals related to query.

        Args:
            query: Search query string.

        Returns:
            Dict with related_goals list.
        """
        if not query:
            return {"error": "query is required"}

        goals = await self._goal_engine.list_goals()
        query_lower = query.lower()
        related = [
            g for g in goals
            if g.status in ("active", "completed", "validated")
            and any(w in g.description.lower() for w in query_lower.split())
        ]

        return {
            "related_goals": [
                {"id": g.id, "description": g.description, "status": g.status}
                for g in related[:10]
            ],
        }
```

**Key Differences**:
1. No `BaseTool` inheritance (not a Layer 1 tool)
2. No `_run()` / `_arun()` BaseTool methods
3. Direct async methods (cleaner API)
4. Instantiated by AgentLoop, not by plugin system
5. No async-to-sync conversion needed (AgentLoop is async)

### 3.3 Usage in AgentLoop

**Before (conceptual, never implemented)**:
```python
# This was the intended design, but never actually implemented
tools = create_agent_loop_tools(goal_engine, ...)
# Pass to CoreAgent somehow? (never defined)
```

**After (correct)**:
```python
# agent_loop.py
from .communication import GoalCommunicationHelper

class AgentLoop:
    def __init__(self, core_agent, loop_planner, config):
        # ... existing initialization ...

        # Create communication helper (NEW)
        if goal_engine:
            self._communication = GoalCommunicationHelper(goal_engine)
        else:
            self._communication = None

    async def run_with_progress(self, goal, thread_id, ...):
        # Use communication helper during Plan phase
        if self._communication:
            related = await self._communication.get_related_goals(goal)
            # Inject related goals into Plan context
            ...
```

---

## 4. Implementation Plan

### 4.1 Phase 1: Create New Module

**File**: `packages/soothe/src/soothe/cognition/agent_loop/communication.py`

```python
"""Goal communication utilities for Layer 2 ↔ Layer 3 (RFC-204).

These are AgentLoop internal helpers, NOT CoreAgent execution tools.
Used directly by AgentLoop for querying Layer 3 GoalEngine.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.cognition.goal_engine.proposal_queue import Proposal
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


class GoalCommunicationHelper:
    """Helper for Layer 2 ↔ Layer 3 goal communication (RFC-204).

    Provides query and proposal methods for AgentLoop to communicate
    with GoalEngine (Layer 3). NOT a BaseTool - internal utility class.

    Args:
        goal_engine: GoalEngine instance for goal queries.
        proposal_queue: Optional ProposalQueue for queuing proposals.
        memory_protocol: Optional MemoryProtocol for memory search.
        iteration_count: Current iteration count for world info.
        workspace: Workspace path for world info.
        available_subagents: Available subagent names for world info.
    """

    def __init__(
        self,
        goal_engine: Any,  # GoalEngine type hint avoided for circular dependency
        proposal_queue: Any = None,
        memory_protocol: Any = None,
        iteration_count: int = 0,
        workspace: str = "",
        available_subagents: list[str] | None = None,
    ) -> None:
        self._goal_engine = goal_engine
        self._proposal_queue = proposal_queue
        self._memory_protocol = memory_protocol
        self._iteration_count = iteration_count
        self._workspace = workspace
        self._available_subagents = available_subagents or []

    # Query operations (RFC-204 §64-69)

    async def get_related_goals(self, query: str) -> dict[str, Any]:
        """Get goals related to current work.

        Args:
            query: Search query.

        Returns:
            Dict with related_goals list (id, description, status).
        """
        if not query:
            return {"error": "query is required"}

        goals = await self._goal_engine.list_goals()
        query_lower = query.lower()
        related = [
            g for g in goals
            if g.status in ("active", "completed", "validated")
            and any(w in g.description.lower() for w in query_lower.split())
        ]

        return {
            "related_goals": [
                {"id": g.id, "description": g.description, "status": g.status}
                for g in related[:10]
            ],
        }

    async def get_goal_progress(self, goal_id: str) -> dict[str, Any]:
        """Get status and progress of a specific goal.

        Args:
            goal_id: Goal ID to query.

        Returns:
            Dict with goal_id, description, status, priority.
        """
        if not goal_id:
            return {"error": "goal_id is required"}

        goal = await self._goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}

        return {
            "goal_id": goal.id,
            "description": goal.description,
            "status": goal.status,
            "priority": goal.priority,
        }

    async def get_world_info(self) -> dict[str, Any]:
        """Get current workspace and execution state.

        Returns:
            Dict with active_goals, total_goals, iteration_count, workspace.
        """
        goals = await self._goal_engine.list_goals()
        active = [g for g in goals if g.status == "active"]

        return {
            "active_goals": len(active),
            "total_goals": len(goals),
            "iteration_count": self._iteration_count,
            "workspace": self._workspace,
            "available_subagents": self._available_subagents,
        }

    async def search_memory(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Search cross-thread memory for relevant content.

        Args:
            query: Search query.
            limit: Max results (default 5).

        Returns:
            Dict with results list.
        """
        if not query:
            return {"error": "query is required"}

        if not self._memory_protocol:
            return {"error": "Memory protocol not available"}

        try:
            items = await self._memory_protocol.recall(query, limit=limit)
            return {"results": items if isinstance(items, list) else [items]}
        except Exception as exc:
            return {"error": f"Memory search failed: {exc}"}

    # Proposal operations (RFC-204 §71-76)

    async def report_progress(
        self, goal_id: str, status: str = "", findings: str = ""
    ) -> dict[str, Any]:
        """Report progress on current goal.

        Args:
            goal_id: Goal ID.
            status: Status update.
            findings: Findings text.

        Returns:
            Dict with status="queued" and goal_id.
        """
        if not goal_id:
            return {"error": "goal_id is required"}

        goal = await self._goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}

        logger.info(
            "Goal %s progress reported: status=%s, findings=%s",
            goal_id,
            status,
            preview_first(findings, 100),
        )

        if self._proposal_queue:
            self._proposal_queue.enqueue(
                Proposal(
                    type="report_progress",
                    goal_id=goal_id,
                    payload={"status": status, "findings": findings},
                )
            )

        return {"status": "queued", "goal_id": goal_id}

    async def suggest_goal(self, description: str, priority: int = 50) -> dict[str, Any]:
        """Propose a new goal to Layer 3.

        Args:
            description: Goal description.
            priority: Priority (0-100, default 50).

        Returns:
            Dict with status="proposed", description, priority.
        """
        if not description:
            return {"error": "description is required"}

        logger.info("Goal proposed: %s (priority=%d)", description, priority)

        if self._proposal_queue:
            self._proposal_queue.enqueue(
                Proposal(
                    type="suggest_goal",
                    goal_id="",
                    payload={"description": description, "priority": priority},
                )
            )

        return {"status": "proposed", "description": description, "priority": priority}

    async def flag_blocker(
        self, goal_id: str, reason: str, dependencies: str = ""
    ) -> dict[str, Any]:
        """Signal that current goal is blocked.

        Args:
            goal_id: Goal ID.
            reason: Blocker reason.
            dependencies: Dependency description.

        Returns:
            Dict with status="flagged", goal_id, reason.
        """
        if not goal_id:
            return {"error": "goal_id is required"}
        if not reason:
            return {"error": "reason is required"}

        goal = await self._goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}

        blocker_deps = f" (depends on: {dependencies})" if dependencies else ""
        logger.warning("Goal %s blocked: %s%s", goal_id, reason, blocker_deps)

        if self._proposal_queue:
            self._proposal_queue.enqueue(
                Proposal(
                    type="flag_blocker",
                    goal_id=goal_id,
                    payload={"reason": reason, "dependencies": dependencies},
                )
            )

        return {"status": "flagged", "goal_id": goal_id, "reason": reason}

    async def add_finding(self, goal_id: str, content: str, tags: str = "") -> dict[str, Any]:
        """Add finding to current goal's context ledger.

        Args:
            goal_id: Goal ID.
            content: Finding content.
            tags: Comma-separated tags.

        Returns:
            Dict with status="queued", goal_id, content_preview.
        """
        if not goal_id:
            return {"error": "goal_id is required"}
        if not content:
            return {"error": "content is required"}

        goal = await self._goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}

        if self._proposal_queue:
            self._proposal_queue.enqueue(
                Proposal(
                    type="add_finding",
                    goal_id=goal_id,
                    payload={"content": content, "tags": tags.split(",") if tags else []},
                )
            )

        return {
            "status": "queued",
            "goal_id": goal_id,
            "content_preview": preview_first(content, 100),
        }
```

### 4.2 Phase 2: Update AgentLoop

**File**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

```python
# Add import
from .communication import GoalCommunicationHelper

class AgentLoop:
    def __init__(
        self,
        core_agent: CoreAgent,
        loop_planner: LoopPlannerProtocol,
        config: SootheConfig,
        goal_engine: GoalEngine | None = None,  # NEW parameter
    ) -> None:
        # ... existing initialization ...

        # NEW: Create communication helper
        if goal_engine:
            self._communication = GoalCommunicationHelper(goal_engine)
        else:
            self._communication = None

    async def run_with_progress(self, goal, thread_id, ...):
        # NEW: Use communication helper for context enrichment
        if self._communication:
            world_info = await self._communication.get_world_info()
            # Inject world_info into Plan phase context
            ...
```

### 4.3 Phase 3: Remove Old Implementation

**Delete**:
- `packages/soothe/src/soothe/tools/goals/implementation.py` (entire file)
- `packages/soothe/src/soothe/tools/goals/__init__.py` (GoalsPlugin)
- `packages/soothe/tests/unit/tools/goals/test_goal_communication_tools.py` (tests)

**Update exports**:
- Remove from `tools/__init__.py`
- Remove from plugin registry

---

## 5. Verification Checklist

After implementation:

1. ✅ Communication utilities moved to `cognition/agent_loop/communication.py`
2. ✅ No BaseTool inheritance (internal helper classes)
3. ✅ No `_run()` / `_arun()` BaseTool methods (direct async methods)
4. ✅ Used by AgentLoop directly (not through tool registry)
5. ✅ No GoalsPlugin (not a plugin anymore)
6. ✅ Old `tools/goals/` directory removed
7. ✅ Tests updated to test helper methods directly
8. ✅ All imports updated
9. ✅ Verification script passes

---

## Appendix A: Architectural Principle Mapping

| Principle | Before (Wrong) | After (Correct) |
|-----------|---------------|------------------|
| Layer separation | BaseTool in cognition layer | Internal helper in agent_loop |
| Abstraction matching | BaseTool (Layer 1) for Layer 2 | AgentLoop utility (Layer 2) |
| Inheritance | BaseTool inheritance | No inheritance (plain class) |
| Invocation pattern | tool.invoke() / tool.astream() | helper.method() (direct call) |
| Plugin system | GoalsPlugin (tool group) | No plugin (internal utility) |

---

## Appendix B: Why This Matters

**Before**: Confusion between "execution tools" (CoreAgent Layer 1) and "communication utilities" (AgentLoop Layer 2).

**After**: Clear separation:
- Layer 1: `BaseTool` for execution (file_ops, web_search, etc.)
- Layer 2: AgentLoop utilities for planning/reasoning/communication
- Layer 3: GoalEngine service APIs for goal management

This eliminates architectural confusion and correctly implements RFC-204's Layer 2 ↔ Layer 3 communication pattern.

---

**Next Steps**: Implement in single phase after approval.