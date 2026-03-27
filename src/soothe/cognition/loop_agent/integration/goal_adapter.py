"""Goal adapter for Layer 3 (GoalManager) integration.

Handles bidirectional communication between Layer 2 (LoopAgent) and Layer 3:
- Goal injection: Layer 3 → Layer 2 (sub-goal delegation)
- Goal escalation: Layer 2 → Layer 3 (scope expansion)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cognition.goal_manager.core.goal import Goal
    from soothe.cognition.goal_manager.manager.engine import GoalEngine
    from soothe.cognition.loop_agent.core.state import LoopState


logger = logging.getLogger(__name__)


class GoalAdapter:
    """Bridge between Layer 2 (LoopAgent) and Layer 3 (GoalManager).

    Implements the Layer 3 ↔ Layer 2 goal delegation protocol.
    """

    def __init__(self, goal_manager: GoalEngine | None) -> None:
        """Initialize goal adapter.

        Args:
            goal_manager: GoalEngine instance (None if autonomous mode disabled)
        """
        self.goal_manager = goal_manager

    async def inject_goal_into_loop(
        self,
        loop_state: LoopState,
        goal: Goal,
    ) -> None:
        """Inject Layer 3 goal context into Layer 2 state.

        Args:
            loop_state: Layer 2 state to update
            goal: Layer 3 goal to inject
        """
        # Set goal description
        loop_state.goal = goal.description

        # Track parent for escalation
        loop_state.parent_goal_id = goal.parent_id
        loop_state.current_goal_id = goal.id

        logger.debug("Injected goal %s into loop: %s", goal.id, goal.description[:100])

    async def request_goal_revision(
        self,
        loop_state: LoopState,
        escalation_reason: str,
    ) -> Goal | None:
        """Escalate scope expansion from Layer 2 to Layer 3.

        Triggered when judgment detects scope expansion.
        Only works if autonomous mode enabled (--autonomous flag).

        Args:
            loop_state: Current loop state
            escalation_reason: Why current goal is insufficient

        Returns:
            New goal if autonomous mode enabled, None otherwise
        """
        if not self.goal_manager:
            # No Layer 3, cannot escalate
            logger.debug("Cannot escalate goal: autonomous mode disabled")
            return None

        # Create new goal based on expanded scope
        new_goal = await self.goal_manager.create_goal(
            description=escalation_reason,
            parent_id=loop_state.current_goal_id,
            priority=60,  # Higher priority for escalated goals
        )

        logger.info(
            "Layer 2 escalated to Layer 3: created goal %s",
            new_goal.id,
            extra={"escalation_reason": escalation_reason},
        )

        return new_goal

    def is_autonomous_mode(self) -> bool:
        """Check if autonomous mode (Layer 3) is enabled."""
        return self.goal_manager is not None
