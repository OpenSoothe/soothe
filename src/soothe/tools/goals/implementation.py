"""Goal management tools for autonomous agent self-drive (RFC-0007, RFC-0016).

Exposes GoalEngine operations as single-purpose tools following RFC-0016:
- create_goal: Create a new goal
- list_goals: List all goals and their statuses
- complete_goal: Mark a goal as successfully completed
- fail_goal: Mark a goal as failed with reason
"""

from __future__ import annotations

import asyncio
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.cognition import GoalEngine
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)

# Module-level shared thread pool for async-to-sync conversion
# This prevents creating new thread pools for each tool invocation
_shared_pool: ThreadPoolExecutor | None = None


def _get_shared_pool() -> ThreadPoolExecutor:
    """Get or create the shared thread pool."""
    global _shared_pool
    if _shared_pool is None:
        _shared_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="goals-async")
        atexit.register(_cleanup_pool)
    return _shared_pool


def _cleanup_pool() -> None:
    """Cleanup the shared thread pool on exit."""
    global _shared_pool
    if _shared_pool is not None:
        _shared_pool.shutdown(wait=True)
        _shared_pool = None


def _run_async(coro: Any) -> Any:
    """Run async coroutine from sync context."""
    loop = asyncio.get_event_loop()
    if loop.is_running():
        pool = _get_shared_pool()
        future = pool.submit(asyncio.run, coro)
        return future.result()
    return asyncio.run(coro)


class CreateGoalTool(BaseTool):
    """Create a new goal for autonomous operation.

    Use this tool to break complex tasks into sub-goals that will be
    executed sequentially. Each goal gets its own planning and iteration
    cycle.
    """

    name: str = "create_goal"
    description: str = (
        "Create a new goal. Parameters: description (required), parent_id (optional). Returns: goal ID and details."
    )
    goal_engine: GoalEngine = Field(exclude=True)

    def _run(self, description: str = "", priority: int = 50, parent_id: str = "") -> dict[str, Any]:
        """Create a new goal.

        Args:
            description: Goal description.
            priority: Priority (0-100, default 50).
            parent_id: Optional parent goal ID.

        Returns:
            Dict with created goal details.
        """
        if not description:
            return {"error": "description is required"}

        async def _create() -> dict[str, Any]:
            goal = await self.goal_engine.create_goal(description, priority=priority, parent_id=parent_id or None)

            return {"created": goal.model_dump(mode="json")}

        return _run_async(_create())

    async def _arun(self, description: str = "", priority: int = 50, parent_id: str = "") -> dict[str, Any]:
        """Async execution."""
        if not description:
            return {"error": "description is required"}

        goal = await self.goal_engine.create_goal(description, priority=priority, parent_id=parent_id or None)
        return {"created": goal.model_dump(mode="json")}


class ListGoalsTool(BaseTool):
    """List all goals and their statuses.

    Use this tool to see all goals, their current status (pending, active,
    completed, failed), and their descriptions.
    """

    name: str = "list_goals"
    description: str = (
        "List all goals. "
        "Optional: status filter (pending, active, completed, failed). "
        "Returns: goal list with IDs, descriptions, statuses."
    )
    goal_engine: GoalEngine = Field(exclude=True)

    def _run(self, status: str = "") -> dict[str, Any]:
        """List goals.

        Args:
            status: Optional status filter (pending, active, completed, failed).

        Returns:
            Dict with list of goals.
        """

        async def _list() -> dict[str, Any]:
            filter_status = status if status in ("pending", "active", "completed", "failed") else None
            goals = await self.goal_engine.list_goals(filter_status)

            return {"goals": [g.model_dump(mode="json") for g in goals]}

        return _run_async(_list())

    async def _arun(self, status: str = "") -> dict[str, Any]:
        """Async execution."""
        filter_status = status if status in ("pending", "active", "completed", "failed") else None
        goals = await self.goal_engine.list_goals(filter_status)
        return {"goals": [g.model_dump(mode="json") for g in goals]}


