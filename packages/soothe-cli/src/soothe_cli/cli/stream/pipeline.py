"""Stream display pipeline for CLI progress output."""

from __future__ import annotations

import logging
import time
from typing import Any

from soothe_sdk.client.protocol import preview_first
from soothe_sdk.core.subagent_wire import (
    SUBAGENT_CLAUDE_FAILED,
    is_allowlisted_subagent_event_type,
    parse_subagent_wire_agent,
)
from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux.subagent_progress import (
    get_subagent_name_from_event,
    summarize_subagent_wire_activity,
)

from soothe_cli.cli.stream.context import PipelineContext
from soothe_cli.cli.stream.display_line import DisplayLine
from soothe_cli.cli.stream.formatter import (
    format_goal_done,
    format_goal_header,
    format_judgement,
    format_plan_phase_reasoning,
    format_step_done,
    format_step_header,
    format_subagent_done,
    format_subagent_milestone,
)
from soothe_cli.shared.core.presentation_engine import PresentationEngine
from soothe_cli.shared.events.essential_events import (
    LOOP_REASON_EVENT_TYPE,
    is_goal_start_event_type,
    is_step_complete_event_type,
    is_step_start_event_type,
)

logger = logging.getLogger(__name__)

GOAL_COMPLETE_EVENTS = {
    "soothe.cognition.agent_loop.completed",
}


