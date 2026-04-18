"""Stream display pipeline for CLI progress output."""

from __future__ import annotations

import logging
import time
from typing import Any

from soothe_sdk.client.protocol import preview_first
from soothe_sdk.verbosity import VerbosityTier

from soothe_cli.cli.stream.context import PipelineContext
from soothe_cli.cli.stream.display_line import DisplayLine
from soothe_cli.cli.stream.formatter import (
    format_goal_done,
    format_goal_header,
    format_judgement,
    format_plan_phase_reasoning,
    format_reasoning,
    format_step_done,
    format_step_header,
    format_subagent_done,
    format_subagent_milestone,
    format_tool_call,
)
from soothe_cli.shared.display_policy import VerbosityLevel, normalize_verbosity
from soothe_cli.shared.essential_events import (
    LOOP_REASON_EVENT_TYPE,
    is_goal_start_event_type,
    is_step_complete_event_type,
    is_step_start_event_type,
)
from soothe_cli.shared.presentation_engine import PresentationEngine

logger = logging.getLogger(__name__)

# Batch step events for parallel execution
BATCH_STEP_STARTED = "soothe.cognition.plan.batch.started"
BATCH_STEP_COMPLETED = "soothe.cognition.plan.batch.completed"

GOAL_COMPLETE_EVENTS = {
    "soothe.cognition.agent_loop.completed",
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
        from soothe_sdk.ux import classify_event_to_tier, is_subagent_progress_event

        # Goal events - NORMAL
        if is_goal_start_event_type(event_type):
            return VerbosityTier.NORMAL

        # Step start events - NORMAL (user-visible step descriptions)
        if is_step_start_event_type(event_type):
            return VerbosityTier.NORMAL

        # Goal completion - QUIET (always visible)
        if event_type in GOAL_COMPLETE_EVENTS:
            return VerbosityTier.QUIET

        # Subagent capability events - DETAILED by default, NORMAL for important progress
        # IG-192: Use SDK helper to identify important progress events (started/completed/judgement)
        if event_type.startswith("soothe.capability."):
            if is_subagent_progress_event(event_type):
                return VerbosityTier.NORMAL
            # Other capability events (internal steps) - DETAILED
            return VerbosityTier.DETAILED

        # soothe.* events: defer to SDK domain-based classification (RFC-0020)
        # Step completion, tool events use domain defaults
        if event_type.startswith("soothe."):
            return classify_event_to_tier(event_type)

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
        # Capability events (soothe.capability.<subagent>.<action>)
        # IG-192: Handle new unified naming scheme for subagent events
        if event_type.startswith("soothe.capability."):
            parts = event_type.split(".")
            if len(parts) >= 4:  # noqa: PLR2004
                # soothe.capability.<subagent>.<action>
                subagent = parts[2]
                action = parts[3]

                # Started/dispatched events
                if action in ("started", "dispatching"):
                    return self._on_subagent_dispatched(event, subagent)

                # Judgement events (research)
                if "judgement" in action:
                    return self._on_subagent_judgement(event)

                # Step events (browser automation): type ends with .step.running
                if len(parts) >= 5 and parts[3] == "step" and parts[4] == "running":  # noqa: PLR2004
                    return self._on_capability_step(event, subagent)

                # Completed events
                if action == "completed":
                    return self._on_subagent_completed(event, subagent)

                # Text/tool events (claude) - DETAILED level
                if action in ("text", "tool") and "running" in event_type:
                    return self._on_capability_activity(event, subagent, action)

        # Legacy subagent events (.subagent.* format)
        if ".subagent." in event_type and ".dispatched" in event_type:
            return self._on_subagent_dispatched(event)

        if ".subagent." in event_type and ".judgement" in event_type:
            return self._on_subagent_judgement(event)

        if ".subagent." in event_type and ".step" in event_type:
            return self._on_subagent_step(event)

        if ".subagent." in event_type and ".completed" in event_type:
            return self._on_subagent_completed(event)

        # Goal/step events
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

    def _on_subagent_dispatched(
        self, event: dict[str, Any], subagent_name: str = ""
    ) -> list[DisplayLine]:
        """Handle subagent dispatched event.

        Args:
            event: Event dictionary.
            subagent_name: Subagent name (extracted from event type).

        Returns:
            Display lines (none for dispatch, just tracking).
        """
        # Extract name from event type: soothe.capability.<name>.started
        event_type = event.get("type", "")
        parts = event_type.split(".")
        name = ""
        # Pattern: soothe.capability.<name>.started -> parts[0]=soothe, parts[1]=capability, parts[2]=name
        # Need at least 3 parts for valid capability event type
        if len(parts) >= 3 and parts[1] == "capability":  # noqa: PLR2004
            name = parts[2]
        name = name or subagent_name or event.get("name", event.get("subagent_name", ""))
        self._context.subagent_name = name
        self._context.subagent_milestones.clear()

        # Emit tool call for subagent dispatch
        query = event.get("query", event.get("task", event.get("topic", "")))
        args_summary = f'"{preview_first(query, 40)}"' if query else ""
        return [
            format_tool_call(
                f"{name}_subagent",
                args_summary,
                running=True,
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
                preview_first(brief, 60),
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _on_subagent_completed(
        self, event: dict[str, Any], subagent_name: str = ""
    ) -> list[DisplayLine]:
        """Handle subagent completed event.

        Args:
            event: Event dictionary.
            subagent_name: Subagent name (extracted from event type).

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
                preview_first(summary, 50),
                duration_s,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _on_capability_step(self, event: dict[str, Any], subagent_name: str) -> list[DisplayLine]:
        """Handle capability step event (e.g., browser automation steps).

        Args:
            event: Event dictionary.
            subagent_name: Subagent name (browser, etc.).

        Returns:
            Display lines for step milestone.
        """
        # Extract step info from different event schemas
        step = event.get("step", "")
        url = event.get("url", "")
        action = event.get("action", "")
        title = event.get("title", "")

        # Build brief description
        if url:
            brief = f"Step {step}: {action} on {url}"
        elif action:
            brief = f"Step {step}: {action}"
        elif title:
            brief = f"Step {step}: {title}"
        else:
            brief = f"Step {step}"

        return [
            format_subagent_milestone(
                preview_first(brief, 60),
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

    def _on_capability_activity(
        self, event: dict[str, Any], subagent_name: str, action_type: str
    ) -> list[DisplayLine]:
        """Handle capability activity event (e.g., claude text/tool).

        Args:
            event: Event dictionary.
            subagent_name: Subagent name (claude, etc.).
            action_type: Activity type (text, tool).

        Returns:
            Display lines for activity milestone (empty for DETAILED events).
        """
        # Claude text/tool events are DETAILED level - not shown at normal verbosity
        # Just return empty list, classification already filters them
        return []

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

        # Mark step complete (updates _active_step_ids and steps_completed)
        if step_id:
            self._context.complete_step(step_id)
            self._context.step_descriptions.pop(step_id, None)

        # Reset current step context (but not _active_step_ids)
        self._context.current_step_id = None
        self._context.current_step_description = None
        self._context.step_start_time = None

        # IG-182: Return list directly (formatter returns list now)
        return format_step_done(
            duration_s,
            tool_call_count=tool_call_count,
            success=success,
            error_msg=error_msg,
            namespace=self._current_namespace,
            verbosity_tier=self._verbosity_tier,
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
        """Handle AgentLoop Reason progress with prominent reasoning display (IG-152)."""
        status = event.get("status", "")

        # Extract action text (IG-152: full text, no truncation in schema or display)
        action_text = event.get("next_action", "").strip() or self._derive_action_from_status(
            status
        )

        if not action_text:
            return []

        # Polish: Capitalize first letter if not already
        if action_text and action_text[0].islower():
            action_text = action_text[0].upper() + action_text[1:]

        # IG-152: Show full action text to user (no truncation)
        # Word boundary respect happens at schema level (preview_first in planner)
        # CLI display should show complete reasoning chain for transparency

        # Deduplicate repeated actions
        if not self._presentation.should_emit_action(action_text=action_text):
            return []

        # Determine action type
        action = "complete" if status == "done" else "continue"

        raw_plan_action = event.get("plan_action")
        plan_action_kw: str | None = raw_plan_action if raw_plan_action in ("keep", "new") else None

        lines = [
            format_judgement(
                action_text,
                action,
                plan_action=plan_action_kw,
                namespace=self._current_namespace,
                verbosity_tier=self._verbosity_tier,
            )
        ]

        assessment = event.get("assessment_reasoning", "").strip()
        plan_reasoning = event.get("plan_reasoning", "").strip()
        if assessment or plan_reasoning:
            if assessment:
                lines.append(
                    format_plan_phase_reasoning(
                        "Assessment",
                        assessment,
                        namespace=self._current_namespace,
                        verbosity_tier=self._verbosity_tier,
                    )
                )
            if plan_reasoning:
                lines.append(
                    format_plan_phase_reasoning(
                        "Plan",
                        plan_reasoning,
                        namespace=self._current_namespace,
                        verbosity_tier=self._verbosity_tier,
                    )
                )
        else:
            reasoning = event.get("reasoning", "").strip()
            if reasoning:
                lines.append(
                    format_reasoning(
                        reasoning,
                        namespace=self._current_namespace,
                        verbosity_tier=self._verbosity_tier,
                    )
                )

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
