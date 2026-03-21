"""Goal management tools for autonomous agent self-drive (RFC-0007, RFC-0016).

Exposes GoalEngine operations as single-purpose tools following RFC-0016:
- create_goal: Create a new goal
- list_goals: List all goals and their statuses
- complete_goal: Mark a goal as successfully completed
- fail_goal: Mark a goal as failed with reason
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.cognition import GoalEngine


def _run_async(coro):
    """Run async coroutine from sync context."""
    loop = asyncio.get_event_loop()
    if loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
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

        async def _create():
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

        async def _list():
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

        async def _complete():
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

        async def _fail():
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
