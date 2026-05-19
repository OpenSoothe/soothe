"""Pipeline context for tracking CLI display state."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PipelineContext:
    """Context tracking for CLI stream display pipeline.

    Tracks goal and step state to produce contextual output.

    Attributes:
        current_goal: Current goal description.
        goal_start_time: Goal start timestamp.
        steps_total: Total steps in current goal.
        steps_completed: Completed step count.
        current_step_id: Active step ID.
        current_step_description: Active step description.
        step_start_time: Step start timestamp.
        step_descriptions: Description by step ID (parallel-step tracking).
    """

    # Goal state
    current_goal: str | None = None
    goal_start_time: float | None = None
    steps_total: int = 0
    steps_completed: int = 0

    # Step state
    current_step_id: str | None = None
    current_step_description: str | None = None
    step_start_time: float | None = None
    _active_step_ids: list[str] = field(default_factory=list)
    step_descriptions: dict[str, str] = field(default_factory=dict)

    def reset_goal(self) -> None:
        """Reset goal-related state."""
        self.current_goal = None
        self.goal_start_time = None
        self.steps_total = 0
        self.steps_completed = 0
        self._active_step_ids.clear()
        self.step_descriptions.clear()
        self.reset_step()

    def reset_step(self) -> None:
        """Reset step-related state."""
        self.current_step_id = None
        self.current_step_description = None
        self.step_start_time = None

    def complete_step(self, step_id: str) -> None:
        """Mark a step as completed and update tracking.

        Args:
            step_id: Step identifier to mark complete.
        """
        if step_id in self._active_step_ids:
            self._active_step_ids.remove(step_id)
        self.steps_completed += 1


__all__ = ["PipelineContext"]
