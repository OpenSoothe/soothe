"""Stream display pipeline for CLI progress output."""

from __future__ import annotations

import logging
import time
from typing import Any

from soothe.foundation.verbosity_tier import VerbosityTier
from soothe.ux.cli.stream.context import PipelineContext
from soothe.ux.cli.stream.display_line import DisplayLine
from soothe.ux.cli.stream.formatter import (
    format_goal_done,
    format_goal_header,
    format_judgement,
    format_step_done,
    format_step_header,
    format_subagent_done,
    format_subagent_milestone,
    format_tool_call,
)
from soothe.ux.shared.display_policy import VerbosityLevel, normalize_verbosity
from soothe.ux.shared.presentation_engine import PresentationEngine

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

# Batch step events for parallel execution
BATCH_STEP_STARTED = "soothe.cognition.plan.batch_step_started"
BATCH_STEP_COMPLETED = "soothe.cognition.plan.batch_step_completed"

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

    def __init__(
        self,
        verbosity: VerbosityLevel = "normal",
        *,
        presentation_engine: PresentationEngine | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            verbosity: Verbosity level for filtering.
            presentation_engine: Shared engine (defaults to a new instance).
        """
        self._verbosity = normalize_verbosity(verbosity)
        self._verbosity_tier = _VERBOSITY_TO_TIER.get(self._verbosity, VerbosityTier.NORMAL)
        self._context = PipelineContext()
        self._presentation = presentation_engine or PresentationEngine()
        self._current_namespace: tuple[str, ...] = ()  # Track current namespace

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

        # Extract namespace from event
        self._current_namespace = tuple(event.get("namespace", []))

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
        from soothe.core.event_catalog import REGISTRY

        # Goal events - NORMAL
        if event_type in GOAL_START_EVENTS:
            return VerbosityTier.NORMAL

        # Step start events - NORMAL (user-visible step descriptions)
        if event_type in STEP_START_EVENTS:
            return VerbosityTier.NORMAL

        # Goal completion - QUIET (always visible)
        if event_type in GOAL_COMPLETE_EVENTS:
            return VerbosityTier.QUIET

        # soothe.* events: defer to registry classification (RFC-0020)
        # Step completion, tool events, subagent events all use registry
        if event_type.startswith("soothe."):
            return REGISTRY.get_verbosity(event_type)

        # Non-soothe events (from deepagents subagents)
        if ".subagent." in event_type:
            return VerbosityTier.NORMAL

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

        if ".subagent." in event_type and ".dispatched" in event_type:
            return self._on_subagent_dispatched(event)

        if ".subagent." in event_type and ".judgement" in event_type:
            return self._on_subagent_judgement(event)

        if ".subagent." in event_type and ".step" in event_type:
            return self._on_subagent_step(event)

        if ".subagent." in event_type and ".completed" in event_type:
            return self._on_subagent_completed(event)

        if event_type in STEP_COMPLETE_EVENTS:
            return self._on_step_completed(event)

        if event_type in GOAL_COMPLETE_EVENTS:
            return self._on_goal_completed(event)

        if event_type == "soothe.cognition.loop_agent.reason":
            return self._on_loop_agent_reason(event)

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

        return [
            format_goal_header(
                goal,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

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

        # Track step by ID for parallel execution
        if step_id and step_id not in self._context._active_step_ids:
            self._context._active_step_ids.append(step_id)
        if step_id:
            self._context.step_descriptions[step_id] = description

        # Reset step context for this specific step
        self._context.current_step_id = step_id
        self._context.current_step_description = description
        self._context.step_start_time = time.time()
        self._context.step_header_emitted = True

        return [
            format_step_header(
                description,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _on_subagent_dispatched(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle subagent dispatched event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines (none for dispatch, just tracking).
        """
        # Extract name from event type: soothe.subagent.<name>.dispatched
        event_type = event.get("type", "")
        parts = event_type.split(".")
        name = ""
        # Pattern: soothe.subagent.<name>.dispatched -> parts[0]=soothe, parts[1]=subagent, parts[2]=name
        # Need at least 3 parts for valid subagent event type
        if len(parts) >= 3 and parts[1] == "subagent":  # noqa: PLR2004
            name = parts[2]
        name = name or event.get("name", event.get("subagent_name", ""))
        self._context.subagent_name = name
        self._context.subagent_milestones.clear()

        # Emit tool call for subagent dispatch
        query = event.get("query", event.get("task", event.get("topic", "")))
        args_summary = f'"{query[:40]}"' if query else ""
        return [
            format_tool_call(
                f"{name}_subagent",
                args_summary,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _on_subagent_judgement(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle subagent judgement event.

        IG-089: Shows meaningful LLM decision reasoning without raw intermediate data.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for judgement.
        """
        judgement = event.get("judgement", "")
        action = event.get("action", "")

        if not judgement:
            return []

        return [
            format_judgement(
                judgement,
                action,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

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

        return [
            format_subagent_milestone(
                brief[:60],
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _on_subagent_completed(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle subagent completed event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for completion.
        """
        # Handle various summary fields from different subagent events
        summary = event.get("summary", event.get("result", "done"))
        if not summary:
            # For events like ResearchCompletedEvent that have answer_length
            answer_len = event.get("answer_length", 0)
            result_count = event.get("result_count", 0)
            if answer_len:
                summary = f"{answer_len} chars"
            elif result_count:
                summary = f"{result_count} results"
            else:
                summary = "done"

        duration_s = event.get("duration_s", event.get("duration_seconds", 0))

        if duration_s == 0:
            duration_ms = event.get("duration_ms", 0)
            duration_s = duration_ms / 1000 if duration_ms else 0

        return [
            format_subagent_done(
                summary[:50],
                duration_s,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _on_step_completed(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle step completed event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for step completion.
        """
        step_id = event.get("step_id", "")
        duration_s = event.get("duration_s", event.get("duration_seconds", 0))
        if duration_s == 0:
            duration_ms = event.get("duration_ms", 0)
            duration_s = duration_ms / 1000 if duration_ms else 0

        # Use tracked start time if available
        if duration_s == 0 and self._context.step_start_time:
            duration_s = time.time() - self._context.step_start_time

        # Resolve description robustly for parallel/async step completions
        description = (
            self._context.step_descriptions.get(step_id, "")
            or self._context.current_step_description
            or event.get("description", "")
            or "Completed action"
        )

        # Get tool call count from event
        tool_call_count = event.get("tool_call_count", 0)

        # Mark step complete (updates _active_step_ids and steps_completed)
        if step_id:
            self._context.complete_step(step_id)
            self._context.step_descriptions.pop(step_id, None)

        # Reset current step context (but not _active_step_ids)
        self._context.current_step_id = None
        self._context.current_step_description = None
        self._context.step_start_time = None

        return [
            format_step_done(
                description,
                duration_s,
                tool_call_count=tool_call_count,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

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

        return [
            format_goal_done(
                goal,
                steps,
                total_s,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _on_loop_agent_reason(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle Layer 2 Reason progress with condensed action summary."""
        status = event.get("status", "")
        confidence = event.get("confidence", 0.0)

        # Extract action summary (priority order)
        action_text = (
            event.get("user_summary", "").strip()
            or event.get("soothe_next_action", "").strip()
            or self._derive_action_from_status(status)
        )

        if not action_text:
            return []

        # Format with confidence
        confidence_pct = confidence if confidence > 0 else 0.8
        formatted = f"{action_text} ({confidence_pct:.0%} sure)"

        # Deduplicate repeated actions
        if not self._presentation.should_emit_action(action_text=formatted):
            return []

        # Determine action type
        action = "complete" if status == "done" else "continue"

        return [
            format_judgement(
                formatted,
                action,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _derive_action_from_status(self, status: str) -> str:
        """Fallback action text when metadata missing.

        Args:
            status: Reason event status field.

        Returns:
            Human-readable action description, or empty string if no valid status.
        """
        if status == "done":
            return "Completing final analysis"
        if status == "replan":
            return "Trying alternative approach"
        if status == "working":
            return "Processing next step"
        # No fallback for missing/empty status - better to skip than emit noise
        return ""


__all__ = ["StreamDisplayPipeline"]