class CompleteGoalTool(BaseTool):
    """Mark a goal as successfully completed.

    Use this tool when you have finished working on a goal and achieved
    the desired outcome.
    """

    name: str = "complete_goal"
    description: str = "Mark goal as complete. Parameters: goal_id (required). Returns: confirmation with goal details."
    goal_engine: GoalEngine = Field(exclude=True)

    def _run(self, goal_id: str = "") -> dict[str, Any]:
        """Complete a goal.

        Args:
            goal_id: Goal ID to complete.

        Returns:
            Dict with completed goal details.
        """
        if not goal_id:
            return {"error": "goal_id is required"}

        async def _complete() -> dict[str, Any]:
            try:
                goal = await self.goal_engine.complete_goal(goal_id)

                return {"completed": goal.model_dump(mode="json")}
            except KeyError:
                return {"error": f"Goal {goal_id} not found"}

        return _run_async(_complete())

    async def _arun(self, goal_id: str = "") -> dict[str, Any]:
        """Async execution."""
        if not goal_id:
            return {"error": "goal_id is required"}

        try:
            goal = await self.goal_engine.complete_goal(goal_id)
            return {"completed": goal.model_dump(mode="json")}
        except KeyError:
            return {"error": f"Goal {goal_id} not found"}


class FailGoalTool(BaseTool):
    """Mark a goal as failed with reason.

    Use this tool when you cannot complete a goal due to errors or
    blockers. Provide a clear reason for the failure.
    """

    name: str = "fail_goal"
    description: str = (
        "Mark goal as failed. "
        "Parameters: goal_id (required), reason (required). "
        "Returns: confirmation with goal details."
    )
    goal_engine: GoalEngine = Field(exclude=True)

    def _run(self, goal_id: str = "", reason: str = "") -> dict[str, Any]:
        """Fail a goal.

        Args:
            goal_id: Goal ID to fail.
            reason: Reason for failure.

        Returns:
            Dict with failed goal details.
        """
        if not goal_id:
            return {"error": "goal_id is required"}
        if not reason:
            return {"error": "reason is required"}

        async def _fail() -> dict[str, Any]:
            try:
                goal = await self.goal_engine.fail_goal(goal_id, error=reason)

                return {"failed": goal.model_dump(mode="json")}
            except KeyError:
                return {"error": f"Goal {goal_id} not found"}

        return _run_async(_fail())

    async def _arun(self, goal_id: str = "", reason: str = "") -> dict[str, Any]:
        """Async execution."""
        if not goal_id:
            return {"error": "goal_id is required"}
        if not reason:
            return {"error": "reason is required"}

        try:
            goal = await self.goal_engine.fail_goal(goal_id, error=reason)
            return {"failed": goal.model_dump(mode="json")}
        except KeyError:
            return {"error": f"Goal {goal_id} not found"}


def create_goals_tools(goal_engine: GoalEngine) -> list[BaseTool]:
    """Create goal management tools bound to a GoalEngine instance.

    Args:
        goal_engine: The GoalEngine to bind.

    Returns:
        List containing CreateGoalTool, ListGoalsTool, CompleteGoalTool, FailGoalTool.
    """
    return [
        CreateGoalTool(goal_engine=goal_engine),
        ListGoalsTool(goal_engine=goal_engine),
        CompleteGoalTool(goal_engine=goal_engine),
        FailGoalTool(goal_engine=goal_engine),
    ]


# =====================================================================
# RFC-204: Layer 2 ↔ Layer 3 Query & Proposal Tools
# =====================================================================


class GetRelatedGoalsTool(BaseTool):
    """RFC-204: Query goals that might inform the current goal."""

    name: str = "get_related_goals"
    description: str = (
        "Find goals related to the current work. "
        "Parameters: query (goal description or topic). "
        "Returns: related goals with status and description."
    )
    goal_engine: GoalEngine = Field(exclude=True)

    def _run(self, query: str = "") -> dict[str, Any]:
        if not query:
            return {"error": "query is required"}
        return _run_async(self._arun(query=query))

    async def _arun(self, query: str = "") -> dict[str, Any]:
        if not query:
            return {"error": "query is required"}
        goals = await self.goal_engine.list_goals()
        query_lower = query.lower()
        related = [
            g
            for g in goals
            if g.status in ("active", "completed", "validated")
            and any(w in g.description.lower() for w in query_lower.split())
        ]
        return {
            "related_goals": [{"id": g.id, "description": g.description, "status": g.status} for g in related[:10]],
        }


class GetGoalProgressTool(BaseTool):
    """RFC-204: Query progress of a specific goal."""

    name: str = "get_goal_progress"
    description: str = (
        "Get the status and progress of a specific goal. "
        "Parameters: goal_id (required). "
        "Returns: goal status, description, and details."
    )
    goal_engine: GoalEngine = Field(exclude=True)

    def _run(self, goal_id: str = "") -> dict[str, Any]:
        if not goal_id:
            return {"error": "goal_id is required"}
        return _run_async(self._arun(goal_id=goal_id))

    async def _arun(self, goal_id: str = "") -> dict[str, Any]:
        if not goal_id:
            return {"error": "goal_id is required"}
        goal = await self.goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}
        return {
            "goal_id": goal.id,
            "description": goal.description,
            "status": goal.status,
            "priority": goal.priority,
        }


