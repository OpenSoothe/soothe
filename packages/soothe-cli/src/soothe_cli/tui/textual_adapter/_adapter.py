"""TextualUIAdapter class and related type protocols/constants."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Protocol

    # Type alias matching HITLResponse["decisions"] element type
    from langchain.agents.middleware.human_in_the_loop import (
        ApproveDecision,
        EditDecision,
        RejectDecision,
    )
    from pydantic import TypeAdapter

    from soothe_cli.tui._ask_user_types import AskUserWidgetResult, Question

    HITLDecision = ApproveDecision | EditDecision | RejectDecision

    class _TokensUpdateCallback(Protocol):
        """Callback signature for `_on_tokens_update`."""

        def __call__(self, count: int, *, approximate: bool = False) -> None: ...

    class _TokensShowCallback(Protocol):
        """Callback signature for `_on_tokens_show`."""

        def __call__(self, *, approximate: bool = False) -> None: ...


from soothe_cli.tui._ask_user_types import AskUserRequest
from soothe_cli.tui._session_stats import (
    ModelStats as ModelStats,
)
from soothe_cli.tui._session_stats import (
    SessionStats as SessionStats,
)
from soothe_cli.tui._session_stats import (
    SpinnerStatus as SpinnerStatus,
)
from soothe_cli.tui._session_stats import (
    format_token_count as format_token_count,
)
from soothe_cli.tui.widgets.messages import (
    CognitionStepMessage,
    ToolCallMessage,
)

logger = logging.getLogger(__name__)

AGENT_LOOP_STEP_STARTED = "soothe.cognition.agent_loop.step.started"
AGENT_LOOP_STEP_COMPLETED = "soothe.cognition.agent_loop.step.completed"
AGENT_LOOP_STEP_TOOL_BINDING = "soothe.cognition.agent_loop.step.tool_binding"
AGENT_LOOP_GOAL_STARTED = "soothe.cognition.agent_loop.started"
AGENT_LOOP_GOAL_COMPLETED = "soothe.cognition.agent_loop.completed"

_hitl_adapter_cache: TypeAdapter | None = None
"""Lazy singleton for the HITL request validator."""


def _get_hitl_request_adapter(hitl_request_type: type) -> TypeAdapter:
    """Return a cached `TypeAdapter(HITLRequest)`.

    Avoids re-compiling the pydantic schema on every `execute_task_textual` call.

    Args:
        hitl_request_type: The `HITLRequest` class (passed in because
            it is imported locally by the caller).

    Returns:
        Shared `TypeAdapter` instance.
    """
    global _hitl_adapter_cache  # noqa: PLW0603
    if _hitl_adapter_cache is None:
        from pydantic import TypeAdapter

        _hitl_adapter_cache = TypeAdapter(hitl_request_type)
    return _hitl_adapter_cache


_ask_user_adapter_cache: TypeAdapter | None = None
"""Lazy singleton for the `ask_user` interrupt validator."""


def _get_ask_user_adapter() -> TypeAdapter:
    """Return a cached `TypeAdapter(AskUserRequest)`.

    Returns:
        Shared `TypeAdapter` instance.
    """
    global _ask_user_adapter_cache  # noqa: PLW0603
    if _ask_user_adapter_cache is None:
        from pydantic import TypeAdapter

        _ask_user_adapter_cache = TypeAdapter(AskUserRequest)
    return _ask_user_adapter_cache


class TextualUIAdapter:
    """Adapter for rendering agent output to Textual widgets.

    This adapter provides an abstraction layer between the agent execution and the
    Textual UI, allowing streaming output to be rendered as widgets.
    """

    def __init__(
        self,
        mount_message: Callable[..., Awaitable[None]],
        update_status: Callable[[str], None],
        request_approval: Callable[..., Awaitable[Any]],
        on_auto_approve_enabled: Callable[[], None] | None = None,
        set_spinner: Callable[[SpinnerStatus], Awaitable[None]] | None = None,
        set_active_message: Callable[[str | None], None] | None = None,
        sync_message_content: Callable[[str, str], None] | None = None,
        request_ask_user: (
            Callable[
                [list[Question]],
                Awaitable[asyncio.Future[AskUserWidgetResult] | None],
            ]
            | None
        ) = None,
    ) -> None:
        """Initialize the adapter."""
        self._mount_message = mount_message
        """Async callback to mount a message widget to the chat."""

        self._update_status = update_status
        """Callback to update the status bar text."""

        self._request_approval = request_approval
        """Async callback that returns a Future for HITL approval."""

        self._on_auto_approve_enabled = on_auto_approve_enabled
        """Callback invoked when auto-approve is enabled via the HITL approval
        menu.

        Fired when the user selects "Auto-approve all" from an approval dialog,
        allowing the app to sync its status bar and session state.
        """

        self._set_spinner = set_spinner
        """Callback to show/hide loading spinner."""

        self._set_active_message = set_active_message
        """Callback to set the active streaming message ID (pass `None` to clear)."""

        self._sync_message_content = sync_message_content
        """Callback to sync final message content back to the store after streaming."""

        self._request_ask_user = request_ask_user
        """Async callback for `ask_user` interrupts.

        When awaited, returns a `Future` that resolves to user answers.
        """

        # State tracking
        self._current_tool_messages: dict[str, ToolCallMessage] = {}
        """Map of tool call IDs to widgets still awaiting a ``ToolMessage`` (in-flight)."""

        self._tool_display_by_call_id: dict[str, ToolCallMessage | CognitionStepMessage] = {}
        """Stable tool_call_id → tool card or step card (``task`` on step aggregates here).

        Used for subagent activity lines and inner-tool result routing (IG-402). Cleared with
        the same lifecycle as in-flight tools."""

        self._current_step_messages: dict[str, CognitionStepMessage] = {}
        """Map of agent-loop act step IDs to step card widgets."""

        self._step_by_namespace: dict[tuple[Any, ...], CognitionStepMessage] = {}
        """Active step card per stream namespace (main-agent tool aggregation, IG-402)."""

        self._last_completed_main_step_execute_prose: str = ""
        """Execute-phase prose frozen when the main-namespace step completes.

        Used to suppress a duplicate standalone ``goal_completion`` assistant card when
        the runner replays the same body for headless (``ledger_direct``); the TUI
        already shows that text on the step card.
        """

        self._last_main_flushed_assistant_prose: str = ""
        """Body last written to a main-namespace ``AssistantMessage`` via flush.

        After ``chunk_position == last`` the adapter pops ``assistant_message_by_namespace``,
        so ``goal_completion`` cannot use ``existing_msg`` to detect an already-mounted
        execute card; this field preserves the final text for dedupe (``execute_wave`` path).
        """

        self._tool_to_step: dict[str, ToolCallMessage | CognitionStepMessage] = {}
        """tool_call_id → parent card (step or task) while awaiting a matching ``ToolMessage``."""

        self._task_inner_tool_pending_lines: dict[str, str] = {}
        """tool_call_id → invocation line for task subgraph tools awaiting ``ToolMessage``."""

        self._task_inner_tool_start_times: dict[str, float] = {}
        """Wall time when the pending inner-tool line was recorded (for duration in status)."""

        self._pending_main_tools: list[tuple[str, dict[str, Any]]] = []
        """IG-402: Ordered buffer of tool calls on main namespace awaiting step_started.

        Each entry is ``(tool_call_id, {name, args, raw_args})``. Insertion order
        is preserved so that when ``AGENT_LOOP_STEP_STARTED`` fires, only tools
        buffered **before** that event are flushed into the step card (not tools
        that arrive later for subsequent steps).
        """

        self._tool_call_to_step_id: dict[str, str] = {}
        """tool_call_id → step_id mapping for accurate parallel step routing.

        Populated by AGENT_LOOP_STEP_TOOL_BINDING events from executor.
        Used to route root-graph tool calls to the correct parallel step card.
        """

        # Token display callbacks (set by the app after construction)
        self._on_tokens_update: _TokensUpdateCallback | None = None
        """Called with total context tokens after each LLM response."""

        self._on_tokens_hide: Callable[[], None] | None = None
        """Called to hide the token display during streaming."""

        self._on_tokens_show: _TokensShowCallback | None = None
        """Called to restore the token display with the cached value."""

    def apply_tool_step_binding(self, tool_call_id: str, step_id: str) -> None:
        """Map a root-graph tool call to a step and migrate any misplaced row (parallel act).

        ``AGENT_LOOP_STEP_TOOL_BINDING`` may arrive after a row was attached using the
        namespace fallback; this moves the row to the authoritative step card when needed.

        Args:
            tool_call_id: LangChain / provider tool call id.
            step_id: Agent-loop execute step id.
        """
        tcid = str(tool_call_id).strip()
        sid = str(step_id).strip()
        if not tcid or not sid:
            return
        self._tool_call_to_step_id[tcid] = sid
        target = self._current_step_messages.get(sid)
        if target is None:
            logger.info(
                "[StepToolBind] ui_apply step_id=%s tool_call_id=%s target_card=missing",
                sid,
                tcid,
            )
            return
        parent = self._tool_to_step.get(tcid)
        migrated = False
        if parent is not None and parent is not target:
            pop = getattr(parent, "pop_tool_row", None)
            ingest = getattr(target, "ingest_tool_row", None)
            if callable(pop) and callable(ingest):
                moved = pop(tcid)
                if moved is not None:
                    ingest(moved)
                    migrated = True
            self._tool_to_step[tcid] = target
        disp = self._tool_display_by_call_id.get(tcid)
        if disp is parent and parent is not None:
            self._tool_display_by_call_id[tcid] = target
        if migrated:
            logger.info(
                "[StepToolBind] ui_migrate tool_call_id=%s step_id=%s from_parent=%s",
                tcid,
                sid,
                type(parent).__name__,
            )
        else:
            logger.debug(
                "[StepToolBind] ui_apply tool_call_id=%s step_id=%s parent=%s",
                tcid,
                sid,
                type(parent).__name__ if parent is not None else "none",
            )

    def finalize_pending_tools_with_error(self, error: str) -> None:
        """Mark all pending/running tool widgets as error and clear tracking.

        This is used as a safety net when an unexpected exception aborts
        streaming before matching `ToolMessage` results are received.

        Args:
            error: Error text to display in each pending tool widget.
        """
        for tool_msg in list(self._current_tool_messages.values()):
            tool_msg.set_error(error)
        self._current_tool_messages.clear()
        self._tool_display_by_call_id.clear()

        for tcid, step_w in list(self._tool_to_step.items()):
            step_w.set_tool_error(tcid, error, duration_ms=0)
        self._tool_to_step.clear()
        self._step_by_namespace.clear()
        self._task_inner_tool_pending_lines.clear()
        self._task_inner_tool_start_times.clear()
        self._pending_main_tools.clear()
        self._last_completed_main_step_execute_prose = ""
        self._last_main_flushed_assistant_prose = ""
        self._tool_call_to_step_id.clear()

        # Clear active streaming message to avoid stale "active" state in the store.
        if self._set_active_message:
            self._set_active_message(None)

    def finalize_pending_steps_with_error(self, message: str) -> None:
        """Mark in-flight step cards as interrupted and clear tracking."""
        for step_msg in list(self._current_step_messages.values()):
            step_msg.set_interrupted(message)
        self._current_step_messages.clear()
        self._tool_to_step.clear()
        self._step_by_namespace.clear()
        self._task_inner_tool_pending_lines.clear()
        self._task_inner_tool_start_times.clear()
        self._pending_main_tools.clear()
        self._last_completed_main_step_execute_prose = ""
        self._last_main_flushed_assistant_prose = ""
        self._tool_call_to_step_id.clear()
