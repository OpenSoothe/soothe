"""Stream display pipeline for CLI progress output."""

from __future__ import annotations

import logging
import time
from typing import Any

from soothe.core.verbosity_tier import VerbosityTier
from soothe.ux.cli.stream.context import PipelineContext
from soothe.ux.cli.stream.display_line import DisplayLine
from soothe.ux.cli.stream.formatter import (
    format_goal_done,
    format_goal_header,
    format_step_done,
    format_step_header,
    format_subagent_done,
    format_subagent_milestone,
    format_tool_call,
    format_tool_result,
)
from soothe.ux.core.display_policy import VerbosityLevel, normalize_verbosity

logger = logging.getLogger(__name__)

# Event type patterns
GOAL_START_EVENTS = {
    "soothe.agentic.loop.started",
    "soothe.cognition.plan.created",
}

STEP_START_EVENTS = {
    "soothe.cognition.plan.step_started",
    "soothe.agentic.step.started",
}

STEP_COMPLETE_EVENTS = {
    "soothe.cognition.plan.step_completed",
    "soothe.agentic.step.completed",
}

GOAL_COMPLETE_EVENTS = {
    "soothe.agentic.loop.completed",
}

# Verbosity tier mapping
_VERBOSITY_TO_TIER = {
    "quiet": VerbosityTier.QUIET,
    "normal": VerbosityTier.NORMAL,
    "detailed": VerbosityTier.DETAILED,
    "debug": VerbosityTier.DEBUG,
}


