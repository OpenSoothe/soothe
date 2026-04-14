"""Widget for rendering Soothe protocol events as compact indicators.

RFC-606: Soothe CLI TUI Migration
"""

from __future__ import annotations

from typing import Any

from textual.widgets import Static


class ProtocolEventWidget(Static):
    """Widget for rendering protocol events as compact indicators.

    Style: Icon + brief message + optional status
    Placement: Status bar activity queue, plan tree panel

    This widget renders Soothe protocol events (soothe.plan.*,
    soothe.context.*, soothe.memory.*, soothe.policy.*, soothe.goal.*)
    as compact one-liner indicators similar to Soothe tool call indicators.
    """

    def render_event(self, event: dict[str, Any]) -> str:
        """Render protocol event as Rich markup string.

        Args:
            event: Protocol event dict with type and fields

        Returns:
            Rich markup string for display
        """
        event_type = event.get("type", "")

        # SOOTHE: Route to specialized renderer based on event type
        if event_type.startswith("soothe.plan"):
            return self._render_plan_event(event)
        elif event_type.startswith("soothe.context"):
            return self._render_context_event(event)
        elif event_type.startswith("soothe.memory"):
            return self._render_memory_event(event)
        elif event_type.startswith("soothe.policy"):
            return self._render_policy_event(event)
        elif event_type.startswith("soothe.goal"):
            return self._render_goal_event(event)
        elif event_type.startswith("soothe.thread"):
            return self._render_thread_event(event)
        else:
            return self._render_generic_event(event)

    def _render_plan_event(self, event: dict[str, Any]) -> str:
        """Plan events: step progress.

        Args:
            event: Plan event dict

        Returns:
            Rendered string
        """
        event_type = event.get("type", "")

        if event_type == "soothe.plan.created":
            goal = event.get("goal", "")
            step_count = event.get("step_count", 0)
            return f"📋 [cyan]Plan created[/cyan]: {goal} ({step_count} steps)"

        elif event_type == "soothe.plan.step_started":
            step_id = event.get("step_id", "")
            description = event.get("description", "")
            return f"📋 [cyan]Starting[/cyan]: {description} (step {step_id})"

        elif event_type == "soothe.plan.step_completed":
            success = event.get("success", False)
            if success:
                return "✅ [green]Completed[/green]"
            else:
                return "❌ [red]Failed[/red]"

        else:
            return f"📋 [cyan]Plan[/cyan]: {event_type}"

    def _render_context_event(self, event: dict[str, Any]) -> str:
        """Context events: projection/ingestion.

        Args:
            event: Context event dict

        Returns:
            Rendered string
        """
        event_type = event.get("type", "")

        if event_type == "soothe.context.projected":
            entries = event.get("entries", 0)
            tokens = event.get("tokens", 0)
            return f"🔍 [magenta]Context[/magenta]: {entries} entries ({tokens} tokens)"

        elif event_type == "soothe.context.ingested":
            entries = event.get("entries", 0)
            return f"🔍 [magenta]Context ingested[/magenta]: {entries} entries"

        else:
            return f"🔍 [magenta]Context[/magenta]: {event_type}"

    def _render_memory_event(self, event: dict[str, Any]) -> str:
        """Memory events: recall/store.

        Args:
            event: Memory event dict

        Returns:
            Rendered string
        """
        event_type = event.get("type", "")

        if event_type == "soothe.memory.recalled":
            count = event.get("count", 0)
            return f"💭 [yellow]Memory[/yellow]: recalled {count} items"

        elif event_type == "soothe.memory.stored":
            content_preview = event.get("content_preview", "")
            return f"💭 [yellow]Memory stored[/yellow]: {content_preview[:50]}"

        else:
            return f"💭 [yellow]Memory[/yellow]: {event_type}"

    def _render_policy_event(self, event: dict[str, Any]) -> str:
        """Policy events: approval/denial.

        Args:
            event: Policy event dict

        Returns:
            Rendered string
        """
        event_type = event.get("type", "")

        if event_type == "soothe.policy.checked":
            action = event.get("action", "")
            verdict = event.get("verdict", "")
            if verdict == "allowed":
                return f"🔒 [green]Policy approved[/green]: {action}"
            else:
                return f"🔒 [yellow]Policy check[/yellow]: {action} → {verdict}"

        elif event_type == "soothe.policy.denied":
            action = event.get("action", "")
            reason = event.get("reason", "")
            return f"🔒 [red]Policy denied[/red]: {action} - {reason}"

        else:
            return f"🔒 Policy: {event_type}"

    def _render_goal_event(self, event: dict[str, Any]) -> str:
        """Goal events: batch execution.

        Args:
            event: Goal event dict

        Returns:
            Rendered string
        """
        event_type = event.get("type", "")

        if event_type == "soothe.goal.batch_started":
            goal_count = event.get("goal_count", 0)
            return f"🎯 [cyan]Goals batch[/cyan]: {goal_count} goals"

        elif event_type == "soothe.goal.report":
            completed = event.get("completed", 0)
            failed = event.get("failed", 0)
            return f"🎯 [cyan]Goals[/cyan]: {completed} done, {failed} failed"

        else:
            return f"🎯 [cyan]Goal[/cyan]: {event_type}"

    def _render_thread_event(self, event: dict[str, Any]) -> str:
        """Thread events: lifecycle.

        Args:
            event: Thread event dict

        Returns:
            Rendered string
        """
        event_type = event.get("type", "")

        if event_type == "soothe.thread.started":
            return "▶️ [green]Thread started[/green]"

        elif event_type == "soothe.thread.ended":
            summary = event.get("summary", "")
            return f"⏹️ [green]Thread ended[/green]: {summary}"

        else:
            return f"Thread: {event_type}"

    def _render_generic_event(self, event: dict[str, Any]) -> str:
        """Generic fallback renderer.

        Args:
            event: Generic event dict

        Returns:
            Rendered string
        """
        event_type = event.get("type", "unknown")
        return f"[white]{event_type}[/white]"
