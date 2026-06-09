"""AutopilotProtocol - Layer 3 goal lifecycle and dispatch interface.

Autopilot manages goal DAG orchestration, lifecycle, and dispatch to
AgentLoop workers. It is the highest abstraction layer, coordinating
multi-goal execution with backoff reasoning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from soothe.config import SootheConfig

    # Import from current location (will update after move)
    from soothe.foundation.autopilot.engine.models import (
        BackoffDecision,
        EvidenceBundle,
        Goal,
    )
    from soothe.foundation.loop.state.schemas import PlanResult


@runtime_checkable
class AutopilotProtocol(Protocol):
    """Layer 3 Autopilot interface - Goal lifecycle and dispatch.

    Autopilot manages:
    - Goal DAG orchestration (create, schedule, dependencies)
    - Goal lifecycle (pending, active, completed, failed)
    - Backoff reasoning on failure
    - Dispatch to AgentLoop workers

    This protocol enables alternative Autopilot implementations while
    maintaining AgentLoop isolation (Autopilot dispatches to Loop,
    Loop doesn't know Autopilot internals).

    Key responsibilities:
    - Goal creation with dependency DAG
    - Priority-based goal scheduling
    - BackoffReasoner for failure recovery
    - GoalDirective application for DAG restructuring
    """

    def create_goal(
        self,
        description: str,
        priority: int = 50,
        parent_id: str | None = None,
        depends_on: list[str] | None = None,
    ) -> Goal:
        """Create a new goal in the DAG.

        Args:
            description: Goal text description
            priority: Priority 0-100 (higher = first)
            parent_id: Parent goal for hierarchical goals
            depends_on: Prerequisite goal IDs

        Returns:
            Created Goal instance.
        """
        ...

    def get_goal(self, goal_id: str) -> Goal | None:
        """Get goal by ID.

        Args:
            goal_id: 8-char hex goal identifier

        Returns:
            Goal instance or None if not found.
        """
        ...

    def get_next_ready_goal(self) -> Goal | None:
        """Get next goal ready for execution (DAG-satisfied).

        Returns:
            Goal with dependencies satisfied and highest priority,
            or None if no goals ready.
        """
        ...

    def ready_goals(self, limit: int = 10) -> list[Goal]:
        """Get all goals ready for execution.

        Args:
            limit: Maximum goals to return

        Returns:
            List of DAG-satisfied, activated goals sorted by priority.
        """
        ...

    def complete_goal(
        self,
        goal_id: str,
        plan_result: PlanResult,
    ) -> None:
        """Mark goal completed with Layer 2 evidence.

        Args:
            goal_id: Completed goal identifier
            plan_result: Layer 2 final result with evidence_summary
        """
        ...

    async def fail_goal(
        self,
        goal_id: str,
        evidence: EvidenceBundle,
        allow_retry: bool = True,
    ) -> BackoffDecision | None:
        """Mark goal failed with evidence, apply backoff reasoning.

        Args:
            goal_id: Failed goal identifier
            evidence: Layer 2 execution evidence (RFC-200 EvidenceBundle)
            allow_retry: Whether retry is allowed

        Returns:
            BackoffDecision if backoff reasoning applied, None if no retry.
        """
        ...

    def list_goals(
        self,
        status: str | None = None,
    ) -> list[Goal]:
        """List goals by status filter.

        Args:
            status: Filter by status (pending, active, completed, failed)
                or None for all.

        Returns:
            List of matching goals.
        """
        ...

    def snapshot(self) -> dict:
        """Get DAG snapshot for persistence.

        Returns:
            Dict with all goals, dependencies, and statuses.
        """
        ...

    def restore_from_snapshot(self, snapshot: dict) -> None:
        """Restore DAG from persistence snapshot.

        Args:
            snapshot: Previously saved DAG state
        """
        ...

    @classmethod
    def create(cls, config: SootheConfig) -> AutopilotProtocol:
        """Factory method for creating Autopilot instances.

        Args:
            config: SootheConfig with autopilot/goal settings

        Returns:
            AutopilotProtocol instance ready for goal management.
        """
        ...
