"""Goal management tool for autonomous agent self-drive (RFC-0007).

Exposes GoalEngine operations as a langchain BaseTool so the agent can
create, list, and complete goals during execution.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.core.goal_engine import GoalEngine


class ManageGoalsTool(BaseTool):
    """Create, list, or complete goals for autonomous multi-phase work.

    Use this tool to break complex tasks into sub-goals that will be
    executed sequentially. Each goal gets its own planning and iteration
    cycle.

    Actions:
        - create: Create a new goal with description and optional priority (0-100).
        - list: List all goals and their statuses.
        - complete: Mark a goal as completed by goal_id.
        - fail: Mark a goal as failed by goal_id.
    """

    name: str = "manage_goals"
    description: str = (
        "Manage autonomous goals. Actions: "
        "'create' (description, priority 0-100), "
        "'list' (optional status filter), "
        "'complete' (goal_id), "
        "'fail' (goal_id, error). "
        "Use to break complex tasks into sequential sub-goals."
    )
    goal_engine: GoalEngine = Field(exclude=True)

    def _run(
        self,
        action: str = "list",
        description: str = "",
        priority: int = 50,
        goal_id: str = "",
        status: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._arun(action, description, priority, goal_id, status, error))
                return future.result()
        return asyncio.run(self._arun(action, description, priority, goal_id, status, error))

    async def _arun(
        self,
        action: str = "list",
        description: str = "",
        priority: int = 50,
        goal_id: str = "",
        status: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        if action == "create":
            if not description:
                return {"error": "description is required for create action"}
            goal = await self.goal_engine.create_goal(description, priority=priority)
            return {"created": goal.model_dump(mode="json")}

        if action == "list":
            filter_status = status if status in ("pending", "active", "completed", "failed") else None
            goals = await self.goal_engine.list_goals(filter_status)
            return {"goals": [g.model_dump(mode="json") for g in goals]}

        if action == "complete":
            if not goal_id:
                return {"error": "goal_id is required for complete action"}
            try:
                goal = await self.goal_engine.complete_goal(goal_id)
                return {"completed": goal.model_dump(mode="json")}
            except KeyError:
                return {"error": f"Goal {goal_id} not found"}

        if action == "fail":
            if not goal_id:
                return {"error": "goal_id is required for fail action"}
            try:
                goal = await self.goal_engine.fail_goal(goal_id, error=error)
                return {"failed": goal.model_dump(mode="json")}
            except KeyError:
                return {"error": f"Goal {goal_id} not found"}

        return {"error": f"Unknown action: {action}. Use create, list, complete, or fail."}


def create_goal_tools(goal_engine: GoalEngine) -> list[BaseTool]:
    """Create goal management tools bound to a GoalEngine instance.

    Args:
        goal_engine: The GoalEngine to bind.

    Returns:
        List containing the ManageGoalsTool.
    """
    return [ManageGoalsTool(goal_engine=goal_engine)]
