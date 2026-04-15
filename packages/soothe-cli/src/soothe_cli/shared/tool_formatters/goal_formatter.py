"""Formatter for goal management tools."""

from __future__ import annotations

from typing import Any

from soothe_cli.shared.tool_formatters.base import BaseFormatter
from soothe_cli.shared.tool_output_formatter import ToolBrief


class GoalFormatter(BaseFormatter):
    """Formatter for goal management tools.

    Handles: create_goal, list_goals, complete_goal, fail_goal

    Provides semantic summaries with goal IDs, counts, and status.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:
        """Format goal management tool result.

        Args:
            tool_name: Name of the goal tool.
            result: Tool result (dict with goal data).

        Returns:
            ToolBrief with goal summary.

        Raises:
            ValueError: If tool_name is not a recognized goal tool.

        Example:
            >>> formatter = GoalFormatter()
            >>> brief = formatter.format("create_goal", {"created": {"id": "g1"}})
            >>> brief.to_display()
            '✓ Created goal g1'
        """
        # Normalize tool name
        normalized = tool_name.lower().replace("-", "_").replace(" ", "_")

        # Route to specific formatter
        if normalized == "create_goal":
            return self._format_create_goal(result)
        if normalized == "list_goals":
            return self._format_list_goals(result)
        if normalized == "complete_goal":
            return self._format_complete_goal(result)
        if normalized == "fail_goal":
            return self._format_fail_goal(result)
        msg = f"Unknown goal tool: {tool_name}"
        raise ValueError(msg)

    def _format_create_goal(self, result: dict[str, Any]) -> ToolBrief:
        """Format create_goal result.

        Shows created goal ID.

        Args:
            result: Dict with 'created' field containing goal object.

        Returns:
            ToolBrief with goal ID.

        Example:
            >>> brief = formatter._format_create_goal({"created": {"id": "g1", "priority": 80}})
            >>> brief.summary
            'Created goal g1'
        """
        # Handle dict result
        if isinstance(result, dict):
            # Check for error
            if "error" in result:
                error_msg = str(result["error"])
                return ToolBrief(
                    icon="✗",
                    summary="Create failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Extract goal data
            created = result.get("created", {})
            goal_id = created.get("id", "unknown")
            priority = created.get("priority")

            # Build summary
            summary = f"Created goal {goal_id}"

            # Build detail
            detail = None
            if priority is not None:
                detail = f"priority: {priority}"

            return ToolBrief(
                icon="✓",
                summary=summary,
                detail=detail,
                metrics={"goal_id": goal_id, "priority": priority},
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Create failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Created goal",
                detail=None,
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✓",
            summary="Created goal",
            detail=None,
            metrics={},
        )

    def _format_list_goals(self, result: dict[str, Any]) -> ToolBrief:
        """Format list_goals result.

        Shows count of goals.

        Args:
            result: Dict with 'goals' field containing list of goal objects.

        Returns:
            ToolBrief with goal count.

        Example:
            >>> brief = formatter._format_list_goals({"goals": [{"id": "g1"}, {"id": "g2"}]})
            >>> brief.summary
            'Found 2 goals'
        """
        # Handle dict result
        if isinstance(result, dict):
            # Check for error
            if "error" in result:
                error_msg = str(result["error"])
                return ToolBrief(
                    icon="✗",
                    summary="List failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Extract goals
            goals = result.get("goals", [])
            count = len(goals)

            # Build summary
            summary = f"Found {count} goal{'s' if count != 1 else ''}"

            return ToolBrief(
                icon="✓",
                summary=summary,
                detail=None,
                metrics={"count": count},
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="List failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Listed goals",
                detail=None,
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✓",
            summary="Listed goals",
            detail=None,
            metrics={},
        )

    def _format_complete_goal(self, result: dict[str, Any]) -> ToolBrief:
        """Format complete_goal result.

        Shows completed goal ID.

        Args:
            result: Dict with 'completed' field containing goal object.

        Returns:
            ToolBrief with goal ID.

        Example:
            >>> brief = formatter._format_complete_goal({"completed": {"id": "g1"}})
            >>> brief.summary
            'Completed goal g1'
        """
        # Handle dict result
        if isinstance(result, dict):
            # Check for error
            if "error" in result:
                error_msg = str(result["error"])
                return ToolBrief(
                    icon="✗",
                    summary="Complete failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Extract goal data
            completed = result.get("completed", {})
            goal_id = completed.get("id", "unknown")

            # Build summary
            summary = f"Completed goal {goal_id}"

            return ToolBrief(
                icon="✓",
                summary=summary,
                detail=None,
                metrics={"goal_id": goal_id},
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Complete failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Completed goal",
                detail=None,
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✓",
            summary="Completed goal",
            detail=None,
            metrics={},
        )

    def _format_fail_goal(self, result: dict[str, Any]) -> ToolBrief:
        """Format fail_goal result.

        Shows failed goal ID and reason.

        Args:
            result: Dict with 'failed' field containing goal object.

        Returns:
            ToolBrief with goal ID and failure reason.

        Example:
            >>> brief = formatter._format_fail_goal({"failed": {"id": "g1", "reason": "blocked"}})
            >>> brief.summary
            'Failed goal g1'
            >>> brief.detail
            'reason: blocked'
        """
        # Handle dict result
        if isinstance(result, dict):
            # Check for error
            if "error" in result:
                error_msg = str(result["error"])
                return ToolBrief(
                    icon="✗",
                    summary="Fail operation failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Extract goal data
            failed = result.get("failed", {})
            goal_id = failed.get("id", "unknown")
            reason = failed.get("reason", "unknown reason")

            # Build summary
            summary = f"Failed goal {goal_id}"

            # Build detail
            detail = f"reason: {reason}"

            return ToolBrief(
                icon="✗",
                summary=summary,
                detail=detail,
                metrics={"goal_id": goal_id, "reason": reason},
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Fail operation failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✗",
                summary="Failed goal",
                detail=None,
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✗",
            summary="Failed goal",
            detail=None,
            metrics={},
        )