class ReportProgressTool(BaseTool):
    """RFC-204: Propose a progress update for the current goal."""

    name: str = "report_progress"
    description: str = (
        "Report progress on the current goal. Parameters: goal_id (required), status, findings. Returns: confirmation."
    )
    goal_engine: GoalEngine = Field(exclude=True)
    proposal_queue: Any = Field(default=None, exclude=True)

    def _run(self, goal_id: str = "", status: str = "", findings: str = "") -> dict[str, Any]:
        if not goal_id:
            return {"error": "goal_id is required"}
        return _run_async(self._arun(goal_id=goal_id, status=status, findings=findings))

    async def _arun(self, goal_id: str = "", status: str = "", findings: str = "") -> dict[str, Any]:
        if not goal_id:
            return {"error": "goal_id is required"}
        goal = await self.goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}
        logger.info("Goal %s progress reported: status=%s, findings=%s", goal_id, status, preview_first(findings, 100))
        if self.proposal_queue:
            from soothe.cognition.goal_engine.proposal_queue import Proposal

            self.proposal_queue.enqueue(
                Proposal(
                    type="report_progress",
                    goal_id=goal_id,
                    payload={"status": status, "findings": findings},
                )
            )
        return {"status": "queued", "goal_id": goal_id}


class SuggestGoalTool(BaseTool):
    """RFC-204: Propose a new goal to Layer 3."""

    name: str = "suggest_goal"
    description: str = (
        "Propose a new goal to the autopilot manager. "
        "Parameters: description (required), priority (optional). "
        "Returns: proposal confirmation (subject to review)."
    )
    goal_engine: GoalEngine = Field(exclude=True)
    proposal_queue: Any = Field(default=None, exclude=True)

    def _run(self, description: str = "", priority: int = 50) -> dict[str, Any]:
        if not description:
            return {"error": "description is required"}
        return _run_async(self._arun(description=description, priority=priority))

    async def _arun(self, description: str = "", priority: int = 50) -> dict[str, Any]:
        if not description:
            return {"error": "description is required"}
        logger.info("Goal proposed: %s (priority=%d)", description, priority)
        if self.proposal_queue:
            from soothe.cognition.goal_engine.proposal_queue import Proposal

            self.proposal_queue.enqueue(
                Proposal(
                    type="suggest_goal",
                    goal_id="",
                    payload={"description": description, "priority": priority},
                )
            )
        return {"status": "proposed", "description": description, "priority": priority}


class FlagBlockerTool(BaseTool):
    """RFC-204: Signal that the current goal is blocked."""

    name: str = "flag_blocker"
    description: str = (
        "Signal that the current goal is blocked and needs intervention. "
        "Parameters: goal_id (required), reason (required). "
        "Returns: confirmation."
    )
    goal_engine: GoalEngine = Field(exclude=True)
    proposal_queue: Any = Field(default=None, exclude=True)

    def _run(self, goal_id: str = "", reason: str = "", dependencies: str = "") -> dict[str, Any]:
        if not goal_id:
            return {"error": "goal_id is required"}
        if not reason:
            return {"error": "reason is required"}
        return _run_async(self._arun(goal_id=goal_id, reason=reason, dependencies=dependencies))

    async def _arun(self, goal_id: str = "", reason: str = "", dependencies: str = "") -> dict[str, Any]:
        if not goal_id:
            return {"error": "goal_id is required"}
        if not reason:
            return {"error": "reason is required"}
        goal = await self.goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}
        blocker_deps = f" (depends on: {dependencies})" if dependencies else ""
        logger.warning("Goal %s blocked: %s%s", goal_id, reason, blocker_deps)
        if self.proposal_queue:
            from soothe.cognition.goal_engine.proposal_queue import Proposal

            self.proposal_queue.enqueue(
                Proposal(
                    type="flag_blocker",
                    goal_id=goal_id,
                    payload={"reason": reason, "dependencies": dependencies},
                )
            )
        return {"status": "flagged", "goal_id": goal_id, "reason": reason}