class StreamDisplayPipeline:
    """Pipeline for processing events into CLI display lines.

    Processes events with integrated verbosity filtering and context tracking.
    Emits structured DisplayLine objects for rendering.

    Usage:
        pipeline = StreamDisplayPipeline()
        for event in events:
            lines = pipeline.process(event)
            renderer.write_lines(lines)
    """

    def __init__(
        self,
        *,
        presentation_engine: PresentationEngine | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            presentation_engine: Shared engine (defaults to a new instance).
        """
        self._context = PipelineContext()
        self._presentation = presentation_engine or PresentationEngine()

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

        tier = self._classify_event(event_type)
        if tier > VerbosityTier.NORMAL:
            return []

        return self._dispatch_event(event_type, event)

    def _classify_event(self, event_type: str) -> VerbosityTier:
        """Classify event type to verbosity tier.

        Args:
            event_type: Event type string.

        Returns:
            VerbosityTier for the event.
        """
        from soothe_sdk.ux import classify_event_to_tier

        # Goal events - NORMAL
        if is_goal_start_event_type(event_type):
            return VerbosityTier.NORMAL

        # Step start events - NORMAL (user-visible step descriptions)
        if is_step_start_event_type(event_type):
            return VerbosityTier.NORMAL

        # Goal completion - QUIET (always visible)
        if event_type in GOAL_COMPLETE_EVENTS:
            return VerbosityTier.QUIET

        # soothe.* events: defer to SDK domain-based classification (RFC-0020)
        # Step completion, tool events use domain defaults
        if event_type.startswith("soothe."):
            return classify_event_to_tier(event_type)

        # Non-soothe events (from deepagents subagents)
        if ".subagent." in event_type and not event_type.startswith("soothe.subagent."):
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
        # Curated delegated UX — metadata-only ``soothe.subagent.*`` (IG-339)
        if event_type.startswith("soothe.subagent."):
            return self._dispatch_curated_subagent_wire(event_type, event)

        if is_goal_start_event_type(event_type):
            return self._on_goal_started(event)

        if is_step_start_event_type(event_type):
            return self._on_step_started(event)

        if is_step_complete_event_type(event_type):
            return self._on_step_completed(event)

        if event_type in GOAL_COMPLETE_EVENTS:
            return self._on_goal_completed(event)

        if event_type == LOOP_REASON_EVENT_TYPE:
            return self._on_loop_agent_reason(event)

        return []

    def _task_scope_from_event(self, event: dict[str, Any]) -> tuple[str, str] | None:
        """Extract IG-334 ``(task_tool_call_id, subagent_type)`` when attached by the renderer."""
        ts = event.get("task_scope")
        if isinstance(ts, (list, tuple)) and len(ts) == 2:
            a, b = ts
            if isinstance(a, str) and isinstance(b, str):
                return (a, b)
        return None

    def _task_description_from_completed_event(
        self, event: dict[str, Any], subagent_name: str
    ) -> str | None:
        """Original task brief for completion lines (quoted in ``Task(type, \"…\")``)."""
        if subagent_name == "explore":
            raw = event.get("search_target")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return None

    def _dispatch_curated_subagent_wire(
        self, event_type: str, event: dict[str, Any]
    ) -> list[DisplayLine]:
        """Show compact lines for allowlisted ``soothe.subagent.*`` payloads (IG-339)."""
        if not is_allowlisted_subagent_event_type(event_type):
            logger.debug("Ignoring non-allowlisted soothe.subagent wire event: %s", event_type)
            return []

        task_scope = self._task_scope_from_event(event)
        agent_name = parse_subagent_wire_agent(event_type) or ""

        if event_type == SUBAGENT_CLAUDE_FAILED:
            msg = preview_first(str(event.get("message", "")), 120)
            summary = f"failed: {msg}" if msg else "failed"
            return [
                format_subagent_done(
                    preview_first(summary, 120),
                    0.0,
                    task_scope=task_scope,
                    task_done_success=False,
                )
            ]

        # Run-level ``*.completed`` only — not granular ``*.step.completed`` activity lines.
        if event_type.endswith(".completed") and ".step." not in event_type:
            # IG-340: When running inside a Task tool scope, suppress the wire
            # completion line; the task ToolMessage result path already emits an
            # authoritative completion line with full wall-clock duration.
            if task_scope:
                return []
            return self._on_subagent_completed(event, subagent_name=agent_name)

        brief = summarize_subagent_wire_activity(event_type, event)
        if not brief:
            brief = event_type.split(".")[-1].replace("_", " ")
        return [
            format_subagent_milestone(
                brief.strip(),
                task_scope=task_scope,
            )
        ]

    def _on_goal_started(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle goal start event.

        Args:
            event: Event dictionary.

        Returns:
            Display lines for goal header.
        """
        # IG-287: Prefer friendly_message over goal/goal_description
        friendly_message = event.get("friendly_message")
        goal = friendly_message or event.get("goal", event.get("goal_description", ""))
        if not goal:
            return []

        # Reset context for new goal
        self._context.reset_goal()
        # Store the actual goal description (not friendly message) for context tracking
        self._context.current_goal = event.get("goal", event.get("goal_description", goal))
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

        # Track step by ID for parallel execution
        if step_id and step_id not in self._context._active_step_ids:
            self._context._active_step_ids.append(step_id)
        if step_id:
            self._context.step_descriptions[step_id] = description

        # Reset step context for this specific step
        self._context.current_step_id = step_id
        self._context.current_step_description = description
        self._context.step_start_time = time.time()

        return [format_step_header(description)]

    def _on_subagent_completed(
        self, event: dict[str, Any], subagent_name: str = ""
    ) -> list[DisplayLine]:
        """Handle subagent completed event.

        Args:
            event: Event dictionary.
            subagent_name: Subagent name (extracted from event type).

        Returns:
            Display lines for completion with subagent-specific metrics.
        """
        # Extract subagent name from event type if not provided
        event_type = event.get("type", "")
        if not subagent_name:
            subagent_name = get_subagent_name_from_event(event_type) or ""

        summary = self._build_subagent_summary(event, subagent_name)

        duration_s = event.get("duration_s", event.get("duration_seconds", 0))

        if duration_s == 0:
            duration_ms = event.get("duration_ms", 0)
            duration_s = duration_ms / 1000 if duration_ms else 0

        task_description = self._task_description_from_completed_event(event, subagent_name)

        answer_tail: str | None = None
        raw_summary = event.get("summary")
        if isinstance(raw_summary, str) and raw_summary.strip() and subagent_name:
            answer_tail = preview_first(raw_summary.strip(), 120)

        return [
            format_subagent_done(
                preview_first(summary, 70),
                duration_s,
                task_scope=self._task_scope_from_event(event),
                task_description=task_description,
                answer_summary=answer_tail,
            )
        ]

    def _build_subagent_summary(self, event: dict[str, Any], subagent_name: str) -> str:
        """Build subagent-specific progress summary with metrics.

        Args:
            event: Event dictionary.
            subagent_name: Subagent id (e.g. explore, plan, research, or a plugin id).

        Returns:
            Formatted summary string with key metrics.
        """
        # Explore: total_findings, iterations_used, thoroughness
        if subagent_name == "explore":
            findings = event.get("total_findings", 0)
            iterations = event.get("iterations_used", 0)
            thoroughness = event.get("thoroughness", "")
            if findings:
                summary = f"{findings} findings"
                if iterations:
                    summary += f", {iterations} iterations"
                if thoroughness:
                    summary += f" ({thoroughness})"
                return summary
            return "done"

        # Claude Code / plugin id `claude`: cost_usd, claude_session_id
        if subagent_name == "claude":
            cost = event.get("cost_usd", 0.0)
            session_id = event.get("claude_session_id")
            if cost:
                summary = f"${float(cost):.2f}"
                if session_id:
                    summary += f", session={session_id[:8]}"
                return summary
            return "done"

        # Browser-use / plugin id `browser`: success status
        if subagent_name == "browser":
            success = event.get("success", True)
            return "✓ success" if success else "✗ failed"

        # Research: answer_length or result_count
        if subagent_name == "research":
            answer_len = event.get("answer_length", 0)
            result_count = event.get("result_count", 0)
            if answer_len:
                return f"{answer_len} chars"
            if result_count:
                return f"{result_count} results"
            return "done"

        summary = event.get("summary", event.get("result", "done"))
        return summary if summary else "done"

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

        # Get success/error status (IG-182)
        success = event.get("success", True)
        error_msg = None
        if not success:
            error_msg = event.get("error", event.get("error_message", ""))

        # Get tool call count from event
        tool_call_count = event.get("tool_call_count", 0)

        # Snapshot description before mutating context (IG-333).
        step_description = ""
        if step_id:
            step_description = (self._context.step_descriptions.get(step_id) or "").strip()
        if not step_description:
            step_description = (self._context.current_step_description or "").strip()

        # Mark step complete (updates _active_step_ids and steps_completed)
        if step_id:
            self._context.complete_step(step_id)
            self._context.step_descriptions.pop(step_id, None)

        # Reset current step context (but not _active_step_ids)
        self._context.current_step_id = None
        self._context.current_step_description = None
        self._context.step_start_time = None

        return format_step_done(
            duration_s,
            tool_call_count=tool_call_count,
            success=success,
            error_msg=error_msg,
            step_description=step_description,
        )

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

        self._context.reset_goal()

        return [format_goal_done(goal, steps, total_s)]

    def _on_loop_agent_reason(self, event: dict[str, Any]) -> list[DisplayLine]:
        """Handle AgentLoop Reason progress with prominent reasoning display (IG-152)."""
        status = event.get("status", "")

        # Extract action text (IG-152: full text, no truncation in schema or display)
        action_text = event.get("next_action", "").strip() or self._derive_action_from_status(
            status
        )

        if not action_text:
            return []

        if action_text and action_text[0].islower():
            action_text = action_text[0].upper() + action_text[1:]

        # IG-152: Show full action text to user (no truncation)
        # Word boundary respect happens at schema level (preview_first in planner)
        # CLI display should show complete reasoning chain for transparency

        if not self._presentation.should_emit_action(action_text=action_text):
            return []

        action = "complete" if status == "done" else "continue"

        lines = [format_judgement(action_text, action)]

        # IG-257: Only show Plan reasoning, Assessment removed from display
        plan_reasoning = event.get("plan_reasoning", "").strip()
        if plan_reasoning:
            # IG-257: Show Plan reasoning without "Plan:" prefix
            lines.append(format_plan_phase_reasoning("", plan_reasoning))

        return lines

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
