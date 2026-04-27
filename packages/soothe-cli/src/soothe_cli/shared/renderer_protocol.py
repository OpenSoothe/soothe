"""Abstract callback interface for CLI/TUI event rendering.

This module defines the RendererProtocol that CLI and TUI renderers implement.
The EventProcessor calls these callbacks; implementations handle mode-specific display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from soothe_sdk.client.schemas import Plan


class RendererProtocol(Protocol):
    """Abstract callback interface for CLI/TUI event rendering.

    Implementations handle mode-specific display while EventProcessor
    handles unified event routing and state management.

    Core callbacks are required for basic functionality.
    Optional fine-grained hooks can be implemented for specific event handling.
    """

    # === Core Callbacks (Required) ===

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,
    ) -> None:
        """Assistant text chunk or complete message.

        Args:
            text: Text content to display.
            is_main: True if from main agent, False if from subagent.
            is_streaming: True if partial chunk, False if complete.
        """
        ...

    def on_streaming_output(
        self,
        event_type: str,
        text: str,
        *,
        is_chunk: bool,
        namespace: tuple[str, ...],
    ) -> None:
        """Streaming output chunk from unified framework (RFC-614).

        Optional method - default implementation may delegate to on_assistant_text.
        Implementations may choose different display styles for different event types.

        Args:
            event_type: Event type string (e.g., "soothe.output.execution.streaming").
            text: Text content (may be chunk or final).
            is_chunk: True if partial chunk, False if final.
            namespace: Namespace tuple for stream context.

        Note:
            This is optional - default implementation may delegate to on_assistant_text.
            Implementations may choose different display styles for different event types.
        """
        ...

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,
        *,
        is_main: bool,
    ) -> None:
        """Tool invocation started.

        Args:
            name: Tool name (snake_case internal name).
            args: Parsed argument dictionary.
            tool_call_id: Unique identifier for correlation with result.
            is_main: True if from main agent.
        """
        ...

    def on_tool_result(
        self,
        name: str,
        result: str,
        tool_call_id: str,
        *,
        is_error: bool,
        is_main: bool,
    ) -> None:
        """Tool returned a result.

        Args:
            name: Tool name.
            result: Result content (may be truncated).
            tool_call_id: Correlates with on_tool_call.
            is_error: True if result indicates failure.
            is_main: True if from main agent.
        """
        ...

    def on_status_change(self, state: str) -> None:
        """Daemon state changed.

        Args:
            state: One of "idle", "running", "stopped".
        """
        ...

    def on_error(self, error: str, *, context: str | None = None) -> None:
        """Error occurred.

        Args:
            error: Error message.
            context: Optional context (e.g., "tool_execution", "daemon").
        """
        ...

    def on_progress_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        namespace: tuple[str, ...],
    ) -> None:
        """Protocol/subagent progress event.

        Catch-all for events not covered by specific callbacks.

        Args:
            event_type: Full event type string (e.g., "soothe.capability.browser.step.running").
            data: Event payload.
            namespace: Subagent namespace tuple (empty for main agent).
        """
        ...

    # === Optional Fine-Grained Hooks ===
    # These have default no-op implementations in base renderers

    def on_plan_created(self, plan: Plan) -> None:
        """Plan was created.

        Default implementation may delegate to on_progress_event.

        Args:
            plan: The created plan object.
        """
        ...

    def on_plan_step_started(self, step_id: str, description: str) -> None:
        """Plan step began execution.

        Args:
            step_id: Unique step identifier.
            description: Step description.
        """
        ...

    def on_plan_step_completed(
        self,
        step_id: str,
        success: bool,  # noqa: FBT001
        duration_ms: int,
    ) -> None:
        """Plan step finished.

        Args:
            step_id: Unique step identifier.
            success: True if step succeeded.
            duration_ms: Execution duration in milliseconds.
        """
        ...

    def on_turn_end(self) -> None:
        """Current turn completed.

        Use for finalizing streaming buffers and cleanup.
        """
        ...