class GetWorldInfoTool(BaseTool):
    """RFC-204: Get current workspace and execution state."""

    name: str = "get_world_info"
    description: str = (
        "Get the current workspace and execution state. "
        "Parameters: none. "
        "Returns: current goal ID, iteration count, workspace path, active goals count."
    )
    goal_engine: GoalEngine = Field(exclude=True)
    iteration_count: int = Field(default=0, exclude=True)
    workspace: str = Field(default="", exclude=True)
    available_subagents: list[str] = Field(default_factory=list, exclude=True)

    def _run(self) -> dict[str, Any]:
        return _run_async(self._arun())

    async def _arun(self) -> dict[str, Any]:
        goals = await self.goal_engine.list_goals()
        active = [g for g in goals if g.status == "active"]
        return {
            "active_goals": len(active),
            "total_goals": len(goals),
            "iteration_count": self.iteration_count,
            "workspace": self.workspace,
            "available_subagents": self.available_subagents,
        }


class SearchMemoryTool(BaseTool):
    """RFC-204: Search cross-thread memory for relevant content."""

    name: str = "search_memory"
    description: str = (
        "Search long-term memory for content related to the query. "
        "Parameters: query (required), limit (optional, default 5). "
        "Returns: matching memory items."
    )
    memory_protocol: Any = Field(exclude=True)

    def _run(self, query: str = "", limit: int = 5) -> dict[str, Any]:
        if not query:
            return {"error": "query is required"}
        return _run_async(self._arun(query=query, limit=limit))

    async def _arun(self, query: str = "", limit: int = 5) -> dict[str, Any]:
        if not query:
            return {"error": "query is required"}
        try:
            items = await self.memory_protocol.recall(query, limit=limit)
            return {"results": items if isinstance(items, list) else [items]}
        except Exception as exc:
            return {"error": f"Memory search failed: {exc}"}


class AddFindingTool(BaseTool):
    """RFC-204: Add a finding to the current goal's context ledger."""

    name: str = "add_finding"
    description: str = (
        "Record a significant finding for the current goal. "
        "Parameters: goal_id (required), content (required), tags (optional). "
        "Returns: confirmation."
    )
    goal_engine: GoalEngine = Field(exclude=True)
    proposal_queue: Any = Field(default=None, exclude=True)

    def _run(self, goal_id: str = "", content: str = "", tags: str = "") -> dict[str, Any]:
        if not goal_id:
            return {"error": "goal_id is required"}
        if not content:
            return {"error": "content is required"}
        return _run_async(self._arun(goal_id=goal_id, content=content, tags=tags))

    async def _arun(self, goal_id: str = "", content: str = "", tags: str = "") -> dict[str, Any]:
        if not goal_id:
            return {"error": "goal_id is required"}
        if not content:
            return {"error": "content is required"}
        goal = await self.goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}
        # Queue the finding for post-iteration application
        if self.proposal_queue:
            from soothe.cognition.goal_engine.proposal_queue import Proposal

            self.proposal_queue.enqueue(
                Proposal(
                    type="add_finding",
                    goal_id=goal_id,
                    payload={"content": content, "tags": tags.split(",") if tags else []},
                )
            )
        return {"status": "queued", "goal_id": goal_id, "content_preview": preview_first(content, 100)}


def create_layer2_tools(
    goal_engine: GoalEngine,
    *,
    proposal_queue: Any = None,
    memory_protocol: Any = None,
    iteration_count: int = 0,
    workspace: str = "",
    available_subagents: list[str] | None = None,
) -> list[BaseTool]:
    """Create Layer 2 <-> Layer 3 communication tools (RFC-204).

    Args:
        goal_engine: The GoalEngine to bind.
        proposal_queue: Optional ProposalQueue for queuing semantics.
        memory_protocol: Optional memory protocol for search.
        iteration_count: Current iteration count.
        workspace: Workspace path.
        available_subagents: List of available subagent names.

    Returns:
        List of query and proposal tool instances.
    """
    tools = [
        GetRelatedGoalsTool(goal_engine=goal_engine),
        GetGoalProgressTool(goal_engine=goal_engine),
        ReportProgressTool(goal_engine=goal_engine, proposal_queue=proposal_queue),
        SuggestGoalTool(goal_engine=goal_engine, proposal_queue=proposal_queue),
        FlagBlockerTool(goal_engine=goal_engine, proposal_queue=proposal_queue),
        GetWorldInfoTool(
            goal_engine=goal_engine,
            iteration_count=iteration_count,
            workspace=workspace,
            available_subagents=available_subagents or [],
        ),
    ]
    if memory_protocol:
        tools.append(SearchMemoryTool(memory_protocol=memory_protocol))
    tools.append(AddFindingTool(goal_engine=goal_engine, proposal_queue=proposal_queue))
    return tools