class StreamDisplayPipeline:
    """Pipeline for processing events into CLI display lines.

    Processes events with integrated verbosity filtering and context tracking.
    Emits structured DisplayLine objects for rendering.

    Usage:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        for event in events:
            lines = pipeline.process(event)
            renderer.write_lines(lines)
    """

    def __init__(self, verbosity: VerbosityLevel = "normal") -> None:
        """Initialize the pipeline.

        Args:
            verbosity: Verbosity level for filtering.
        """
        self._verbosity = normalize_verbosity(verbosity)
        self._verbosity_tier = _VERBOSITY_TO_TIER.get(self._verbosity, VerbosityTier.NORMAL)
        self._context = PipelineContext()

    def process(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Process an event into display lines.

        Args:
            event: Event dictionary with 'type' key.

        Returns:
            List of DisplayLine objects to render.
        """
        event_type = event.get("type", "")
        if not event_type:
            return []

        # Classify and filter
        tier = self._classify_event(event_type)
        if tier > self._verbosity_tier:
            return []

        # Dispatch to handlers
        return self._dispatch_event(event_type, event)

    def _classify_event(self, event_type: str) -> VerbosityTier:
        """Classify event type to verbosity tier.

        Args:
            event_type: Event type string.

        Returns:
            VerbosityTier for the event.
        """
        # Goal events - NORMAL
        if event_type in GOAL_START_EVENTS:
            return VerbosityTier.NORMAL

        # Step events - NORMAL
        if event_type in STEP_START_EVENTS or event_type in STEP_COMPLETE_EVENTS:
            return VerbosityTier.NORMAL

        # Tool events - NORMAL (key change from DETAILED)
        # Match: soothe.tool.file_ops.read_file_started, soothe.tool.*.call_started, etc.
        if ".tool." in event_type and ("_started" in event_type or "_completed" in event_type):
            return VerbosityTier.NORMAL

        # Subagent events - NORMAL
        if ".subagent." in event_type:
            return VerbosityTier.NORMAL

        # Goal completion - QUIET (always visible)
        if event_type in GOAL_COMPLETE_EVENTS:
            return VerbosityTier.QUIET

        # Default to DETAILED (hidden at normal)
        return VerbosityTier.DETAILED

    def _dispatch_event(self, event_type: str, event: dict[str, Any]) -> list[DisplayLine]:
        """Dispatch event to appropriate handler.

        Args:
            event_type: Event type string.
            event: Event dictionary.

        Returns:
            List of DisplayLine objects.
        """
        if event_type in GOAL_START_EVENTS:
            return self._on_goal_started(event)

        if event_type in STEP_START_EVENTS:
            return self._on_step_started(event)

        # Tool events: soothe.tool.file_ops.read_file_started, soothe.tool.*.call_started
        if ".tool." in event_type and "_started" in event_type:
            return self._on_tool_call_started(event)

        if ".tool." in event_type and "_completed" in event_type:
            return self._on_tool_call_completed(event)

        if ".subagent." in event_type and ".dispatched" in event_type:
            return self._on_subagent_dispatched(event)

        if ".subagent." in event_type and ".step" in event_type:
            return self._on_subagent_step(event)

        if ".subagent." in event_type and ".completed" in event_type:
            return self._on_subagent_completed(event)

        if event_type in STEP_COMPLETE_EVENTS:
            return self._on_step_completed(event)

        if event_type in GOAL_COMPLETE_EVENTS:
            return self._on_goal_completed(event)

        return []

    def _on_goal_started(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle goal start event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for goal header.
        """
        goal = event.get("goal", event.get("goal_description", ""))
        if not goal:
            return []

        # Reset context for new goal
        self._context.reset_goal()
        self._context.current_goal = goal
        self._context.goal_start_time = time.time()

        # Get steps count if available
        steps = event.get("steps", [])
        self._context.steps_total = len(steps) if steps else 0

        return [format_goal_header(goal)]

    def _on_step_started(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle step start event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for step header.
        """
        step_id = event.get("step_id", event.get("id", ""))
        description = event.get("description", event.get("step_description", ""))

        if not description:
            return []

        # Reset step context
        self._context.reset_step()
        self._context.current_step_id = step_id
        self._context.current_step_description = description
        self._context.step_start_time = time.time()
        self._context.step_header_emitted = True

        # Calculate step number
        step_num = self._context.steps_completed + 1

        return [format_step_header(step_num, description)]

    def _on_tool_call_started(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle tool call started event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for tool call.
        """
        # Handle both event formats:
        # - soothe.tool.file_ops.read_file_started: {'tool': 'read_file', 'args': {...}}
        # - soothe.tool.*.call_started: {'name': 'read_file', 'tool_call_id': '...'}
        tool_call_id = event.get("tool_call_id", event.get("id", ""))
        name = event.get("name", event.get("tool", "tool"))
        args = event.get("args", {})
        args_summary = self._format_args_summary(args)

        # Track tool call
        start_time = time.time()
        self._context.start_tool_call(tool_call_id, name, args_summary, start_time)

        lines = []

        # If entering parallel mode and header not yet emitted with (parallel)
        if (
            self._context.parallel_mode
            and not self._context.parallel_header_emitted
            and self._context.current_step_description
        ):
            # Re-emit step header with (parallel) suffix
            step_num = self._context.steps_completed + 1
            lines.append(format_step_header(step_num, self._context.current_step_description, parallel=True))
            self._context.parallel_header_emitted = True

        # Emit tool call
        is_running = self._context.parallel_mode
        lines.append(format_tool_call(name, args_summary, running=is_running))

        return lines

    def _on_tool_call_completed(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle tool call completed event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for tool result.
        """
        # Handle both event formats:
        # - soothe.tool.file_ops.read_file_completed: {'tool': 'read_file', 'result_preview': '...'}
        # - soothe.tool.*.call_completed: {'name': 'read_file', 'result': '...', 'duration_ms': 100}
        tool_call_id = event.get("tool_call_id", event.get("id", ""))
        name = event.get("name", event.get("tool", "tool"))
        result = event.get("result", event.get("result_preview", ""))
        is_error = event.get("is_error", False)
        duration_ms = event.get("duration_ms", 0)

        # Track tool call if not already tracked
        if not tool_call_id:
            tool_call_id = f"{name}_{time.time()}"

        # Get tool info and calculate duration if not provided
        tool_info = self._context.complete_tool_call(tool_call_id)
        if tool_info and duration_ms == 0:
            duration_ms = int((time.time() - tool_info.start_time) * 1000)

        # Format result summary
        summary = self._format_result_summary(result, is_error=is_error)

        return [format_tool_result(summary, duration_ms, is_error=is_error)]

    def _on_subagent_dispatched(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle subagent dispatched event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines (none for dispatch, just tracking).
        """
        name = event.get("name", event.get("subagent_name", ""))
        self._context.subagent_name = name
        self._context.subagent_milestones.clear()

        # Emit tool call for subagent dispatch
        query = event.get("query", event.get("task", ""))
        args_summary = f'"{query[:40]}"' if query else ""
        return [format_tool_call(f"{name}_subagent", args_summary)]

    def _on_subagent_step(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle subagent step event (compact hybrid).

        Args:
            event: Event dictionary.

        Returns:
            Display lines for milestone (if significant).
        """
        # Only show query/analyze type steps
        step_type = event.get("step_type", event.get("type", ""))
        if step_type not in ("query", "analyze", "search", "fetch"):
            return []

        brief = event.get("brief", event.get("summary", ""))
        if not brief:
            action = event.get("action", "")
            target = event.get("target", "")
            brief = f"{action}: {target}" if action and target else action or target

        if not brief:
            return []

        return [format_subagent_milestone(brief[:60])]

    def _on_subagent_completed(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle subagent completed event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for completion.
        """
        summary = event.get("summary", event.get("result", "done"))
        duration_s = event.get("duration_s", event.get("duration_seconds", 0))

        if duration_s == 0:
            duration_ms = event.get("duration_ms", 0)
            duration_s = duration_ms / 1000 if duration_ms else 0

        return [format_subagent_done(summary[:50], duration_s)]

    def _on_step_completed(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle step completed event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for step completion.
        """
        duration_s = event.get("duration_s", event.get("duration_seconds", 0))
        if duration_s == 0:
            duration_ms = event.get("duration_ms", 0)
            duration_s = duration_ms / 1000 if duration_ms else 0

        # Use tracked start time if available
        if duration_s == 0 and self._context.step_start_time:
            duration_s = time.time() - self._context.step_start_time

        step_num = self._context.steps_completed + 1
        self._context.steps_completed = step_num

        # Reset step context
        self._context.reset_step()

        return [format_step_done(step_num, duration_s)]

    def _on_goal_completed(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle goal completed event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for goal completion.
        """
        goal = self._context.current_goal or event.get("goal", "")
        steps = self._context.steps_completed or event.get("total_steps", 0)

        total_s = event.get("total_duration_s", 0)
        if total_s == 0 and self._context.goal_start_time:
            total_s = time.time() - self._context.goal_start_time

        # Reset goal context
        self._context.reset_goal()

        return [format_goal_done(goal, steps, total_s)]

    def _format_args_summary(self, args: Any, max_len: int = 40) -> str:
        """Format tool args as summary string.

        Args:
            args: Args value (dict or other).
            max_len: Maximum length.

        Returns:
            Truncated args summary.
        """
        if isinstance(args, dict):
            # Show first key-value pair
            if args:
                key = next(iter(args))
                val = str(args[key])[:20]
                return f'{key}="{val}"'
            return ""

        return str(args)[:max_len]

    def _format_result_summary(self, result: Any, *, is_error: bool, max_len: int = 60) -> str:
        """Format tool result as summary string.

        Args:
            result: Result value.
            is_error: Whether result is an error.
            max_len: Maximum length.

        Returns:
            Truncated result summary.
        """
        s = str(result)
        if is_error:
            # Show more of error messages
            return s[:max_len]

        # Try to extract meaningful summary
        if len(s) <= max_len:
            return s

        return s[: max_len - 3] + "..."


__all__ = ["StreamDisplayPipeline"]
