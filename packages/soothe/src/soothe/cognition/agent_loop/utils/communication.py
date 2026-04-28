"""Goal communication utilities for Layer 2 ↔ Layer 3 (RFC-204).

These are AgentLoop internal helpers, NOT CoreAgent execution tools.
Used directly by AgentLoop for querying Layer 3 GoalEngine.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


class GoalCommunicationHelper:
    """Helper for Layer 2 ↔ Layer 3 goal communication (RFC-204).

    Provides query and proposal methods for AgentLoop to communicate
    with GoalEngine (Layer 3). NOT a BaseTool - internal utility class.

    Query operations: get_related_goals, get_goal_progress, get_world_info, search_memory
    Proposal operations: report_progress, suggest_goal, flag_blocker, add_finding

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
        """Initialize communication helper.

        Args:
            goal_engine: GoalEngine instance.
            proposal_queue: Optional ProposalQueue for proposals.
            memory_protocol: Optional MemoryProtocol for memory search.
            iteration_count: Current iteration count.
            workspace: Workspace path.
            available_subagents: Available subagent names.
        """
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
            g
            for g in goals
            if g.status in ("active", "completed", "validated")
            and any(w in g.description.lower() for w in query_lower.split())
        ]

        return {
            "related_goals": [
                {"id": g.id, "description": g.description, "status": g.status} for g in related[:10]
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
            Dict with active_goals, total_goals, iteration_count, workspace,
            available_subagents.
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
            from soothe.cognition.goal_engine.proposal_queue import Proposal

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
            from soothe.cognition.goal_engine.proposal_queue import Proposal

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
            from soothe.cognition.goal_engine.proposal_queue import Proposal

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
            from soothe.cognition.goal_engine.proposal_queue import Proposal

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
