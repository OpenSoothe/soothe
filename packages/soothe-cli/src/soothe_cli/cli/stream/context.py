"""Pipeline context for tracking CLI display state."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCallInfo:
    """Information about an in-progress tool call.

    Attributes:
        name: Tool name.
        args_summary: Truncated args summary.
        start_time: Start timestamp (time.time()).
    """

    name: str
    args_summary: str
    start_time: float


@dataclass
class PipelineContext:
    """Context tracking for CLI stream display pipeline.

    Tracks goal, step, and tool state to produce contextual output.

    Attributes:
        current_goal: Current goal description.
        goal_start_time: Goal start timestamp.
        steps_total: Total steps in current goal.
        steps_completed: Completed step count.
        current_step_id: Active step ID.
        current_step_description: Active step description.
        step_start_time: Step start timestamp.
        pending_tool_calls: Tool calls awaiting results.
        parallel_mode: Whether multiple tools are running.
        subagent_name: Active subagent name.
        subagent_milestones: Accumulated subagent milestones.
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
    step_header_emitted: bool = False  # Track if step header was emitted
    _active_step_ids: list[str] = field(default_factory=list)  # Track parallel steps in progress
    step_descriptions: dict[str, str] = field(default_factory=dict)  # Track descriptions by step ID

    # Parallel tool tracking
    pending_tool_calls: dict[str, ToolCallInfo] = field(default_factory=dict)
    parallel_mode: bool = False
    parallel_header_emitted: bool = False  # Track if parallel header was emitted

    # Subagent tracking
    subagent_name: str | None = None
    subagent_milestones: list[str] = field(default_factory=list)

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
        self.step_header_emitted = False
        self.pending_tool_calls.clear()
        self.parallel_mode = False
        self.parallel_header_emitted = False
        self.subagent_name = None
        self.subagent_milestones.clear()
        # Don't clear _active_step_ids here - it's cleared when steps complete

    def complete_step(self, step_id: str) -> None:
        """Mark a step as completed and update tracking.

        Args:
            step_id: Step identifier to mark complete.
        """
        # Remove from active steps
        if step_id in self._active_step_ids:
            self._active_step_ids.remove(step_id)
        # Increment completed count
        self.steps_completed += 1

    def start_tool_call(
        self, tool_call_id: str, name: str, args_summary: str, start_time: float
    ) -> None:
        """Register a tool call as started.

        Args:
            tool_call_id: Tool call identifier.
            name: Tool name.
            args_summary: Truncated args.
            start_time: Start timestamp.
        """
        self.pending_tool_calls[tool_call_id] = ToolCallInfo(
            name=name,
            args_summary=args_summary,
            start_time=start_time,
        )
        # Enable parallel mode if multiple tools running
        if len(self.pending_tool_calls) > 1:
            self.parallel_mode = True

    def complete_tool_call(self, tool_call_id: str) -> ToolCallInfo | None:
        """Mark a tool call as completed.

        Args:
            tool_call_id: Tool call identifier.

        Returns:
            ToolCallInfo if found, None otherwise.
        """
        info = self.pending_tool_calls.pop(tool_call_id, None)
        # Disable parallel mode when all tools complete
        if not self.pending_tool_calls:
            self.parallel_mode = False
            self.parallel_header_emitted = False
        return info


__all__ = ["PipelineContext", "ToolCallInfo"]
