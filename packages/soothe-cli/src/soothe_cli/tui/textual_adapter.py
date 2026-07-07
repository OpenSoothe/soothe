"""Textual UI adapter: stream daemon events into Textual widgets.

Merged module (formerly ``tui/textual_adapter/`` package). Public symbols are listed
in ``__all__``; a few test-only helpers resolve via ``__getattr__``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from time import monotonic
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Protocol

    from langchain_core.runnables import RunnableConfig

    class _TokensUpdateCallback(Protocol):
        def __call__(self, count: int, *, approximate: bool = False) -> None: ...

    class _TokensShowCallback(Protocol):
        def __call__(self, *, approximate: bool = False) -> None: ...


from langchain_core.messages import AIMessage, HumanMessage
from soothe_sdk.core.events import (
    LOOP_CLARIFICATION_ANSWERED,
    LOOP_CLARIFICATION_DEFERRED,
    LOOP_CLARIFICATION_REQUESTED,
    STRANGE_LOOP_COMPLETED,
    STRANGE_LOOP_PLAN_DECISION,
    STRANGE_LOOP_PLAN_PHASE,
    STRANGE_LOOP_STARTED,
    STRANGE_LOOP_STEP_COMPLETED,
    STRANGE_LOOP_STEP_QUEUED,
    STRANGE_LOOP_STEP_STARTED,
    STREAM_END,
)
from soothe_sdk.core.subagent_wire import is_allowlisted_subagent_event_type
from soothe_sdk.langchain_wire import (
    messages_from_wire_dicts,
)
from soothe_sdk.ux.loop_stream import (
    LOOP_ASSISTANT_OUTPUT_PHASES,
    assistant_output_phase,
    is_goal_completion_stream_terminal,
    is_stream_terminal,
)
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, TOOL_CALL_UPDATES_BATCH
from soothe_sdk.ux.task_namespace import (
    TaskScope,
    is_inner_subgraph_task_tool_id,
    normalize_main_task_delegation_id,
    parse_unified_tool_call_id,
    row_key_for_subgraph_tool,
    task_scope_step_id,
    task_scope_task_idx,
)

from soothe_cli.runtime.parse.message_processing import (
    extract_tool_args_dict,
    ingest_tool_call_stream_state,
    tool_ids_touched_by_stream_message,
)
from soothe_cli.runtime.parse.tool_call_resolution import (
    build_streaming_args_overlay,
    is_step_card_tool_scope,
    materialize_ai_blocks_with_resolved_tools,
    merge_tool_display_args,
    predict_main_execute_tool_call_id,
    resolve_stream_tool_name,
    resolve_tool_result_row_key,
    should_ingest_tool_for_step_stats,
    tool_args_meaningful,
)
from soothe_cli.runtime.parse.tool_result import extract_tool_result_payload
from soothe_cli.runtime.policy.essential_events import (
    INTENT_CLASSIFIED_EVENT_TYPE,
    LOOP_REASON_EVENT_TYPE,
)
from soothe_cli.runtime.presentation.duration_format import format_duration
from soothe_cli.runtime.presentation.engine import PresentationEngine
from soothe_cli.runtime.presentation.renderer_base import RendererBase
from soothe_cli.runtime.presentation.subagent_task_display import (
    format_subagent_task_assistant_for_display,
)
from soothe_cli.runtime.state.file_tracker import (
    FILE_CHANGE_TOOLS,
    FileOpTracker,
    file_change_action_label,
    track_file_operation,
)
from soothe_cli.runtime.state.session_stats import (
    ModelStats,
    SessionStats,
    SpinnerStatus,
    TurnEventStats,
    TurnLatencyStats,
    build_goal_completed_log_event,
    build_turn_finished_log_event,
    format_cli_log_event,
    format_token_count,
)
from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.runtime.turn.pipeline import run_turn_pipeline
from soothe_cli.runtime.turn.prepare import (
    PreparedTurnChunk,
    TurnPrepareState,
    prepare_turn_chunk,
)
from soothe_cli.tui._cli_context import CLIContext
from soothe_cli.tui.commands.subagent_routing import parse_subagent_from_input
from soothe_cli.tui.config import build_stream_config
from soothe_cli.tui.file_change_notify import (
    finalize_file_change_preview,
    mount_file_change_preview,
)
from soothe_cli.tui.hooks import dispatch_hook
from soothe_cli.tui.input import MediaTracker, parse_file_mentions
from soothe_cli.tui.media_utils import create_multimodal_content
from soothe_cli.tui.spinner_labels import (
    SPINNER_LABEL_EXECUTING,
    SPINNER_LABEL_INPUT,
    SPINNER_LABEL_OFFLOADING,
    SPINNER_LABEL_RETRYING,
    SPINNER_LABEL_SYNTHESIZING,
    SPINNER_LABEL_THINKING,
    SPINNER_LABEL_TOOLS,
    SPINNER_LABEL_WRITING,
    map_plan_phase_spinner_label,
    retry_spinner_hint,
)
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    ClarificationInputMessage,
    CognitionGoalTreeMessage,
    CognitionReasonMessage,
    CognitionStepMessage,
    DiffMessage,
    SummarizationMessage,
    create_subagent_card,
    flush_deferred_tools_refreshes,
    reset_turn_tool_refresh_state,
)

logger = logging.getLogger(__name__)

# IG-504: LLM retry event type for step card status display
LLM_RETRY_ATTEMPT = "soothe.cognition.llm.retry.attempt"

# Single-chunk loop assistant phases mount immediately (avoid "Writing..." spinner).
_INSTANT_LOOP_ASSISTANT_PHASES = frozenset({"chitchat", "plan_direct", "autonomous_goal"})


def _retain_assistant_ns_on_stream_terminal(
    message: Any,
    *,
    ns_key: tuple[Any, ...],
    assistant_message_by_namespace: dict[tuple[Any, ...], Any],
    is_main_agent: bool,
) -> bool:
    """Return True when ``stream_terminal`` must not release the namespace card.

    Loop-tagged assistant streams append deltas onto one ``AssistantMessage``.
    """
    if is_main_agent and ns_key in assistant_message_by_namespace:
        return True
    phase = assistant_output_phase(message)
    return phase is not None and phase in LOOP_ASSISTANT_OUTPUT_PHASES


class TextualUIAdapter:
    """Adapter for rendering agent output to Textual widgets.

    This adapter provides an abstraction layer between the agent execution and the
    Textual UI, allowing streaming output to be rendered as widgets.
    """

    def __init__(
        self,
        mount_message: Callable[..., Awaitable[None]],
        update_status: Callable[[str], None],
        set_spinner: Callable[..., Awaitable[None]] | None = None,
        pause_spinner: Callable[[str], Awaitable[None]] | None = None,
        resume_spinner: Callable[[], Awaitable[None]] | None = None,
        set_active_message: Callable[[str | None], None] | None = None,
        sync_message_content: Callable[[str, str], None] | None = None,
    ) -> None:
        """Initialize the adapter."""
        self._mount_message = mount_message
        """Async callback to mount a message widget to the chat."""

        self._update_status = update_status
        """Callback to update the status bar text."""

        self._set_spinner = set_spinner
        """Callback to show/hide loading spinner."""

        self._pause_spinner = pause_spinner
        """Callback to pause the thinking-row spinner (clarification wait)."""

        self._resume_spinner = resume_spinner
        """Callback to resume the thinking-row spinner after clarification."""

        self._set_active_message = set_active_message
        """Callback to set the active streaming message ID (pass `None` to clear)."""

        self._sync_message_content = sync_message_content
        """Callback to sync final message content back to the store after streaming."""

        # State tracking
        self._tool_display_by_call_id: dict[str, CognitionStepMessage] = {}
        """Stable tool_call_id → step card for subagent activity and pending-tool routing."""

        self._current_step_messages: dict[str, CognitionStepMessage] = {}
        """Map of StrangeLoop act step IDs to step card widgets."""

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

        self._goal_completion_mounted_this_turn: bool = False
        """True when a standalone ``goal_completion`` assistant card was mounted this turn."""

        self._tool_to_step: dict[str, CognitionStepMessage] = {}
        """tool_call_id → step card while awaiting a matching ``ToolMessage``."""

        self._step_router = StepTaskRouter()
        """Per-turn routing for parallel steps, root tools, and subagent namespaces."""

        self._file_change_previews_shown: set[str] = set()
        """tool_call_ids that already have a non-blocking file-change preview card."""

        self._file_change_widgets: dict[str, Any] = {}
        """tool_call_id → mounted preview widget (finalized in place on tool completion)."""

        self._file_preview_assistant_id: str | None = None
        """Agent id for the active turn (path resolution in file previews)."""

        # IG-513: SubAgent card registry for routing inner subgraph tools
        self._subagent_cards_by_key: dict[str, Any] = {}
        """SubAgent cards keyed by "{step}:t{n}" for direct tool routing."""

        self._subagent_cards_by_key: dict[str, Any] = {}
        """SubAgent cards keyed by "{step}:t{n}" for direct tool routing."""

        # Token display callbacks (set by the app after construction)
        self._on_tokens_update: _TokensUpdateCallback | None = None
        """Called with total context tokens after each LLM response."""

        self._on_tokens_hide: Callable[[], None] | None = None
        """Called to hide the token display during streaming."""

        self._on_tokens_show: _TokensShowCallback | None = None
        """Called to restore the token display with the cached value."""

        self._clarification_pending: bool = False
        """RFC-622: True while the loop graph is paused on ``await_clarification``.

        Set when ``soothe.loop.clarification.requested`` arrives and survives the
        end of the current turn so the next ``send_turn`` can attach
        ``clarification_answer=True`` and the input UI can hint that text will
        be routed as the answer instead of a new goal. Cleared on
        ``soothe.loop.clarification.answered`` or after a clarification answer
        turn is dispatched.
        """

        self._execute_wave_total: int = 0
        """Steps in the current execute batch (for thinking-row progress)."""

        self._execute_wave_completed: int = 0
        """Completed steps in the current execute batch."""

        self._successful_step_ids: set[str] = set()
        """Step ids that finished successfully this loop (survives plan=keep replays)."""

        self._clarification_input_by_step: dict[str, ClarificationInputMessage] = {}
        """Active inline ``ClarificationInputMessage`` widgets keyed by step id.

        Entry is added when a clarification request arrives and removed once
        the user submits the dialog (the app handler renders the answers on
        the step card and forwards them to the daemon).
        """

        self._clarification_answers_pending: list[str] | None = None
        """RFC-622: per-question answers paired with the next clarification turn.

        Set by the app's clarification submit handler so ``execute_task_textual``
        can forward them on the wire as ``clarification_answers``. Cleared once
        attached to ``send_turn`` so a subsequent normal turn does not reuse
        stale answers.
        """

        self._last_plan_execution_mode: str | None = None
        """Execution mode from the latest ``plan_decision`` (``dependency`` / ``parallel``)."""

        self._plan_step_order: list[str] = []
        """Step ids from the latest plan wave in planner list order."""

        self._plan_step_ids: set[str] = set()
        """Step ids declared in the latest plan wave."""

        self._plan_step_dependencies: dict[str, tuple[str, ...]] = {}
        """Normalized dependency lists keyed by in-wave step id."""

        self._goal_tree_message: CognitionGoalTreeMessage | None = None
        """In-memory goal→steps state for the Ctrl+t plan quick view (not mounted in #messages)."""

    def finalize_pending_tools_with_error(self, error: str) -> None:
        """Mark all pending/running tool widgets as error and clear tracking.

        This is used as a safety net when an unexpected exception aborts
        streaming before matching `ToolMessage` results are received.

        Args:
            error: Error text to display in each pending tool widget.
        """
        self._tool_display_by_call_id.clear()

        for tcid, step_w in list(self._tool_to_step.items()):
            step_w.set_tool_error(tcid, error, duration_ms=0)
        self._tool_to_step.clear()
        self._step_by_namespace.clear()
        self._step_router.reset_turn()
        self._subagent_cards_by_key.clear()
        self._last_completed_main_step_execute_prose = ""
        self._last_main_flushed_assistant_prose = ""
        self._file_change_previews_shown.clear()
        self._file_change_widgets.clear()
        self._file_preview_assistant_id = None
        if self._goal_tree_message is not None:
            self._goal_tree_message.set_interrupted(error)

        # Clear active streaming message to avoid stale "active" state in the store.
        if self._set_active_message:
            self._set_active_message(None)

    def finalize_pending_steps_with_error(self, message: str) -> None:
        """Mark in-flight step cards as interrupted and clear tracking."""
        for step_id in list(self._current_step_messages.keys()):
            _finalize_subagent_cards_for_step(
                self,
                step_id,
                success=False,
                summary=message,
            )
        for step_msg in list(self._current_step_messages.values()):
            step_msg.set_interrupted(message)
        self._current_step_messages.clear()
        self._tool_to_step.clear()
        self._step_by_namespace.clear()
        self._tool_display_by_call_id.clear()
        self._step_router.reset_turn()
        self._subagent_cards_by_key.clear()
        self._last_completed_main_step_execute_prose = ""
        self._last_main_flushed_assistant_prose = ""
        if self._goal_tree_message is not None:
            self._goal_tree_message.set_interrupted(message)


def _stream_end_pending_error_message(
    adapter: TextualUIAdapter,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
) -> str:
    """Choose a user-visible label when the stream ends with in-flight steps."""
    from soothe_cli.cli.execution.daemon_errors import (
        is_daemon_worker_subprocess_lost,
        is_daemon_worker_thread_lost,
    )

    if bool(getattr(daemon_session, "last_turn_cancellation_seen", False)):
        return "Stream cancelled"
    end_state = getattr(daemon_session, "last_turn_end_state", None)
    if end_state == "stopped":
        return "Stream cancelled"
    if end_state == "connection_lost":
        return "Connection lost during stream"
    err_msg = getattr(daemon_session, "last_turn_error_message", None) or ""
    if is_daemon_worker_thread_lost(err_msg) or is_daemon_worker_subprocess_lost(err_msg):
        return "Worker stopped during stream"
    if end_state == "idle" and any(
        getattr(widget, "_status", "") in {"running", "queued"}
        for widget in adapter._current_step_messages.values()
    ):
        return "Stream ended before steps completed"
    return "Stream ended unexpectedly"


# ---------------------------------------------------------------------------
# Turn UI coalescing
# ---------------------------------------------------------------------------

_TOOL_UI_COALESCE_SEC = 0.05
_EXECUTE_WAVE_UI_COALESCE_SEC = 0.2
_CHUNK_YIELD_INTERVAL = 24
_CHUNK_YIELD_BUDGET_SEC = 0.016


class TurnToolUiCoalescer:
    """Batch tool-card repaints, dedupe wire kwargs, and yield during dense streams."""

    def __init__(self) -> None:
        reset_turn_tool_refresh_state()
        self._chunk_count = 0
        self._burst_start = monotonic()
        self._last_flush_at = 0.0
        self._wire_args_fingerprint: dict[str, str] = {}
        self.execute_wave_active = False

    def reset_turn(self) -> None:
        """Clear per-turn state (new user turn)."""
        reset_turn_tool_refresh_state()
        self._chunk_count = 0
        self._burst_start = monotonic()
        self._last_flush_at = 0.0
        self._wire_args_fingerprint.clear()
        self.execute_wave_active = False

    def note_wire_apply(self, tool_call_id: str, args: dict[str, Any]) -> bool:
        """Record a wire kwargs payload.

        Returns:
            True when the same ``(tool_call_id, args)`` was already applied.
        """
        key = str(tool_call_id).strip()
        if not key:
            return False
        try:
            fp = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            fp = repr(args)
        if self._wire_args_fingerprint.get(key) == fp:
            return True
        self._wire_args_fingerprint[key] = fp
        return False

    def wire_applied(self, tool_call_id: str) -> bool:
        """True when wire has already delivered displayable kwargs for this id."""
        return str(tool_call_id).strip() in self._wire_args_fingerprint

    def should_skip_messages_arg_refresh(self, tool_call_id: str) -> bool:
        """Skip messages-path arg refresh when execute wave uses wire authority."""
        if not self.execute_wave_active:
            return False
        return self.wire_applied(tool_call_id)

    def _coalesce_interval_sec(self) -> float:
        if self.execute_wave_active:
            return _EXECUTE_WAVE_UI_COALESCE_SEC
        return _TOOL_UI_COALESCE_SEC

    async def after_chunk(self, *, force_flush: bool = False) -> None:
        """Yield to Textual when needed and flush deferred tool-list repaints."""
        self._chunk_count += 1
        now = monotonic()
        if self._chunk_count % _CHUNK_YIELD_INTERVAL == 0:
            await asyncio.sleep(0)
            self._burst_start = now
        elif now - self._burst_start >= _CHUNK_YIELD_BUDGET_SEC:
            await asyncio.sleep(0)
            self._burst_start = now

        if force_flush or (now - self._last_flush_at) >= self._coalesce_interval_sec():
            flush_deferred_tools_refreshes(force=force_flush)
            self._last_flush_at = now

    async def flush_final(self) -> None:
        """Force pending tool UI updates at end of turn or interrupt."""
        flush_deferred_tools_refreshes(force=True)


__all__ = [
    "TurnToolUiCoalescer",
]

# ---------------------------------------------------------------------------
# Stream formatting
# ---------------------------------------------------------------------------


def _is_summarization_chunk(metadata: dict | None) -> bool:
    """Return True when metadata marks a summarization middleware chunk."""
    if metadata is None:
        return False
    return metadata.get("lc_source") == "summarization"


def print_usage_table(
    stats: SessionStats,
    wall_time: float,
    console: Any,
) -> None:
    """Print a model-usage stats table to a Rich console."""
    from rich.table import Table

    from soothe_cli.runtime.state.session_stats import format_token_count

    has_time = wall_time >= 0.1  # noqa: PLR2004
    if not (stats.request_count or stats.input_tokens or has_time):
        return

    if stats.per_model:
        multi_model = len(stats.per_model) > 1
        table = Table(
            show_header=True,
            header_style="bold",
            box=None,
            padding=(0, 2, 0, 0),
            show_edge=False,
        )
        table.add_column("Model", style="dim")
        table.add_column("Reqs", justify="right", style="dim")
        table.add_column("InputTok", justify="right", style="dim")
        table.add_column("OutputTok", justify="right", style="dim")

        if multi_model:
            for model_name, ms in stats.per_model.items():
                table.add_row(
                    model_name,
                    str(ms.request_count),
                    format_token_count(ms.input_tokens),
                    format_token_count(ms.output_tokens),
                )
            table.add_row(
                "Total",
                str(stats.request_count),
                format_token_count(stats.input_tokens),
                format_token_count(stats.output_tokens),
            )
        else:
            model_label = next(iter(stats.per_model))
            table.add_row(
                model_label,
                str(stats.request_count),
                format_token_count(stats.input_tokens),
                format_token_count(stats.output_tokens),
            )

        console.print()
        console.print("[bold]Usage Stats[/bold]")
        console.print(table)
    if has_time:
        console.print()
        console.print(
            f"Agent active  {format_duration(wall_time)}",
            style="dim",
            highlight=False,
        )


def canonical_subgraph_tool_ids(
    ns_key: tuple[str, ...],
    raw_tool_call_id: str,
    *,
    task_scope: TaskScope | None,
) -> tuple[str, str]:
    """Return ``(merge_lookup_id, row_key)`` for a subgraph tool invocation."""
    raw = str(raw_tool_call_id).strip()
    if not raw:
        return "", ""
    row_key = row_key_for_subgraph_tool(ns_key, raw, task_scope=task_scope)
    _, type_code, _, _ = parse_unified_tool_call_id(row_key)
    if type_code == "t":
        return row_key, row_key
    return raw, row_key


def alias_subgraph_pending_and_overlay(
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    streaming_overlay: dict[str, dict[str, Any]],
    router: Any,
    ns_key: tuple[str, ...],
) -> None:
    """Mirror provider tool-call ids under unified task-level ids when scope is bound."""
    ts = router.resolve_task_scope(ns_key)
    if ts is None:
        return
    for oid, pend in list(pending_tool_calls_lc.items()):
        if not isinstance(pend, dict):
            continue
        merge_id, _row = canonical_subgraph_tool_ids(ns_key, oid, task_scope=ts)
        if not merge_id or merge_id == oid:
            continue
        if merge_id not in pending_tool_calls_lc:
            pending_tool_calls_lc[merge_id] = dict(pend)
        oargs = streaming_overlay.get(oid)
        if isinstance(oargs, dict) and oargs:
            prev = streaming_overlay.get(merge_id)
            if isinstance(prev, dict) and prev:
                merged = dict(prev)
                merged.update(oargs)
                streaming_overlay[merge_id] = merged
            else:
                streaming_overlay[merge_id] = dict(oargs)


def _log_step_completion_stats(
    log: logging.Logger,
    step_id: str,
    widget: Any,
    success: bool,
    duration_ms: int,
    tool_call_count: int,
) -> None:
    """Compact step-completion trace (DEBUG only)."""
    rows = getattr(widget, "_rows", []) or []
    task_rows = sum(1 for r in rows if getattr(r, "is_task_row", False))
    log.debug(
        "[Step] %s done success=%s duration_ms=%d tools=%d rows=%d task=%d",
        step_id,
        success,
        duration_ms,
        tool_call_count,
        len(rows),
        task_rows,
    )


def _subagent_registry_key(step_id: str, task_idx: int) -> str:
    """Registry key for a SubAgent card (``{step}:t{n}``)."""
    return f"{step_id.strip()}:t{int(task_idx)}"


def _lookup_subagent_card(adapter: TextualUIAdapter, display_key: str) -> Any | None:
    """Return the SubAgent card for a unified task-level tool id, if registered."""
    parsed_sid, type_code, task_idx, _ = parse_unified_tool_call_id(str(display_key).strip())
    if not parsed_sid or type_code != "t" or task_idx is None:
        return None
    return adapter._subagent_cards_by_key.get(_subagent_registry_key(parsed_sid, task_idx))


def _lookup_subagent_card_for_task_scope(
    adapter: TextualUIAdapter,
    task_scope: TaskScope,
) -> Any | None:
    """Return the SubAgent card for a resolved task namespace binding."""
    step_id = task_scope_step_id(task_scope)
    if not step_id:
        return None
    task_idx = task_scope_task_idx(task_scope, step_id)
    return adapter._subagent_cards_by_key.get(_subagent_registry_key(step_id, task_idx))


def _register_execute_namespace_binding(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    ns_key: tuple[str, ...],
    *,
    step_id: str = "",
) -> None:
    """Bind an execute namespace to its step card for later lookups.

    Custom loop events (step_started, step_completed) carry the root namespace
    ``()`` and register the step card under ``_step_by_namespace[()]``. But LLM
    message chunks — including ``usage_metadata`` for token accounting — arrive
    under the actual execute namespace (e.g. ``("execute:{thread_id}",)`` or a
    parallel branch ``("execute:{thread_id}", "N")``). Without binding, the
    namespace lookup in ``_resolve_token_target_card`` misses for parallel
    waves where the single-active-step fallback cannot disambiguate.

    Called when a step-scope tool call or message is first seen for an execute
    namespace so subsequent token-usage chunks resolve correctly.
    """
    if not ns_key or not is_step_card_tool_scope(ns_key=ns_key):
        return
    if adapter._step_by_namespace.get(ns_key) is not None:
        return  # already bound
    sid = str(step_id or "").strip()
    if sid:
        step_w = adapter._current_step_messages.get(sid)
        if step_w is not None:
            adapter._step_by_namespace[ns_key] = step_w
            return
    # Single active step: infer the binding
    if len(router.active_step_ids) == 1:
        only_sid = next(iter(router.active_step_ids))
        step_w = adapter._current_step_messages.get(only_sid)
        if step_w is not None:
            adapter._step_by_namespace[ns_key] = step_w


def _resolve_token_target_card(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    ns_key: tuple[str, ...],
    *,
    message: Any = None,
) -> Any | None:
    """Resolve step or SubAgent card for per-card token accounting.

    Main execute namespaces update the step card. Subgraph/task namespaces update
    the SubAgent card only so step totals exclude nested delegation usage.
    """
    if is_step_card_tool_scope(ns_key=ns_key):
        step_w = adapter._step_by_namespace.get(ns_key)
        if step_w is not None:
            return step_w
        # Try to infer step_id from tool_calls on the message (parallel waves)
        if message is not None:
            tool_calls = getattr(message, "tool_calls", None) or []
            for tc in tool_calls:
                # Tool calls can be dicts (LangChain) or objects
                tcid = ""
                if isinstance(tc, dict):
                    tcid = str(tc.get("id", "") or "").strip()
                else:
                    tcid = str(getattr(tc, "id", "") or "").strip()
                if tcid:
                    parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
                    if parsed_sid:
                        step_w = adapter._current_step_messages.get(parsed_sid)
                        if step_w is not None:
                            adapter._step_by_namespace[ns_key] = step_w
                            return step_w
        if len(router.active_step_ids) == 1:
            only_sid = next(iter(router.active_step_ids))
            return adapter._current_step_messages.get(only_sid)
        return None
    task_scope = router.resolve_task_scope(ns_key)
    if task_scope is None:
        return None
    return _lookup_subagent_card_for_task_scope(adapter, task_scope)


def _ingest_tool_on_subagent_card(
    adapter: TextualUIAdapter,
    subagent_card: Any,
    *,
    display_key: str,
    tool_name: str,
    args: dict[str, Any],
    raw_args: str = "",
) -> None:
    """Register or update one tool row on a SubAgent card."""
    row_id = str(display_key).strip()
    resolved_args = dict(args or {})
    if raw_args and not extract_tool_args_dict(resolved_args):
        parsed = extract_tool_args_dict({"_raw": raw_args})
        if parsed:
            resolved_args = parsed
    if subagent_card.has_tool_call_row(row_id):
        subagent_card.update_tool_args(row_id, resolved_args)
    else:
        subagent_card.add_tool_call(row_id, tool_name, resolved_args, raw_args=raw_args)
    adapter._tool_to_step[row_id] = subagent_card


async def _mount_subagent_card_if_needed(
    adapter: TextualUIAdapter,
    subagent_card: Any | None,
) -> None:
    """Mount a newly created SubAgent card when not already on the message list."""
    if subagent_card is None or getattr(subagent_card, "is_mounted", False):
        return
    mount_result = adapter._mount_message(subagent_card)
    if mount_result is not None:
        await mount_result


def _rehome_subgraph_rows_to_subagent(
    adapter: TextualUIAdapter,
    step_widget: Any,
    subagent_card: Any,
    task_idx: int,
) -> None:
    """Move subgraph tool rows from the step card onto the SubAgent card (RFC-628)."""
    kept: list[Any] = []
    moved = False
    for row in step_widget._rows:
        _, type_code, idx, _ = parse_unified_tool_call_id(str(row.tool_call_id).strip())
        if type_code == "t" and idx == task_idx:
            moved = True
            row_args = dict(row.args or {})
            raw_args = str(row_args.pop("_raw", "") or "").strip()
            _ingest_tool_on_subagent_card(
                adapter,
                subagent_card,
                display_key=str(row.tool_call_id),
                tool_name=str(row.tool_name or "tool"),
                args=row_args,
                raw_args=raw_args,
            )
            if row.phase not in ("pending",):
                phase = str(row.phase or "pending")
                if phase == "success":
                    subagent_card.set_tool_success(
                        str(row.tool_call_id),
                        str(row.output or ""),
                        duration_ms=int(row.duration_ms or 0),
                    )
                elif phase in ("error", "rejected", "failed"):
                    subagent_card.set_tool_error(
                        str(row.tool_call_id),
                        str(row.output or "Error"),
                        duration_ms=int(row.duration_ms or 0),
                    )
                elif phase == "running":
                    subagent_card.set_tool_running(str(row.tool_call_id))
        else:
            kept.append(row)
    if moved:
        step_widget._rows = kept
        step_widget._sync_step_card_surface()


def _subagent_card_tool_count(card: Any) -> int:
    """Return tracked tool count for a SubAgent card."""
    build_index = getattr(card, "_build_row_index", None)
    if callable(build_index):
        return int(build_index().total_tool_count)
    rows = getattr(card, "_rows", None)
    return len(rows) if isinstance(rows, list) else 0


def _complete_subagent_card(
    adapter: TextualUIAdapter,
    subagent_card: Any,
    *,
    success: bool,
    duration_ms: int,
    summary: str,
) -> None:
    """Finalize one SubAgent card and sync its task row on the parent step."""
    if getattr(subagent_card, "_status", "") in ("success", "error"):
        return
    start = getattr(subagent_card, "_start_time", None)
    dur = duration_ms
    if dur <= 0 and start is not None:
        dur = int((time.time() - start) * 1000)
    tool_count = _subagent_card_tool_count(subagent_card)
    subagent_card.set_complete(success, dur, tool_count, summary)
    parent_step_id = str(getattr(subagent_card, "_parent_step_id", "") or "").strip()
    parent_step = adapter._current_step_messages.get(parent_step_id)
    sync_fn = getattr(subagent_card, "sync_status_to_step", None)
    if callable(sync_fn) and parent_step is not None:
        sync_fn(parent_step, success)


def _finalize_subagent_cards_for_step(
    adapter: TextualUIAdapter,
    step_id: str,
    *,
    success: bool,
    duration_ms: int = 0,
    summary: str = "Done",
) -> None:
    """Complete all SubAgent cards delegated from one execute step."""
    sid = str(step_id or "").strip()
    if not sid:
        return
    keys_done: list[str] = []
    for key, card in list(adapter._subagent_cards_by_key.items()):
        parent = str(getattr(card, "_parent_step_id", "") or "").strip()
        if parent != sid:
            continue
        _complete_subagent_card(
            adapter,
            card,
            success=success,
            duration_ms=duration_ms,
            summary=summary,
        )
        keys_done.append(key)
    for key in keys_done:
        adapter._subagent_cards_by_key.pop(key, None)


def _ensure_subagent_card_for_task_scope(
    adapter: TextualUIAdapter,
    task_scope: TaskScope,
) -> Any | None:
    """Return the SubAgent card for ``task_scope``, creating it when needed."""
    card = _lookup_subagent_card_for_task_scope(adapter, task_scope)
    if card is not None:
        return card
    step_id = task_scope_step_id(task_scope)
    step_w = adapter._current_step_messages.get(step_id)
    if step_w is None:
        return None
    task_tcid = str(task_scope[0] or "").strip()
    task_args: dict[str, Any] = {}
    subagent_type = str(task_scope[1] or "").strip()
    for row in getattr(step_w, "_rows", []) or []:
        tcid = str(getattr(row, "tool_call_id", "") or "").strip()
        if tcid == task_tcid or getattr(row, "is_task_row", False):
            task_args = dict(getattr(row, "args", None) or {})
            if task_args or tcid == task_tcid:
                break
    if not task_args and subagent_type:
        task_args = {"subagent_type": subagent_type}
    _ensure_subagent_card_for_task_row(adapter, step_w, task_tcid, task_args)
    return _lookup_subagent_card_for_task_scope(adapter, task_scope)


def _wire_step_row_id(step_id: str, task_idx: int, tool_name: str, seq: int) -> str:
    """Unified subgraph id for a synthetic subagent progress row."""
    wire_frag = str(step_id).strip().replace("-", "_")
    slug = str(tool_name or "step").strip().lower().replace(" ", "_") or "step"
    return f"{wire_frag}:t{task_idx}:{slug}:{seq}"


def _ingest_wire_step_on_subagent_card(
    adapter: TextualUIAdapter,
    subagent_card: Any,
    *,
    step_id: str,
    task_idx: int,
    tool_name: str,
    args: dict[str, Any],
    phase: str,
    duration_ms: int,
) -> None:
    """Register one curated wire step as a tool-like row on the SubAgent card."""
    seq = int(getattr(subagent_card, "_wire_step_seq", 0) or 0)
    subagent_card._wire_step_seq = seq + 1  # type: ignore[attr-defined]
    row_id = _wire_step_row_id(step_id, task_idx, tool_name, seq)
    _ingest_tool_on_subagent_card(
        adapter,
        subagent_card,
        display_key=row_id,
        tool_name=tool_name,
        args=dict(args or {}),
    )
    if phase == "running":
        subagent_card.set_tool_running(row_id)
    elif phase in ("error", "rejected", "failed"):
        subagent_card.set_tool_error(row_id, "Failed", duration_ms=duration_ms)
    else:
        subagent_card.set_tool_success(row_id, "", duration_ms=duration_ms)


def _subagent_wire_step_params(
    event_type: str,
    data: dict[str, Any],
) -> tuple[str, dict[str, Any], str, int] | None:
    """Map curated subagent wire events to SubAgent card row fields."""
    et = str(event_type or "").strip()
    if et.endswith(".gather.summary"):
        query = str(data.get("query_preview", "") or "").strip()
        rc = int(data.get("result_count", 0) or 0)
        st = int(data.get("sources_touched", 0) or 0)
        preview = query
        if rc or st:
            tail = f"{rc} hits, {st} sources"
            preview = f"{query} → {tail}" if query else tail
        return "WebSearch", {"query": preview or query}, "success", 0
    if et.endswith(".step.completed"):
        tool_name = str(data.get("tool_name", "") or "").strip() or "Step"
        args_preview = str(data.get("args_preview", "") or "").strip()
        status = str(data.get("status", "done") or "done").strip().lower()
        phase = "success" if status in ("done", "success", "complete") else "running"
        if status in ("error", "failed"):
            phase = "error"
        duration_ms = int(data.get("duration_ms", 0) or 0)
        args = {"preview": args_preview} if args_preview else {}
        return tool_name, args, phase, duration_ms
    return None


def _apply_subagent_wire_step_event(
    adapter: TextualUIAdapter,
    *,
    event_type: str,
    data: dict[str, Any],
    task_scope: TaskScope,
) -> bool:
    """Render ``*.step.completed`` / ``*.gather.summary`` on the SubAgent (TASK) card."""
    params = _subagent_wire_step_params(event_type, data)
    if params is None:
        return False
    tool_name, args, phase, duration_ms = params
    step_id = task_scope_step_id(task_scope)
    if not step_id:
        return True
    task_idx = task_scope_task_idx(task_scope, step_id)
    subagent_card = _ensure_subagent_card_for_task_scope(adapter, task_scope)
    if subagent_card is None:
        return True
    _ingest_wire_step_on_subagent_card(
        adapter,
        subagent_card,
        step_id=step_id,
        task_idx=task_idx,
        tool_name=tool_name,
        args=args,
        phase=phase,
        duration_ms=duration_ms,
    )
    return True


def _apply_subagent_wire_lifecycle_event(
    adapter: TextualUIAdapter,
    *,
    event_type: str,
    data: dict[str, Any],
    task_scope: TaskScope,
) -> bool:
    """Handle subagent ``*.completed`` / ``*.failed`` wire events (RFC-628, IG-513)."""
    et = str(event_type or "").strip()
    if not (et.endswith(".completed") or et.endswith(".failed")):
        return True
    step_id = task_scope_step_id(task_scope)
    task_idx = task_scope_task_idx(task_scope, step_id)
    card = adapter._subagent_cards_by_key.get(_subagent_registry_key(step_id, task_idx))
    if card is None:
        return True
    if et.endswith(".failed"):
        success = False
        summary = str(data.get("failure_reason") or data.get("error") or "Failed").strip()
    else:
        status = str(data.get("completion_status") or "complete").strip().lower()
        success = status not in ("failed", "error", "cancelled")
        summary = str(data.get("summary") or data.get("failure_reason") or "Done").strip()
    if not summary:
        summary = "Done" if success else "Failed"
    duration_ms = int(data.get("duration_ms", 0) or 0)
    _complete_subagent_card(
        adapter,
        card,
        success=success,
        duration_ms=duration_ms,
        summary=summary,
    )
    adapter._subagent_cards_by_key.pop(_subagent_registry_key(step_id, task_idx), None)
    return True


def _route_subgraph_tool_call(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    ns_key: tuple[str, ...],
    lookup_id: str,
    display_key: str,
    tool_name: str,
    args: dict[str, Any],
    raw_args: str = "",
) -> bool:
    """Route a subgraph tool to its SubAgent card, or buffer on the step card."""
    display = str(display_key or lookup_id).strip()
    subagent_card = _lookup_subagent_card(adapter, display)
    if subagent_card is not None:
        _ingest_tool_on_subagent_card(
            adapter,
            subagent_card,
            display_key=display,
            tool_name=tool_name,
            args=args,
            raw_args=raw_args,
        )
        router.discard_pending_subgraph_tool(ns_key, str(lookup_id).strip())
        return True
    routed = router.try_route_subgraph_tool(
        ns_key=ns_key,
        lookup_id=str(lookup_id).strip(),
        display_key=display,
        tool_name=tool_name,
        args=args,
        raw_args=raw_args,
        step_cards=adapter._current_step_messages,
        tool_to_step=adapter._tool_to_step,
        tool_display_by_call_id=adapter._tool_display_by_call_id,
    )
    if routed:
        return True
    return _fallback_ingest_subgraph_tool_on_step_card(
        adapter,
        router,
        lookup_id=str(lookup_id),
        display_key=display,
        tool_name=tool_name,
        args=args,
        raw_args=raw_args,
        ns_key=ns_key,
    )


def _route_pending_subgraph_tools(adapter: TextualUIAdapter, router: StepTaskRouter) -> int:
    """Flush buffered subgraph tools, preferring SubAgent cards when registered."""
    pending = router.pending_subgraph_tools()
    routed = 0
    for item in pending:
        if _route_subgraph_tool_call(
            adapter,
            router,
            ns_key=item.ns_key,
            lookup_id=item.lookup_id,
            display_key=item.display_key,
            tool_name=item.tool_name,
            args=item.args,
            raw_args=item.raw_args,
        ):
            routed += 1
    return routed


def _ingest_main_task_tool_on_step_card(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    tool_call_id: str,
    display_args: dict[str, Any],
    *,
    bound_step_id: str,
) -> Any | None:
    """Register a main-graph ``task`` delegation on the step card and prepare SubAgent card.

    IG-513: Creates a SubAgent card for each task delegation. The caller must mount
    the returned card asynchronously. Inner subgraph tools route to the SubAgent card
    via `_subagent_cards_by_key`.

    Returns:
        SubAgentMessage widget if newly created, None otherwise (caller must mount async).
    """
    tcid = str(tool_call_id).strip()
    sid = str(bound_step_id).strip()
    if not tcid or is_inner_subgraph_task_tool_id(tcid):
        return None
    raw_st = display_args.get("subagent_type", "")
    subagent_type = raw_st.strip() if isinstance(raw_st, str) else ""
    if subagent_type:
        router.register_task_spawn(tcid, subagent_type, step_id=sid)
    if not sid:
        _route_pending_subgraph_tools(adapter, router)
        return None
    norm_tcid = normalize_main_task_delegation_id(sid, tcid, tool_name="task")
    step_w = _resolve_step_widget_for_tool(
        adapter,
        router,
        bound_step_id=sid,
        ns_key=(),
    )
    subagent_card_to_mount = None
    if step_w is not None:
        # IG-515: _register_main_tool_on_step_card now returns SubAgent card for task rows
        subagent_card_to_mount = _register_main_tool_on_step_card(
            adapter,
            router,
            step_w,
            norm_tcid,
            "task",
            display_args,
            is_task_row=True,
        )
        adapter._tool_display_by_call_id[norm_tcid] = step_w

    _route_pending_subgraph_tools(adapter, router)
    return subagent_card_to_mount


def _ensure_subagent_card_for_task_row(
    adapter: TextualUIAdapter,
    step_w: CognitionStepMessage,
    task_tcid: str,
    task_args: dict[str, Any],
) -> Any | None:
    """Create SubAgent card for a task row if not already registered (IG-515 fix).

    Called when buffered task tools are routed to a newly-created step card.
    Returns the SubAgent card if newly created, None if already exists.

    Args:
        adapter: TextualUIAdapter with `_subagent_cards_by_key` registry.
        step_w: Step card that owns the task row.
        task_tcid: Normalized tool_call_id for the task delegation.
        task_args: Args dict with subagent_type and description/prompt.

    Returns:
        SubAgentMessage widget if newly created, None otherwise.
    """
    sid = str(getattr(step_w, "_step_id", "") or "").strip()
    if not sid:
        return None
    _, _, _, tool_info = parse_unified_tool_call_id(task_tcid)
    task_idx = 0
    if tool_info and ":" in tool_info:
        tail = tool_info.split(":")[-1]
        if tail.isdigit():
            task_idx = int(tail)
    subagent_key = f"{sid}:t{task_idx}"
    if subagent_key in adapter._subagent_cards_by_key:
        return None
    raw_st = task_args.get("subagent_type", "")
    subagent_type = raw_st.strip() if isinstance(raw_st, str) else ""
    desc = str(task_args.get("description") or task_args.get("prompt") or "").strip()
    subagent_card = create_subagent_card(
        step_id=sid,
        description=desc or f"{subagent_type} task",
        subagent_type=subagent_type or "Task",
        parent_step_id=sid,
        parent_task_key=task_tcid,
        task_idx=task_idx,
        id=f"subagent-{uuid.uuid4().hex[:8]}",
    )
    adapter._subagent_cards_by_key[subagent_key] = subagent_card
    _rehome_subgraph_rows_to_subagent(adapter, step_w, subagent_card, task_idx)
    return subagent_card


def _create_subagent_cards_for_step_tasks(
    adapter: TextualUIAdapter,
    step_w: CognitionStepMessage,
) -> list[Any]:
    """Create SubAgent cards for all task rows on a step card (IG-515 fix).

    Called after routing buffered main tools to a newly-mounted step card.
    Returns list of newly-created SubAgent cards that need async mounting.

    Args:
        adapter: TextualUIAdapter with `_subagent_cards_by_key` registry.
        step_w: Step card with potential task delegation rows.

    Returns:
        List of newly-created SubAgentMessage widgets to mount.
    """
    cards_to_mount: list[Any] = []
    rows = getattr(step_w, "_rows", []) or []
    for row in rows:
        if not getattr(row, "is_task_row", False):
            continue
        tcid = str(row.tool_call_id or "").strip()
        if not tcid:
            continue
        args = dict(row.args or {})
        subagent_card = _ensure_subagent_card_for_task_row(adapter, step_w, tcid, args)
        if subagent_card is not None:
            cards_to_mount.append(subagent_card)
    return cards_to_mount


def _register_main_tool_on_step_card(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    step_w: CognitionStepMessage,
    tool_call_id: str,
    tool_name: str,
    args: dict[str, Any],
    *,
    raw_args: str = "",
    is_task_row: bool = False,
) -> Any | None:
    """Register a main-graph tool row and promote the step card when authorized (RFC-628).

    For task delegations (is_task_row=True and tool_name=='task'), also ensures
    a SubAgent card exists via `_ensure_subagent_card_for_task_row`.

    Returns:
        SubAgentMessage widget if newly created for a task row, None otherwise.
    """
    tcid = str(tool_call_id).strip()
    # IG-517: Ensure subagent_type is present in args for task delegations.
    # The router records this via register_task_spawn, but streaming args
    # may arrive incomplete. Inject from router registry when missing.
    if is_task_row and tool_name == "task":
        existing_type = args.get("subagent_type")
        if not existing_type or not str(existing_type).strip():
            spawn_scope = router._spawns_by_task_id.get(tcid)
            if spawn_scope is not None and len(spawn_scope) >= 2:
                args["subagent_type"] = str(spawn_scope[1] or "").strip()
    if step_w.has_tool_call_row(tcid):
        step_w.update_tool_args(tcid, args)
    else:
        step_w.add_tool_call(
            tcid,
            tool_name,
            args,
            raw_args=raw_args,
            is_task_row=is_task_row,
        )
    router.maybe_promote_step_to_running(
        step_w,
        tcid,
        step_cards=adapter._current_step_messages,
    )
    adapter._tool_to_step[tcid] = step_w

    # IG-515: For task delegations, ensure SubAgent card exists
    if is_task_row and tool_name == "task":
        return _ensure_subagent_card_for_task_row(adapter, step_w, tcid, args)
    return None


def _resolve_step_widget_for_tool(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    bound_step_id: str,
    ns_key: tuple[str, ...],
) -> CognitionStepMessage | None:
    """Resolve the step card that should own main-namespace tool stats."""
    sid = str(bound_step_id or "").strip()
    if sid:
        step_w = adapter._current_step_messages.get(sid)
        if step_w is not None:
            return step_w
    step_w = adapter._step_by_namespace.get(ns_key)
    if step_w is not None:
        return step_w
    if len(router.active_step_ids) == 1 and not sid:
        only_sid = next(iter(router.active_step_ids))
        return adapter._current_step_messages.get(only_sid)
    return None


def _fallback_ingest_subgraph_tool_on_step_card(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    lookup_id: str,
    display_key: str,
    tool_name: str,
    args: dict[str, Any],
    raw_args: str = "",
    ns_key: tuple[str, ...],
) -> bool:
    """Best-effort fallback when namespace routing cannot resolve a parent task.

    This keeps subgraph tool activity visible on the step card until a SubAgent
    card is registered, instead of dropping it when task binding arrives late.
    """
    lookup = str(lookup_id or "").strip()
    display = str(display_key or "").strip()
    if not lookup:
        return False
    if is_inner_subgraph_task_tool_id(lookup):
        return False
    parsed_sid, type_code, _, _ = parse_unified_tool_call_id(lookup)
    bound_step_id = parsed_sid or router.step_id_for_tool(lookup)
    step_w = _resolve_step_widget_for_tool(
        adapter,
        router,
        bound_step_id=bound_step_id,
        ns_key=ns_key,
    )
    if step_w is None:
        return False
    row_id = lookup if type_code == "t" else (display or lookup)
    resolved_args = dict(args or {})
    # Placeholder args like {"_subgraph_tool": true} are not meaningful.
    # Parse raw_args when resolved_args lacks real invocation kwargs.
    meaningful_args = extract_tool_args_dict(resolved_args)
    if raw_args and not meaningful_args:
        parsed = extract_tool_args_dict({"_raw": raw_args})
        if parsed:
            resolved_args = parsed
    _register_main_tool_on_step_card(
        adapter,
        router,
        step_w,
        row_id,
        tool_name,
        resolved_args,
        raw_args=raw_args,
    )
    adapter._tool_display_by_call_id[row_id] = step_w
    return True


def _sync_goal_tree_step_phase(
    adapter: TextualUIAdapter,
    step_id: str,
    phase: str,
    *,
    description: str = "",
) -> None:
    """Update the live goal tree row for a step lifecycle transition."""
    tree = adapter._goal_tree_message
    if tree is None:
        return
    tree.set_step_phase(step_id, phase, description=description or None)


async def _ensure_goal_tree_message(
    adapter: TextualUIAdapter,
    *,
    goal: str = "",
    max_iterations: int = 0,
) -> CognitionGoalTreeMessage:
    """Create or refresh in-memory goal tree state for the plan quick view."""
    tree = adapter._goal_tree_message
    if tree is not None:
        if goal.strip():
            tree._goal_text = goal.strip()
        if max_iterations > 0:
            tree._max_iterations = max_iterations
        return tree
    widget = CognitionGoalTreeMessage(
        goal=goal.strip() or "Goal",
        max_iterations=max_iterations,
        id=f"goal-tree-{uuid.uuid4().hex[:8]}",
    )
    adapter._goal_tree_message = widget
    return widget


async def sync_pending_step_cards_from_plan(
    adapter: TextualUIAdapter,
    *,
    steps: list[dict[str, Any]],
) -> None:
    """Mount step cards in ``pending`` state for planned steps not yet executing."""
    planned_ids = {
        str(row.get("id", "")).strip()
        for row in steps
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }
    for sid, widget in list(adapter._current_step_messages.items()):
        if widget._status == "pending" and sid not in planned_ids:
            if widget.is_mounted:
                await widget.remove()
            adapter._current_step_messages.pop(sid, None)
            for ns, bound in list(adapter._step_by_namespace.items()):
                if bound is widget:
                    adapter._step_by_namespace.pop(ns, None)

    for row in steps:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id", "")).strip()
        if not sid or sid in adapter._current_step_messages:
            continue
        if _is_successful_step_id(adapter, sid):
            continue
        desc = str(row.get("description", "")).strip() or "(step)"
        step_widget = CognitionStepMessage(
            step_id=sid,
            description=desc,
            id=f"step-{uuid.uuid4().hex[:8]}",
        )
        await adapter._mount_message(step_widget)
        adapter._current_step_messages[sid] = step_widget


def _step_card_lookup_keys(step_id: str) -> list[str]:
    """Return dict lookup keys for a step id (canonical and wire variants)."""
    sid = str(step_id or "").strip()
    if not sid:
        return []
    keys = [sid]
    wire = sid.replace("-", "_")
    if wire not in keys:
        keys.append(wire)
    dash = sid.replace("_", "-")
    if dash not in keys:
        keys.append(dash)
    return keys


def _register_successful_step_id(adapter: TextualUIAdapter, step_id: str) -> None:
    """Remember a step that completed successfully so plan=keep does not remount it."""
    for key in _step_card_lookup_keys(step_id):
        adapter._successful_step_ids.add(key)


def _is_successful_step_id(adapter: TextualUIAdapter, step_id: str) -> bool:
    """True when this step already succeeded earlier in the current loop."""
    return any(key in adapter._successful_step_ids for key in _step_card_lookup_keys(step_id))


def _lookup_step_card(
    adapter: TextualUIAdapter,
    step_id: str,
) -> tuple[str, CognitionStepMessage | None]:
    """Resolve a tracked step card by registry key or widget ``_step_id``."""
    for key in _step_card_lookup_keys(step_id):
        widget = adapter._current_step_messages.get(key)
        if widget is not None:
            return key, widget
    target = str(step_id or "").strip()
    for key, widget in adapter._current_step_messages.items():
        if str(getattr(widget, "_step_id", "") or "").strip() == target:
            return key, widget
    return "", None


def _pop_step_card_from_adapter(
    adapter: TextualUIAdapter,
    step_id: str,
) -> CognitionStepMessage | None:
    """Remove and return the step card for ``step_id``, trying alias keys."""
    dict_key, widget = _lookup_step_card(adapter, step_id)
    if widget is None:
        return None
    adapter._current_step_messages.pop(dict_key, None)
    for key in _step_card_lookup_keys(step_id):
        adapter._current_step_messages.pop(key, None)
    return widget


def _record_plan_step_dag(adapter: TextualUIAdapter, raw_steps: list[Any]) -> None:
    """Capture in-wave step order and dependency edges from ``plan_decision``."""
    order: list[str] = []
    dep_map: dict[str, tuple[str, ...]] = {}
    in_plan: set[str] = set()
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id", "")).strip()
        if not sid:
            continue
        order.append(sid)
        in_plan.add(sid)
        raw_deps = raw.get("dependencies")
        if isinstance(raw_deps, list):
            dep_map[sid] = tuple(str(dep).strip() for dep in raw_deps if str(dep).strip())
    adapter._plan_step_order = order
    adapter._plan_step_ids = in_plan
    adapter._plan_step_dependencies = dep_map


def _dependency_stuck_predecessor_ids(
    adapter: TextualUIAdapter,
    next_step_id: str,
) -> set[str]:
    """Return in-plan predecessors that may be finalized when ``next_step_id`` starts."""
    next_id = str(next_step_id or "").strip()
    if not next_id:
        return set()

    in_plan = set(adapter._plan_step_ids)
    if next_id in adapter._plan_step_dependencies:
        declared = adapter._plan_step_dependencies[next_id]
        if declared:
            return {dep for dep in declared if dep in in_plan}

    if adapter._last_plan_execution_mode != "dependency":
        return set()

    order = adapter._plan_step_order
    try:
        idx = order.index(next_id)
    except ValueError:
        return set()
    if idx <= 0:
        return set()
    predecessor = order[idx - 1]
    if predecessor in in_plan:
        return {predecessor}
    return set()


def _finalize_stuck_dependency_predecessors(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    next_step_id: str,
    ns_key: tuple[Any, ...],
) -> None:
    """Finalize predecessor cards still ``running`` when a dependent step starts."""
    if adapter._last_plan_execution_mode != "dependency":
        return
    next_id = str(next_step_id or "").strip()
    if not next_id:
        return
    stuck_predecessors = _dependency_stuck_predecessor_ids(adapter, next_id)
    if not stuck_predecessors:
        return
    for sid, widget in list(adapter._current_step_messages.items()):
        card_id = str(getattr(widget, "_step_id", "") or sid).strip()
        if card_id == next_id:
            continue
        if card_id not in stuck_predecessors:
            continue
        if getattr(widget, "_status", "") != "running":
            continue
        logger.warning(
            "Dependency step %s started while %s still running in UI; finalizing predecessor",
            next_id,
            card_id,
        )
        router.on_step_completed(card_id)
        adapter._current_step_messages.pop(sid, None)
        complete_tracked_step_card(
            adapter,
            router,
            step_id=card_id,
            widget=widget,
            ns_key=ns_key,
            success=True,
            duration_ms=0,
            tool_call_count=_step_card_tool_count(widget),
            summary="Done",
        )


# ---------------------------------------------------------------------------
# Stream messages
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def _normalize_lc_stream_message(message: Any) -> Any:
    """Turn daemon JSON dicts into LangChain message objects when possible."""
    if not isinstance(message, dict):
        return message
    try:
        from soothe_sdk.langchain_wire import deserialize_langchain_message_from_wire

        restored = deserialize_langchain_message_from_wire(message)
        if restored is not message:
            return restored
    except Exception:
        logger.debug("TUI could not restore LangChain message from dict", exc_info=True)
    return message


def _coerce_ai_message_for_blocks(message: Any) -> Any:
    """Best-effort dict → ``AIMessage`` / ``AIMessageChunk`` for block extraction.

    If the wire payload uses ``type: \"AIMessage\"`` (class name) instead of ``ai``,
    :func:`messages_from_dict` would fail; :func:`envelope_langchain_message_dict`
    canonicalizes first (see ``daemon_session``).
    """
    from langchain_core.messages import AIMessageChunk

    if isinstance(message, (AIMessage, AIMessageChunk)):
        return message
    if not isinstance(message, dict):
        return message
    try:
        restored = messages_from_wire_dicts([message])
        if restored and isinstance(restored[0], (AIMessage, AIMessageChunk)):
            return restored[0]
    except Exception:
        logger.debug("TUI could not coerce dict to AIMessage for blocks", exc_info=True)
    return message


def _expand_nonstandard_tool_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map LangChain ``non_standard`` tool wrappers to plain ``tool_call`` blocks.

    Anthropic-style ``tool_use`` content is often stored as
    ``{\"type\": \"non_standard\", \"value\": {\"type\": \"tool_use\", ...}}``.
    The TUI loop only understands ``tool_call`` / ``tool_call_chunk`` — without this,
    tool cards never mount for Claude/Anthropic providers.
    """
    out: list[dict[str, Any]] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") != "non_standard":
            out.append(b)
            continue
        val = b.get("value")
        if not isinstance(val, dict):
            out.append(b)
            continue
        inner_t = val.get("type")
        if inner_t == "tool_use":
            out.append(
                {
                    "type": "tool_call",
                    "name": val.get("name"),
                    "id": val.get("id"),
                    "args": val.get("input") if val.get("input") is not None else {},
                }
            )
            continue
        if inner_t in ("tool_call", "tool_call_chunk"):
            out.append(
                {
                    "type": inner_t,
                    "name": val.get("name"),
                    "id": val.get("id"),
                    "args": val.get("args"),
                    "index": val.get("index"),
                }
            )
            continue
        out.append(b)
    return out


def _tui_main_assistant_body_for_dedupe(raw: str) -> str:
    """Normalize assistant text the same way as :func:`_flush_assistant_text_ns` input."""
    return format_subagent_task_assistant_for_display(
        RendererBase.repair_concatenated_output(raw or ""),
    ).strip()


def _tui_goal_completion_matches_prior_main_visible_answer(
    adapter: TextualUIAdapter,
    *,
    ns_key: tuple[Any, ...],
    output_text: str,
    pending_execute_text: str = "",
) -> bool:
    """Return True when ``goal_completion`` duplicates an already-shown main answer.

    Covers (1) ``execute_step`` prose on ``CognitionStepMessage``, (2) prose last flushed to a
    standalone ``AssistantMessage``, and (3) prose still in ``pending_text_by_namespace`` that
    was already streamed into an ``AssistantMessage`` via ``append_content`` but not yet
    flushed (``goal_completion`` can arrive before the stream terminal frame or end-of-turn
    flush — common for direct daemon runs; subagent routing often interleaves flushes differently).
    """
    if ns_key != ():
        return False
    body = _tui_main_assistant_body_for_dedupe(output_text)
    if not body:
        return False
    priors = [
        _tui_main_assistant_body_for_dedupe(adapter._last_completed_main_step_execute_prose),
        _tui_main_assistant_body_for_dedupe(adapter._last_main_flushed_assistant_prose),
        _tui_main_assistant_body_for_dedupe(pending_execute_text),
    ]
    priors = [p for p in priors if p]
    if not priors:
        return False
    # Never suppress a full synthesis report when only a shorter preview was shown.
    if len(body) > max(len(p) for p in priors):
        return False
    return any(body == p for p in priors)


def _tui_effective_ai_blocks(
    message: Any,
    *,
    ns_key: tuple[Any, ...],
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build content blocks for TUI streaming (text + tool calls).

    Tool kwargs are merged in
    :func:`soothe_cli.shared.tool_call_resolution.materialize_ai_blocks_with_resolved_tools`.
    """
    from langchain_core.messages import AIMessageChunk

    message = _coerce_ai_message_for_blocks(message)
    if not isinstance(message, (AIMessage, AIMessageChunk)):
        return []

    # Root namespace: allow string fallback. Subgraphs: suppress plain string (avoid dup with main).
    allow_plain_string = not ns_key
    raw_blocks = getattr(message, "content_blocks", None)
    blocks: list[dict[str, Any]] = []
    if raw_blocks:
        blocks = _expand_nonstandard_tool_blocks([b for b in raw_blocks if isinstance(b, dict)])
        return materialize_ai_blocks_with_resolved_tools(
            blocks, message, streaming_overlay=streaming_overlay
        )

    raw = getattr(message, "content", None)
    if not allow_plain_string:
        if isinstance(raw, list):
            toolish = [
                b
                for b in raw
                if isinstance(b, dict)
                and b.get("type") in ("tool_call", "tool_call_chunk", "tool_use", "non_standard")
            ]
            if toolish:
                expanded = _expand_nonstandard_tool_blocks(toolish)
                return materialize_ai_blocks_with_resolved_tools(
                    expanded, message, streaming_overlay=streaming_overlay
                )
        return materialize_ai_blocks_with_resolved_tools(
            [], message, streaming_overlay=streaming_overlay
        )
    if isinstance(raw, str) and raw.strip():
        merged = [{"type": "text", "text": raw}]
        return materialize_ai_blocks_with_resolved_tools(
            merged, message, streaming_overlay=streaming_overlay
        )
    if isinstance(raw, list):
        part = _expand_nonstandard_tool_blocks([b for b in raw if isinstance(b, dict)])
        if not part:
            return materialize_ai_blocks_with_resolved_tools(
                [], message, streaming_overlay=streaming_overlay
            )
        return materialize_ai_blocks_with_resolved_tools(
            part, message, streaming_overlay=streaming_overlay
        )
    return materialize_ai_blocks_with_resolved_tools(
        [], message, streaming_overlay=streaming_overlay
    )


# ---------------------------------------------------------------------------
# Stream tool wire
# ---------------------------------------------------------------------------


async def apply_tool_call_wire_update(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    data: dict[str, Any],
    ns_key: tuple[str, ...],
    pending_tool_calls_lc: dict[str, dict[str, Any]],
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
    ui_coalesce: TurnToolUiCoalescer | None = None,
    file_op_tracker: FileOpTracker | None = None,
) -> bool:
    """Seed pending tool state from a wire tool-call update event (no tool-card UI)."""
    if str(data.get("type", "")) != STREAM_TOOL_CALL_UPDATE:
        return False

    if ns_key and not is_step_card_tool_scope(ns_key=ns_key):
        router.on_subgraph_namespace(ns_key)

    tcid = str(data.get("tool_call_id", "")).strip()
    if not tcid:
        return True

    name = str(data.get("name") or "").strip() or "tool"
    raw_args_field = data.get("args")
    raw_args_stream = ""
    if isinstance(raw_args_field, str):
        raw_args_stream = raw_args_field
    elif raw_args_field is not None:
        try:
            raw_args_stream = json.dumps(raw_args_field, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            raw_args_stream = str(raw_args_field)
    display_args = extract_tool_args_dict(raw_args_field)
    is_step_scope = is_step_card_tool_scope(ns_key=ns_key)
    if not display_args and not should_ingest_tool_for_step_stats(
        is_step_card_scope=is_step_scope,
        tool_name=name,
        tool_call_id=tcid,
        args_meaningful=False,
    ):
        return True

    if ui_coalesce is not None and ui_coalesce.note_wire_apply(
        tcid, display_args or raw_args_field
    ):
        return True

    overlay = streaming_overlay if streaming_overlay is not None else {}
    ts = router.resolve_task_scope(ns_key) if ns_key else None
    merge_id, row_key = (
        (tcid, tcid) if is_step_scope else canonical_subgraph_tool_ids(ns_key, tcid, task_scope=ts)
    )

    overlay_payload = dict(display_args or {})
    for key in {tcid, merge_id, row_key}:
        if not key:
            continue
        if overlay_payload:
            overlay[key] = dict(overlay_payload)
        pending_tool_calls_lc[key] = {
            "name": name,
            "args_str": raw_args_stream
            if raw_args_stream
            else json.dumps(overlay_payload, separators=(",", ":")),
            "is_complete_json": True,
            "emitted": False,
            "is_main": is_step_scope,
        }

    if ns_key and not is_step_card_tool_scope(ns_key=ns_key):
        alias_subgraph_pending_and_overlay(pending_tool_calls_lc, overlay, router, ns_key)

    display_args = merge_tool_display_args(
        merge_id or tcid,
        block_args=display_args,
        streaming_overlay=overlay,
        pending_tool_calls_lc=pending_tool_calls_lc,
        tool_name=name,
    )

    if (
        file_op_tracker is not None
        and name in FILE_CHANGE_TOOLS
        and tool_args_meaningful(display_args)
    ):
        file_tcid = str(merge_id or tcid)
        track_file_operation(file_op_tracker, name, display_args, file_tcid)
        await mount_file_change_preview(
            adapter,
            tool_name=name,
            args=display_args,
            tool_call_id=file_tcid,
            assistant_id=adapter._file_preview_assistant_id,
        )

    if is_step_scope and name == "task":
        if is_inner_subgraph_task_tool_id(tcid):
            return True
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        bound_step_id = parsed_sid or router.step_id_for_tool(tcid)
        subagent_card = _ingest_main_task_tool_on_step_card(
            adapter,
            router,
            tcid,
            display_args,
            bound_step_id=bound_step_id,
        )
        # IG-513: Mount SubAgent card if newly created
        await _mount_subagent_card_if_needed(adapter, subagent_card)
        return True

    if is_step_scope:
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        bound_step_id = parsed_sid or router.step_id_for_tool(tcid)
        step_w = _resolve_step_widget_for_tool(
            adapter,
            router,
            bound_step_id=bound_step_id,
            ns_key=ns_key,
        )
        if step_w is not None and name != "task":
            # Bind the execute namespace to this step card so token-usage
            # chunks resolve correctly during parallel waves.
            _register_execute_namespace_binding(
                adapter,
                router,
                ns_key,
                step_id=str(getattr(step_w, "_step_id", "") or bound_step_id),
            )
            update_payload = dict(display_args or {})
            if not update_payload and raw_args_stream:
                update_payload = {"_raw": raw_args_stream}
            _register_main_tool_on_step_card(
                adapter,
                router,
                step_w,
                tcid,
                name,
                update_payload,
                raw_args=raw_args_stream,
            )
        elif name != "task":
            update_payload = dict(display_args or {})
            if not update_payload and raw_args_stream:
                update_payload = {"_raw": raw_args_stream}
            router.buffer_main_tool(
                tcid,
                name,
                update_payload,
                raw_args=raw_args_stream,
            )
        return True

    _merge_buf, display_key = canonical_subgraph_tool_ids(ns_key, tcid, task_scope=ts)
    if display_key:
        _route_subgraph_tool_call(
            adapter,
            router,
            ns_key=ns_key,
            lookup_id=tcid,
            display_key=display_key,
            tool_name=name,
            args=display_args,
            raw_args=raw_args_stream,
        )
    return True


# ---------------------------------------------------------------------------
# Turn helpers
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def _goal_loop_elapsed_start(
    *,
    goal_loop_start_monotonic: float | None,
    turn_start_monotonic: float | None,
) -> float | None:
    """Return the monotonic anchor for goal-loop elapsed time."""
    if goal_loop_start_monotonic is not None:
        return goal_loop_start_monotonic
    return turn_start_monotonic


async def _sync_goal_completion_thinking_row_time(
    adapter: TextualUIAdapter,
    *,
    goal_loop_start_monotonic: float | None,
    turn_start_monotonic: float | None,
    clarification_pending: bool | None = None,
) -> None:
    """Show goal-loop elapsed time on the thinking row above the input box."""
    if clarification_pending is None:
        clarification_pending = bool(getattr(adapter, "_clarification_pending", False))
    if clarification_pending or not adapter._set_spinner:
        return
    start = _goal_loop_elapsed_start(
        goal_loop_start_monotonic=goal_loop_start_monotonic,
        turn_start_monotonic=turn_start_monotonic,
    )
    if _adapter_has_pending_tools(adapter):
        await adapter._set_spinner(SPINNER_LABEL_TOOLS, turn_start_mono=start)
        return
    await adapter._set_spinner(SPINNER_LABEL_THINKING, turn_start_mono=start)


def _loop_id_for_remote_state(config: RunnableConfig, daemon_session: Any) -> str:
    """Resolve checkpoint thread id for daemon ``loop_state_*`` RPCs.

    Prefer ``configurable.thread_id`` from the stream config; fall back to the
    session's active loop when the config is empty (e.g. edge timing during
    bootstrap).
    """
    loop_id = str((config.get("configurable") or {}).get("thread_id") or "").strip()
    if loop_id:
        return loop_id
    raw = getattr(daemon_session, "loop_id", None)
    return str(raw or "").strip()


def _step_card_tool_count(widget: Any) -> int:
    """Return scope-local tool count for a step card footer."""
    build_index = getattr(widget, "_build_row_index", None)
    if callable(build_index):
        return int(build_index().total_tool_count)
    rows = getattr(widget, "_rows", None)
    if isinstance(rows, list):
        return len(rows)
    return 0


def _ensure_step_card_running_ui(widget: Any) -> None:
    """Apply deferred running UI before completing a step card."""
    if getattr(widget, "_deferred_running", False):
        widget._deferred_running = False  # noqa: SLF001
    if getattr(widget, "_status", "") == "pending":  # noqa: SLF001
        if getattr(widget, "is_mounted", False):
            widget.set_running()  # noqa: SLF001
        else:
            widget._status = "running"  # noqa: SLF001
            widget._start_time = time.time()  # noqa: SLF001
            widget._deferred_running = True  # noqa: SLF001
    elif getattr(widget, "_status", "") == "running":  # noqa: SLF001
        ensure = getattr(widget, "_ensure_running_ui", None)
        if callable(ensure):
            ensure()


def _detach_step_card_from_adapter(
    adapter: TextualUIAdapter,
    step_id: str,
    widget: Any,
    *,
    ns_key: tuple[Any, ...],
    router: StepTaskRouter,
) -> None:
    """Clear namespace and tool bindings for a finished step card."""
    if adapter._step_by_namespace.get(ns_key) is widget:
        adapter._step_by_namespace.pop(ns_key, None)
    stale_tool_ids = [k for k, sw in adapter._tool_to_step.items() if sw is widget]
    for k in stale_tool_ids:
        adapter._tool_to_step.pop(k, None)
    for k, parent in list(adapter._tool_display_by_call_id.items()):
        if parent is widget:
            adapter._tool_display_by_call_id.pop(k, None)


def complete_tracked_step_card(
    adapter: TextualUIAdapter,
    router: StepTaskRouter,
    *,
    step_id: str,
    widget: Any,
    ns_key: tuple[Any, ...],
    success: bool,
    duration_ms: int,
    tool_call_count: int,
    summary: str,
) -> None:
    """Finalize a step card that is still tracked in ``_current_step_messages``."""
    _ensure_step_card_running_ui(widget)
    _detach_step_card_from_adapter(adapter, step_id, widget, ns_key=ns_key, router=router)
    widget.set_complete(success, duration_ms, tool_call_count, summary)
    if not ns_key:
        adapter._last_completed_main_step_execute_prose = getattr(
            widget, "last_completed_execute_prose", ""
        )


def _adapter_has_pending_tools(adapter: TextualUIAdapter) -> bool:
    """True while any tool is awaiting a ``ToolMessage`` on a step card."""
    return bool(adapter._tool_to_step)


async def _maybe_set_running_tools_spinner(
    adapter: TextualUIAdapter,
    *,
    clarification_pending: bool | None = None,
) -> None:
    """Show tool-run feedback on the thinking row when tools are in flight."""
    if clarification_pending is None:
        clarification_pending = bool(getattr(adapter, "_clarification_pending", False))
    if clarification_pending or not adapter._set_spinner:
        return
    if _adapter_has_pending_tools(adapter):
        await adapter._set_spinner(
            SPINNER_LABEL_TOOLS,
            hint_extra=_execute_progress_hint(adapter),
        )


def _execute_progress_hint(adapter: TextualUIAdapter) -> str | None:
    """Return ``completed/total`` when a multi-step execute wave is active."""
    total = int(getattr(adapter, "_execute_wave_total", 0) or 0)
    if total <= 1:
        return None
    completed = min(int(getattr(adapter, "_execute_wave_completed", 0) or 0), total)
    return f"{completed}/{total}"


async def _maybe_set_thinking_spinner(
    adapter: TextualUIAdapter,
    *,
    clarification_pending: bool | None = None,
) -> None:
    """Reset thinking row when idle, unless blocked on clarification."""
    if clarification_pending is None:
        clarification_pending = bool(getattr(adapter, "_clarification_pending", False))
    if clarification_pending or not adapter._set_spinner:
        return
    if not _adapter_has_pending_tools(adapter):
        await adapter._set_spinner(
            SPINNER_LABEL_THINKING,
            hint_extra=_execute_progress_hint(adapter),
        )


def _mark_step_tool_rows_running(adapter: TextualUIAdapter) -> None:
    """Mark step-aggregated tool rows running after graph interrupt resume."""
    for tcid, stw in list(adapter._tool_to_step.items()):
        stw.set_tool_running(tcid)


def _reject_step_tool_rows(adapter: TextualUIAdapter) -> None:
    """Mark step-aggregated tool rows rejected and drop pending bindings (IG-402)."""
    for tcid, stw in list(adapter._tool_to_step.items()):
        stw.set_tool_rejected(tcid)
    adapter._tool_to_step.clear()


def _build_interrupted_ai_message(
    pending_text_by_namespace: dict[tuple, str],
    adapter: TextualUIAdapter,
) -> Any:
    """Build an AIMessage capturing interrupted state (text + tool calls).

    Args:
        pending_text_by_namespace: Dict of accumulated text by namespace
        adapter: UI adapter with pending step-aggregated tools.

    Returns:
        AIMessage with accumulated content and tool calls, or None if empty.
    """

    main_ns_key = ()
    accumulated_text = pending_text_by_namespace.get(main_ns_key, "").strip()

    tool_calls: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for step_w in dict.fromkeys(adapter._tool_to_step.values()):
        if hasattr(step_w, "iter_open_tool_calls_for_interrupt"):
            for row in step_w.iter_open_tool_calls_for_interrupt():
                rid = str(row.get("id", ""))
                if rid and rid not in seen_ids:
                    tool_calls.append(row)
                    seen_ids.add(rid)

    if not accumulated_text and not tool_calls:
        return None

    return AIMessage(
        content=accumulated_text,
        tool_calls=tool_calls or [],
    )


def _read_mentioned_file(file_path: Any, max_embed_bytes: int) -> str:
    """Read a mentioned file for inline embedding (sync, for use with to_thread).

    Args:
        file_path: Resolved path to the file.
        max_embed_bytes: Size threshold; larger files get a reference only.

    Returns:
        Markdown snippet with the file content or a size-exceeded reference.
    """
    file_size = file_path.stat().st_size
    if file_size > max_embed_bytes:
        size_kb = file_size // 1024
        return (
            f"\n### {file_path.name}\n"
            f"Path: `{file_path}`\n"
            f"Size: {size_kb}KB (too large to embed, "
            "use read_file tool to view)"
        )
    content = file_path.read_text(encoding="utf-8")
    return f"\n### {file_path.name}\nPath: `{file_path}`\n```\n{content}\n```"


async def _try_mount_instant_loop_assistant_phase(
    adapter: TextualUIAdapter,
    *,
    message: Any,
    blocks: list[Any],
    ns_key: tuple[Any, ...],
    is_main_agent: bool,
    suppress_main_agent_assistant_text: bool,
    pending_text_by_namespace: dict[tuple[Any, ...], str],
    assistant_message_by_namespace: dict[tuple[Any, ...], Any],
    router: Any,
    ev_stats: Any,
    clarification_pending: bool,
) -> bool:
    """Mount single-chunk loop-tagged assistant text; return True when handled."""
    phase = assistant_output_phase(message)
    if phase not in _INSTANT_LOOP_ASSISTANT_PHASES or not is_main_agent:
        return False
    if suppress_main_agent_assistant_text:
        return True
    text = "\n".join(
        str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text"
    )
    if not text.strip():
        return True
    ev_stats.text_chunks += 1
    pending_text = pending_text_by_namespace.get(ns_key, "")
    if pending_text:
        await _flush_assistant_text_ns(
            adapter,
            pending_text,
            ns_key,
            assistant_message_by_namespace,
            router=router,
        )
        pending_text_by_namespace[ns_key] = ""
        assistant_message_by_namespace.pop(ns_key, None)
    current_msg = assistant_message_by_namespace.get(ns_key)
    if current_msg is not None:
        if text:
            await current_msg.append_content(text)
            if adapter._sync_message_content and current_msg.id:
                adapter._sync_message_content(current_msg.id, current_msg._content)
        if adapter._set_active_message:
            adapter._set_active_message(None)
        await _maybe_set_thinking_spinner(adapter, clarification_pending=clarification_pending)
        return True

    repaired = RendererBase.repair_concatenated_output(text)
    output_widget = AssistantMessage(
        id=f"asst-{uuid.uuid4().hex[:8]}",
        render_markdown=False,
    )
    await adapter._mount_message(output_widget)
    assistant_message_by_namespace[ns_key] = output_widget
    if repaired:
        await output_widget.append_content(repaired)
    if adapter._sync_message_content and output_widget.id:
        adapter._sync_message_content(output_widget.id, output_widget._content)
    if adapter._set_active_message:
        adapter._set_active_message(None)
    await _maybe_set_thinking_spinner(adapter, clarification_pending=clarification_pending)
    return True


async def _finalize_goal_completion_stream(
    adapter: TextualUIAdapter,
    stream_msg: AssistantMessage,
    *,
    ns_key: tuple[Any, ...],
    goal_completion_stream_by_namespace: dict[tuple[Any, ...], AssistantMessage],
    assistant_message_by_namespace: dict[tuple[Any, ...], Any],
    extra_text: str,
    goal_loop_start_monotonic: float | None = None,
    turn_start_monotonic: float | None = None,
) -> None:
    """Stop the goal_completion ``AssistantMessage`` stream and record it under ``ns_key``."""
    if not getattr(stream_msg, "_streaming_active", False):
        return
    if extra_text and extra_text not in getattr(stream_msg, "_content", ""):
        await stream_msg.append_content(extra_text)
    await stream_msg.stop_stream()
    if adapter._sync_message_content and stream_msg.id:
        adapter._sync_message_content(stream_msg.id, stream_msg._content)
    goal_completion_stream_by_namespace.pop(ns_key, None)
    assistant_message_by_namespace[ns_key] = stream_msg
    adapter._goal_completion_mounted_this_turn = True
    if adapter._set_active_message:
        adapter._set_active_message(None)
    await _sync_goal_completion_thinking_row_time(
        adapter,
        goal_loop_start_monotonic=goal_loop_start_monotonic,
        turn_start_monotonic=turn_start_monotonic,
    )


async def _finalize_goal_completion_streams_on_turn_end(
    adapter: TextualUIAdapter,
    *,
    goal_completion_stream_by_namespace: dict[tuple[Any, ...], AssistantMessage],
    assistant_message_by_namespace: dict[tuple[Any, ...], Any],
    goal_loop_start_monotonic: float | None,
    turn_start_monotonic: float | None,
) -> None:
    """Finalize partial goal_completion cards on ``soothe.stream.end`` scope=turn."""
    if not goal_completion_stream_by_namespace:
        return
    await asyncio.gather(
        *[
            _finalize_goal_completion_stream(
                adapter,
                stream_msg,
                ns_key=ns_key,
                goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
                assistant_message_by_namespace=assistant_message_by_namespace,
                extra_text="",
                goal_loop_start_monotonic=goal_loop_start_monotonic,
                turn_start_monotonic=turn_start_monotonic,
            )
            for ns_key, stream_msg in list(goal_completion_stream_by_namespace.items())
        ]
    )


async def _handle_interrupt_cleanup(
    *,
    adapter: TextualUIAdapter,
    config: RunnableConfig,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
    pending_text_by_namespace: dict[tuple, str],
    captured_input_tokens: int,
    captured_output_tokens: int,
    turn_stats: SessionStats,
    start_time: float,
    app_exiting: bool = False,
) -> None:
    """Shared cleanup for CancelledError and KeyboardInterrupt.

    Args:
        adapter: UI adapter with display callbacks.
        config: Runnable config with loop_id mapped to thread_id in configurable.
        daemon_session: Active daemon websocket session; also receives ``/cancel``
            so the in-flight query stops (Ctrl+C / Esc; ``detach`` is quit-only).
        pending_text_by_namespace: Accumulated text per namespace.
        captured_input_tokens: Input tokens captured before interrupt.
        captured_output_tokens: Output tokens captured before interrupt.
        turn_stats: Stats for the current turn.
        start_time: Monotonic timestamp when the turn began.
        app_exiting: When ``True`` (TUI quit), skip daemon RPC — disconnect
            cleanup runs immediately afterward.
    """
    import time

    # Clear active message immediately so it won't block pruning.
    # If we don't do this, the store still thinks it's active and protects
    # from pruning, which breaks get_messages_to_prune(), potentially
    # blocking all future pruning.
    if adapter._set_active_message:
        adapter._set_active_message(None)

    # Hide spinner (may still show a stale status if interrupted)
    if adapter._set_spinner:
        await adapter._set_spinner(None)

    interrupted_msg = _build_interrupted_ai_message(pending_text_by_namespace, adapter)

    # Save accumulated state before marking tools as rejected (best-effort).
    # State update failures shouldn't prevent cleanup.
    # Use shorter timeout (2s) during interrupt cleanup to avoid blocking cancel.
    if not app_exiting:
        try:
            cancellation_msg = HumanMessage(
                content="[SYSTEM] Task interrupted by user. Previous operation was cancelled."
            )
            loop_id = _loop_id_for_remote_state(config, daemon_session)
            if loop_id:
                # Attribute the write to the deepagents ``model`` node — the owner of
                # the ``messages`` channel — so LangGraph does not raise
                # ``Ambiguous update, specify as_node`` when multiple nodes have
                # checkpointed at the current version (e.g. tool node + model node).
                if interrupted_msg:
                    await daemon_session.aupdate_loop_state(
                        loop_id,
                        {"messages": [interrupted_msg.model_dump()]},
                        timeout=2.0,
                        as_node="model",
                    )
                await daemon_session.aupdate_loop_state(
                    loop_id,
                    {"messages": [cancellation_msg.model_dump()]},
                    timeout=2.0,
                    as_node="model",
                )
        except Exception:
            logger.warning("Failed to save interrupted state", exc_info=True)

    # Mark tools as rejected AFTER saving state
    _reject_step_tool_rows(adapter)
    adapter._tool_display_by_call_id.clear()

    for step_msg in list(adapter._current_step_messages.values()):
        step_msg.set_interrupted("")
    adapter._current_step_messages.clear()
    adapter._tool_to_step.clear()
    adapter._step_by_namespace.clear()
    adapter._step_router.reset_turn()
    if adapter._goal_tree_message is not None:
        adapter._goal_tree_message.set_interrupted("Stream cancelled")

    adapter._last_completed_main_step_execute_prose = ""
    adapter._last_main_flushed_assistant_prose = ""

    # Keep the token count marked stale whenever interrupted state was captured,
    # including tool-only turns after assistant text was already flushed.
    approximate = interrupted_msg is not None

    turn_stats.wall_time_seconds = time.monotonic() - start_time
    if not app_exiting:
        await _report_and_persist_tokens(
            adapter,
            config,
            captured_input_tokens,
            captured_output_tokens,
            shield=True,
            approximate=approximate,
            daemon_session=daemon_session,
        )

    # Ensure the daemon-side query is cancelled, not detached (detach is quit-only).
    if not app_exiting:
        client = getattr(daemon_session, "_client", None)
        if client is not None and not client.is_connected:
            logger.debug("Skipping daemon cancel — connection already closed")
        else:
            try:
                await daemon_session.cancel_remote_query()
                logger.info("Sent cancel to daemon during interrupt cleanup")
            except ConnectionError:
                logger.debug("Daemon connection closed before cancel during interrupt cleanup")
            except Exception:
                logger.warning(
                    "Failed to send cancel to daemon during interrupt cleanup",
                    exc_info=True,
                )


async def _persist_context_tokens(
    config: RunnableConfig,
    tokens: int,
    *,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
) -> None:
    """Best-effort persist of the context token count into remote loop state."""
    try:
        loop_id = _loop_id_for_remote_state(config, daemon_session)
        if loop_id:
            await daemon_session.aupdate_loop_state(loop_id, {"_context_tokens": tokens})
    except Exception:  # non-critical; stale count on resume is acceptable
        logger.warning(
            "Failed to persist _context_tokens=%d; token count may be stale on resume",
            tokens,
            exc_info=True,
        )


async def _report_and_persist_tokens(
    adapter: TextualUIAdapter,
    config: RunnableConfig,
    captured_input_tokens: int,
    captured_output_tokens: int,
    *,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
    shield: bool = False,
    approximate: bool = False,
) -> None:
    """Update the token display and best-effort persist via ``loop_state_update``."""
    if captured_input_tokens or captured_output_tokens:
        if adapter._on_tokens_update:
            adapter._on_tokens_update(captured_input_tokens, approximate=approximate)
        if shield:
            try:
                await _persist_context_tokens(
                    config,
                    captured_input_tokens,
                    daemon_session=daemon_session,
                )
            except (Exception, asyncio.CancelledError):
                logger.debug(
                    "Token persist suppressed during interrupt cleanup",
                    exc_info=True,
                )
        else:
            await _persist_context_tokens(
                config,
                captured_input_tokens,
                daemon_session=daemon_session,
            )
    elif adapter._on_tokens_show:
        adapter._on_tokens_show(approximate=approximate)


async def _flush_assistant_text_ns(
    adapter: TextualUIAdapter,
    text: str,
    ns_key: tuple,
    assistant_message_by_namespace: dict[tuple, Any],
    *,
    router: StepTaskRouter | None = None,
) -> None:
    """Flush accumulated assistant text for a specific namespace.

    Finalizes the streaming state on the assistant card.
    If no message exists yet, creates one with the full content.
    """
    repaired_text = RendererBase.repair_concatenated_output(text)
    ts_card = router.resolve_task_scope(ns_key) if router is not None and ns_key else None
    subagent_type = str(ts_card[1] or "").strip() if ts_card else ""
    repaired_text = format_subagent_task_assistant_for_display(
        repaired_text,
        subagent_type=subagent_type or None,
    )
    if not repaired_text.strip():
        return

    if ts_card and ts_card[0]:
        subagent_card = _ensure_subagent_card_for_task_scope(adapter, ts_card)
        if subagent_card is not None:
            subagent_card.append_subagent_activity(repaired_text.strip())
            return
        # Suppress standalone AssistantMessage for all subagent tasks —
        # only goal_completion surfaces the final result.
        return

    current_msg = assistant_message_by_namespace.get(ns_key)
    if current_msg is None:
        # No message was created during streaming - create one with full content
        msg_id = f"asst-{uuid.uuid4().hex[:8]}"
        current_msg = AssistantMessage(repaired_text, id=msg_id)
        await adapter._mount_message(current_msg)
        await current_msg.write_initial_content()
        assistant_message_by_namespace[ns_key] = current_msg
    else:
        # Stop the stream to finalize the content
        await current_msg.stop_stream()
        # Sync normalized text for persistence without re-rendering: MarkdownStream
        # already displayed the streamed body; repair can disturb fenced blocks/tables.
        if repaired_text != current_msg._content:
            current_msg._content = repaired_text

    # When the AssistantMessage was first mounted and recorded in the
    # MessageStore, it had empty content (streaming hadn't started yet).
    # Now that streaming is done, the widget holds the full text in
    # `_content`, but the store's MessageData still has `content=""`.
    # If the message is later pruned and re-hydrated, `to_widget()` would
    # recreate it from that stale empty string. This call copies the
    # widget's final content back into the store so re-hydration works.
    if adapter._sync_message_content and current_msg.id:
        adapter._sync_message_content(current_msg.id, current_msg._content)

    if not ns_key:
        adapter._last_main_flushed_assistant_prose = _tui_main_assistant_body_for_dedupe(
            getattr(current_msg, "_content", "") or ""
        )

    # Clear active message since streaming is done
    if adapter._set_active_message:
        adapter._set_active_message(None)


# ---------------------------------------------------------------------------
# Turn execution
# ---------------------------------------------------------------------------


def _snapshot_turn_event_stats(
    ev_stats: TurnEventStats,
    daemon_session: Any,  # noqa: ANN401
) -> TurnEventStats:
    """Return turn + daemon transport counters without mutating ``ev_stats``."""
    snapshot = TurnEventStats()
    snapshot.merge(ev_stats)
    if daemon_session is not None:
        snapshot.merge(daemon_session.turn_event_stats)
    return snapshot


def _warn_inbound_dropped(ev_stats: TurnEventStats) -> None:
    if ev_stats.inbound_dropped > 0:
        logger.warning(
            "Stream degraded during turn: %d inbound frame(s) dropped "
            "(response may be incomplete; try /resume or re-run)",
            ev_stats.inbound_dropped,
        )


def _log_goal_completed_event_stats(
    ev_stats: TurnEventStats,
    turn_stats: SessionStats,
    daemon_session: Any,  # noqa: ANN401
    *,
    status: str,
    goal_progress: str,
    total_steps: int,
    elapsed_seconds: float,
) -> None:
    """Emit a structured goal-completion summary to ``cli.log``."""
    snapshot = _snapshot_turn_event_stats(ev_stats, daemon_session)
    _warn_inbound_dropped(snapshot)
    logger.info(
        "%s",
        format_cli_log_event(
            build_goal_completed_log_event(
                snapshot,
                status=status,
                goal_progress=goal_progress,
                total_steps=total_steps,
                elapsed_seconds=elapsed_seconds,
            )
        ),
    )


def _log_turn_event_stats(
    ev_stats: TurnEventStats,
    turn_stats: SessionStats,
    daemon_session: Any,  # noqa: ANN401
) -> None:
    """Merge daemon-side counters and emit final turn summary to ``cli.log``."""
    snapshot = _snapshot_turn_event_stats(ev_stats, daemon_session)
    turn_stats.event_stats = snapshot
    _warn_inbound_dropped(snapshot)
    logger.info(
        "%s",
        format_cli_log_event(
            build_turn_finished_log_event(
                snapshot,
                wall_seconds=turn_stats.wall_time_seconds,
            )
        ),
    )


def _should_show_clarification_prompt(
    *, event_data: dict[str, Any], fallback_mode: str | None
) -> bool:
    """Return True when TUI should show the interactive clarification card.

    In auto mode, clarifications are resolved/deferred by policy and should not
    render "Awaiting your answer" UI prompts in the TUI message stream.
    """
    mode = event_data.get("mode")
    if isinstance(mode, str) and mode.strip():
        normalized = mode.strip().lower()
    elif isinstance(fallback_mode, str) and fallback_mode.strip():
        normalized = fallback_mode.strip().lower()
    else:
        normalized = "auto"
    if normalized not in {"auto", "manual"}:
        normalized = "auto"
    return normalized == "manual"


async def execute_task_textual(
    user_input: str,
    assistant_id: str | None,
    session_state: Any,  # noqa: ANN401  # Dynamic session state type
    adapter: TextualUIAdapter,
    image_tracker: MediaTracker | None = None,
    context: CLIContext | None = None,
    *,
    daemon_session: Any,  # noqa: ANN401  # TuiDaemonSession
    sandbox_type: str | None = None,
    workspace: str | None = None,
    message_kwargs: dict[str, Any] | None = None,
    turn_stats: SessionStats | None = None,
    skip_daemon_send_turn: bool = False,
    clarification_mode: str | None = None,
    is_shutting_down: Callable[[], bool] | None = None,
) -> SessionStats:
    """Execute a task with output directed to Textual UI.

    This is the Textual-compatible version of execute_task() that uses
    the TextualUIAdapter for all UI operations.

    Args:
        user_input: The user's input message
        daemon_session: Connected daemon websocket session (exclusive execution path).
            When ``skip_daemon_send_turn=True``, only consumes chunks (prompt already
            queued server-side).
        assistant_id: The agent identifier
        session_state: Session state (loop id, etc.)
        adapter: The TextualUIAdapter for UI operations
        image_tracker: Optional tracker for images
        context: Optional `CLIContext` with model override and params, passed
            to the graph via `context=`.
        sandbox_type: Sandbox provider name for trace metadata, or `None`
            if no sandbox is active.
        workspace: Resolved project directory (status-bar cwd / daemon bootstrap)
            mirrored into stream ``configurable.workspace``; when omitted,
            ``build_stream_config`` uses ``Path.cwd()`` (IG-341).
        message_kwargs: Extra fields merged into the stream input message
            dict (e.g., `additional_kwargs` for persisting skill metadata
            in the checkpoint).
        turn_stats: Pre-created `SessionStats` to accumulate into.

            When the caller holds a reference to the same object, stats are
            available even if this coroutine is cancelled before it can return.

            If `None`, a new instance is created internally.
        skip_daemon_send_turn: When ``True``, skip ``send_turn`` and only consume
            chunks (prompt already queued, e.g. after ``invoke_skill`` or a
            running loop).

    Returns:
        Stats accumulated over this turn (request count, token counts,
            wall-clock time).

    Raises:
    """
    from langchain_core.messages import AIMessageChunk

    if daemon_session is None:
        raise RuntimeError("execute_task_textual requires daemon_session")

    presentation = PresentationEngine()

    # Parse file mentions and inject content if any — defer blocking I/O
    prompt_text, mentioned_files = await asyncio.to_thread(parse_file_mentions, user_input)

    # Max file size to embed inline (256KB, matching mistral-vibe)
    # Larger files get a reference instead - use read_file tool to view them
    max_embed_bytes = 256 * 1024

    if mentioned_files:
        context_parts = [prompt_text, "\n\n## Referenced Files\n"]
        for file_path in mentioned_files:
            try:
                part = await asyncio.to_thread(_read_mentioned_file, file_path, max_embed_bytes)
                context_parts.append(part)
            except Exception as e:  # noqa: BLE001  # Resilient adapter error handling
                context_parts.append(f"\n### {file_path.name}\n[Error reading file: {e}]")
        final_input = "\n".join(context_parts)
    else:
        final_input = prompt_text

    # Include images and videos in the message content
    images_to_send = []
    videos_to_send = []
    if image_tracker:
        images_to_send = image_tracker.get_images()
        videos_to_send = image_tracker.get_videos()
    if images_to_send or videos_to_send:
        message_content = create_multimodal_content(final_input, images_to_send, videos_to_send)
    else:
        message_content = final_input

    loop_id = session_state.loop_id
    config = build_stream_config(
        loop_id,
        assistant_id,
        sandbox_type=sandbox_type,
        workspace=workspace,
    )

    await dispatch_hook("session.start", {"loop_id": loop_id})

    captured_input_tokens = 0
    captured_output_tokens = 0
    if turn_stats is None:
        turn_stats = SessionStats()
    ev_stats = TurnEventStats()
    ev_stats.latency = TurnLatencyStats(turn_start_monotonic=time.monotonic())
    start_time = time.monotonic()
    goal_completed_logged = False

    # Warn if token display callbacks are only partially wired — all three
    # should be set together to avoid inconsistent status-bar behavior.
    token_cbs = (
        adapter._on_tokens_update,
        adapter._on_tokens_hide,
        adapter._on_tokens_show,
    )
    if any(token_cbs) and not all(token_cbs):
        logger.warning(
            "Token callbacks partially wired (update=%s, hide=%s, show=%s); token display may behave inconsistently",
            adapter._on_tokens_update is not None,
            adapter._on_tokens_hide is not None,
            adapter._on_tokens_show is not None,
        )

    # Show spinner
    if adapter._set_spinner:
        await adapter._set_spinner(SPINNER_LABEL_THINKING)

    # Hide token display during streaming (will be shown with accurate count at end)
    if adapter._on_tokens_hide:
        adapter._on_tokens_hide()

    file_op_tracker = FileOpTracker(assistant_id=assistant_id)
    adapter._file_preview_assistant_id = assistant_id
    adapter._file_change_previews_shown.clear()
    adapter._file_change_widgets.clear()
    router = adapter._step_router
    router.reset_turn()
    adapter._execute_wave_total = 0
    adapter._execute_wave_completed = 0
    adapter._successful_step_ids.clear()
    ui_coalesce = TurnToolUiCoalescer()
    adapter._goal_completion_mounted_this_turn = False
    adapter._goal_tree_message = None
    tool_call_buffers: dict[str | int, dict] = {}
    # Streaming tool-call args (``tool_call_chunks``) — mirrors EventProcessor / IG-053
    pending_tool_calls_lc: dict[str, dict[str, Any]] = {}
    last_active_tool_call_id: str = ""  # For orphan chunk attachment
    streaming_overlay: dict[str, dict[str, Any]] = {}

    # Track pending text and assistant messages PER NAMESPACE to avoid interleaving
    # when multiple subagents stream in parallel
    pending_text_by_namespace: dict[tuple, str] = {}
    assistant_message_by_namespace: dict[tuple, Any] = {}
    goal_completion_stream_by_namespace: dict[tuple, AssistantMessage] = {}
    goal_loop_start_monotonic: float | None = None
    task_loop_assistant_by_tcid: dict[str, str] = {}

    # Clear media from tracker after creating the message
    if image_tracker:
        image_tracker.clear()

    # Track summarization lifecycle so spinner status and notification stay in sync.
    summarization_in_progress = False
    # Per-turn mirror of the adapter-scoped clarification flag (RFC-622 /
    # RFC-623). Set when ``soothe.loop.clarification.requested`` /
    # ``soothe.loop.clarification.deferred`` arrive and cleared on
    # ``soothe.loop.clarification.answered``. The local copy gates the
    # stream-end safety net; the persisted adapter flag is what the next turn
    # reads to decide whether to attach ``clarification_answer=True``.
    clarification_pending = False
    # Snapshot of the persisted flag taken when this turn started. If the user
    # is answering a previously-pending clarification, we attach the wire flag
    # below and clear ``adapter._clarification_pending`` so the next turn does
    # not double-send. The new turn's events will re-arm the flag if the
    # daemon emits another ``clarification_requested``.
    sending_clarification_answer = bool(getattr(adapter, "_clarification_pending", False))
    pending_clarification_answers: list[str] | None = None
    if sending_clarification_answer:
        adapter._clarification_pending = False
        raw_answers = getattr(adapter, "_clarification_answers_pending", None)
        if isinstance(raw_answers, list) and raw_answers:
            pending_clarification_answers = list(raw_answers)
        adapter._clarification_answers_pending = None
    try:
        if skip_daemon_send_turn:
            chunk_source = daemon_session.iter_turn_chunks()
        else:
            daemon_text = message_content if isinstance(message_content, str) else final_input
            subagent_name, routed_text = parse_subagent_from_input(
                daemon_text if isinstance(daemon_text, str) else final_input
            )
            ctx_model = context.get("model") if context else None
            raw_mp = context.get("model_params") if context else None
            mp = raw_mp if isinstance(raw_mp, dict) else None
            image_attachments: list[dict[str, str]] | None = None
            if images_to_send:
                image_attachments = [
                    {
                        "mime_type": f"image/{img.format}",
                        "data": img.base64_data,
                    }
                    for img in images_to_send
                ]
            await daemon_session.send_turn(
                routed_text,
                preferred_subagent=subagent_name,
                model=ctx_model if isinstance(ctx_model, str) and ctx_model.strip() else None,
                model_params=mp,
                attachments=image_attachments,
                clarification_mode=clarification_mode,
                clarification_answer=sending_clarification_answer,
                clarification_answers=pending_clarification_answers,
            )
            chunk_source = daemon_session.iter_turn_chunks()

        prep_state = TurnPrepareState(
            ev_stats=ev_stats,
            presentation=presentation,
        )

        async def _apply_turn_chunk(prepared: PreparedTurnChunk | None) -> None:
            nonlocal last_active_tool_call_id
            nonlocal summarization_in_progress
            nonlocal clarification_pending
            nonlocal goal_completed_logged
            nonlocal goal_loop_start_monotonic
            nonlocal captured_input_tokens
            if prepared is None or prepared.skip:
                return
            for _chunk_once in (0,):
                try:
                    current_stream_mode = prepared.mode
                    data = prepared.data
                    ns_key = prepared.namespace

                    # Root graph uses namespace ``()``; delegated subgraphs use non-empty
                    # namespaces. Assistant *text* from subgraphs is suppressed (avoid duplicate
                    # prose with main). Tool stats attach to step cards on the main graph only.
                    is_main_agent = ns_key == ()
                    is_step_scope = is_step_card_tool_scope(ns_key=ns_key)
                    suppress_subgraph_assistant_text = not is_main_agent
                    suppress_main_agent_assistant_text = False

                    # Handle UPDATES stream - for todos
                    if current_stream_mode == "updates":
                        if not isinstance(data, dict):
                            continue

                        # Check for todo updates (not yet implemented in Textual UI)
                        chunk_data = next(iter(data.values())) if data else None
                        if chunk_data and isinstance(chunk_data, dict) and "todos" in chunk_data:
                            pass  # Future: render todo list widget

                    # Handle MESSAGES stream - for content and tool calls
                    elif current_stream_mode == "messages":
                        if not isinstance(data, (list, tuple)) or len(data) != 2:  # noqa: PLR2004
                            logger.debug(
                                "Skipping non-pair message data: type=%s",
                                type(data).__name__,
                            )
                            continue

                        if prepared.normalized_message is not None:
                            message = prepared.normalized_message
                            metadata = prepared.message_metadata
                        else:
                            message, metadata = data
                            message = _normalize_lc_stream_message(message)

                        if ns_key and not is_step_card_tool_scope(ns_key=ns_key):
                            router.on_subgraph_namespace(ns_key)

                        # Filter out summarization model output, but keep UI feedback.
                        # The summarization model streams AIMessage chunks tagged
                        # with lc_source="summarization" in the callback metadata.
                        # These are hidden from the user; only the spinner and a
                        # notification widget provide feedback.
                        if prepared.is_summarization or _is_summarization_chunk(metadata):
                            if not summarization_in_progress:
                                summarization_in_progress = True
                                if adapter._set_spinner:
                                    await adapter._set_spinner(SPINNER_LABEL_OFFLOADING)
                            continue

                        # Regular (non-summarization) chunks resumed — summarization
                        # has finished. Mount the notification and reset the spinner.
                        if summarization_in_progress:
                            summarization_in_progress = False
                            try:
                                await adapter._mount_message(SummarizationMessage())
                            except Exception:
                                logger.debug(
                                    "Failed to mount summarization notification",
                                    exc_info=True,
                                )
                            if adapter._set_spinner and not _adapter_has_pending_tools(adapter):
                                await _maybe_set_thinking_spinner(
                                    adapter, clarification_pending=clarification_pending
                                )

                        if isinstance(message, HumanMessage):
                            content = message.text
                            # Flush pending text for this namespace
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if content and pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                            continue

                        tool_result = extract_tool_result_payload(message)
                        if tool_result is not None:
                            ev_stats.tool_results += 1
                            tool_id = tool_result.tool_call_id or None
                            if tool_id:
                                pending_tool_calls_lc.pop(str(tool_id), None)

                            record = file_op_tracker.complete_with_message(message)

                            sid = str(tool_id) if tool_id else ""
                            row_key = resolve_tool_result_row_key(
                                ns_key=ns_key,
                                tool_call_id=sid,
                                task_scope=router.resolve_task_scope(ns_key),
                            )
                            output_str = tool_result.output_display
                            if row_key:
                                step_w = adapter._tool_to_step.pop(row_key, None)
                                if step_w is not None:
                                    dur_ms = step_w.row_duration_ms_since_started(row_key)
                                    if not tool_result.is_error:
                                        step_w.set_tool_success(
                                            row_key, output_str, duration_ms=dur_ms
                                        )
                                    else:
                                        step_w.set_tool_error(
                                            row_key, output_str or "Error", duration_ms=dur_ms
                                        )
                                        await dispatch_hook(
                                            "tool.error",
                                            {"tool_names": [tool_result.tool_name or "tool"]},
                                        )

                            # Reshow spinner only when all in-flight tools have
                            # completed (avoids premature "Thinking..." when
                            # parallel tool calls are active).
                            if adapter._set_spinner and not _adapter_has_pending_tools(adapter):
                                await _maybe_set_thinking_spinner(
                                    adapter, clarification_pending=clarification_pending
                                )

                            # Finalize mounted file previews in place; fall back to DiffMessage
                            if record and record.tool_name in FILE_CHANGE_TOOLS:
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                        router=router,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                finalized = await finalize_file_change_preview(
                                    adapter,
                                    record=record,
                                )
                                if not finalized and record.diff:
                                    await adapter._mount_message(
                                        DiffMessage(
                                            record.diff,
                                            record.display_path,
                                            action_label=file_change_action_label(record),
                                        )
                                    )
                            continue

                        # Extract token usage (before content_blocks check
                        # - usage may be on any chunk)
                        if hasattr(message, "usage_metadata"):
                            usage = message.usage_metadata
                            if usage:
                                input_toks = usage.get("input_tokens", 0)
                                output_toks = usage.get("output_tokens", 0)
                                total_toks = usage.get("total_tokens", 0)
                                from soothe_cli.tui.config import settings

                                active_model = settings.model_name or ""
                                if input_toks or output_toks:
                                    # Model gives split counts — preferred path
                                    turn_stats.record_request(active_model, input_toks, output_toks)
                                    captured_input_tokens = max(
                                        captured_input_tokens, input_toks + output_toks
                                    )
                                    token_card = _resolve_token_target_card(
                                        adapter, router, ns_key, message=message
                                    )
                                    if token_card is not None:
                                        token_card.record_token_usage(input_toks, output_toks)
                                elif total_toks:
                                    # Fallback: model gives only total (no split)
                                    turn_stats.record_request(active_model, total_toks, 0)
                                    captured_input_tokens = max(captured_input_tokens, total_toks)
                                    token_card = _resolve_token_target_card(
                                        adapter, router, ns_key, message=message
                                    )
                                    if token_card is not None:
                                        token_card.record_token_usage(total_toks, 0)

                        touched_tool_ids = tool_ids_touched_by_stream_message(message)
                        if touched_tool_ids:
                            ev_stats.tool_calls += 1
                        if prepared.tool_stream_touched or touched_tool_ids:
                            last_active_tool_call_id = ingest_tool_call_stream_state(
                                pending_tool_calls_lc,
                                message,
                                is_main=(ns_key == ()),
                                last_active_id=last_active_tool_call_id,
                            )
                        if isinstance(message, (AIMessage, AIMessageChunk)) or (
                            isinstance(message, dict)
                            and (message.get("tool_call_chunks") or message.get("tool_calls"))
                        ):
                            overlay_msg = message
                            if isinstance(message, dict):
                                overlay_msg = AIMessageChunk(content="")
                            chunk_overlay = build_streaming_args_overlay(
                                overlay_msg,
                                pending_tool_calls_lc,
                                only_ids=touched_tool_ids,
                            )
                            streaming_overlay.update(chunk_overlay)
                            if ns_key:
                                alias_subgraph_pending_and_overlay(
                                    pending_tool_calls_lc,
                                    streaming_overlay,
                                    router,
                                    ns_key,
                                )
                        blocks = _tui_effective_ai_blocks(
                            message,
                            ns_key=ns_key,
                            streaming_overlay=streaming_overlay or None,
                        )
                        if not blocks:
                            continue

                        # ``phase=goal_completion`` → standalone ``AssistantMessage`` (all namespaces).
                        if getattr(message, "phase", None) == "goal_completion":
                            text_gc = "\n".join(
                                str(b.get("text", ""))
                                for b in blocks
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                            is_gc_chunk = isinstance(message, AIMessageChunk)
                            is_gc_terminal = is_goal_completion_stream_terminal(message)
                            if text_gc == "" and is_gc_chunk and not is_gc_terminal:
                                continue

                            output_text = text_gc
                            ev_stats.text_chunks += 1
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            existing_msg = assistant_message_by_namespace.get(ns_key)
                            stream_msg = goal_completion_stream_by_namespace.get(ns_key)
                            in_gc_stream = is_gc_chunk or stream_msg is not None

                            if in_gc_stream:
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                        router=router,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)

                                if stream_msg is None:
                                    if is_gc_terminal and not output_text:
                                        await _sync_goal_completion_thinking_row_time(
                                            adapter,
                                            goal_loop_start_monotonic=goal_loop_start_monotonic,
                                            turn_start_monotonic=start_time,
                                            clarification_pending=clarification_pending,
                                        )
                                        continue
                                    if adapter._set_spinner:
                                        await adapter._set_spinner(SPINNER_LABEL_SYNTHESIZING)
                                    msg_id = f"asst-{uuid.uuid4().hex[:8]}"
                                    if adapter._set_active_message:
                                        adapter._set_active_message(msg_id)
                                    stream_msg = AssistantMessage(id=msg_id)
                                    await adapter._mount_message(stream_msg)
                                    goal_completion_stream_by_namespace[ns_key] = stream_msg

                                if output_text and output_text not in getattr(
                                    stream_msg, "_content", ""
                                ):
                                    await stream_msg.append_content(output_text)
                                if is_gc_terminal or not is_gc_chunk:
                                    await _finalize_goal_completion_stream(
                                        adapter,
                                        stream_msg,
                                        ns_key=ns_key,
                                        goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
                                        assistant_message_by_namespace=assistant_message_by_namespace,
                                        extra_text="",
                                        goal_loop_start_monotonic=goal_loop_start_monotonic,
                                        turn_start_monotonic=start_time,
                                    )
                                continue

                            if existing_msg is not None:
                                if adapter._set_active_message:
                                    adapter._set_active_message(None)
                                await _maybe_set_thinking_spinner(
                                    adapter, clarification_pending=clarification_pending
                                )
                                continue

                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)

                            repaired_output = RendererBase.repair_concatenated_output(output_text)
                            output_widget = AssistantMessage(
                                repaired_output,
                                id=f"asst-{uuid.uuid4().hex[:8]}",
                            )
                            await adapter._mount_message(output_widget)
                            await output_widget.write_initial_content()
                            adapter._goal_completion_mounted_this_turn = True
                            if adapter._sync_message_content and output_widget.id:
                                adapter._sync_message_content(
                                    output_widget.id,
                                    repaired_output,
                                )
                            assistant_message_by_namespace[ns_key] = output_widget

                            if adapter._set_active_message:
                                adapter._set_active_message(None)
                            await _sync_goal_completion_thinking_row_time(
                                adapter,
                                goal_loop_start_monotonic=goal_loop_start_monotonic,
                                turn_start_monotonic=start_time,
                                clarification_pending=clarification_pending,
                            )
                            continue

                        if await _try_mount_instant_loop_assistant_phase(
                            adapter,
                            message=message,
                            blocks=blocks,
                            ns_key=ns_key,
                            is_main_agent=is_main_agent,
                            suppress_main_agent_assistant_text=suppress_main_agent_assistant_text,
                            pending_text_by_namespace=pending_text_by_namespace,
                            assistant_message_by_namespace=assistant_message_by_namespace,
                            router=router,
                            ev_stats=ev_stats,
                            clarification_pending=clarification_pending,
                        ):
                            continue

                        for block in blocks:
                            block_type = block.get("type")

                            if block_type == "text":
                                if suppress_main_agent_assistant_text:
                                    continue
                                task_scope_txt = (
                                    router.resolve_task_scope(ns_key) if ns_key else None
                                )
                                phase_loop = getattr(message, "phase", None)
                                text = block.get("text", "") or ""
                                if task_scope_txt is not None:
                                    if (
                                        phase_loop
                                        in (
                                            "execute_step",
                                            "execute_wave",
                                        )
                                        and text.strip()
                                    ):
                                        tcid = str(task_scope_txt[0] or "").strip()
                                        if tcid:
                                            parent_tool = router.resolve_parent(
                                                task_scope_txt,
                                                step_cards=adapter._current_step_messages,
                                                tool_display_by_call_id=adapter._tool_display_by_call_id,
                                            )
                                            if parent_tool is not None and hasattr(
                                                parent_tool, "set_result_preview"
                                            ):
                                                prev = task_loop_assistant_by_tcid.get(tcid, "")
                                                task_loop_assistant_by_tcid[tcid] = prev + text
                                                parent_tool.set_result_preview(
                                                    task_loop_assistant_by_tcid[tcid]
                                                )
                                    continue
                                if suppress_subgraph_assistant_text:
                                    continue
                                if not text:
                                    continue
                                if phase_loop == "execute_step" and is_main_agent and text.strip():
                                    step_w = adapter._step_by_namespace.get(ns_key)
                                    if step_w is not None:
                                        step_w.append_execute_assistant_delta(text)
                                    # Never mount standalone assistant cards for execute-step prose
                                    # (aggregated on the step card when present).
                                    continue

                                # Main graph: skip standalone AssistantMessage cards for
                                # intermediate AIMessage streams (execute_wave, unphased, etc.).
                                # ``goal_completion`` is handled above. Other RFC-614 user-output
                                # phases (chitchat, plan_direct, autonomous_goal) use instant mount.
                                if (
                                    is_main_agent
                                    and assistant_output_phase(message)
                                    not in LOOP_ASSISTANT_OUTPUT_PHASES
                                ):
                                    continue

                                # Track accumulated text for reference
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                pending_text += text
                                pending_text_by_namespace[ns_key] = pending_text

                                # Get or create assistant message for this namespace
                                current_msg = assistant_message_by_namespace.get(ns_key)
                                ev_stats.text_chunks += 1
                                if current_msg is None:
                                    if adapter._set_spinner:
                                        await adapter._set_spinner(SPINNER_LABEL_WRITING)
                                    msg_id = f"asst-{uuid.uuid4().hex[:8]}"
                                    # Mark active BEFORE mounting so pruning
                                    # (triggered by mount) won't remove it
                                    # (_mount_message can trigger
                                    # _prune_old_messages if the window exceeds
                                    # WINDOW_SIZE.)
                                    if adapter._set_active_message:
                                        adapter._set_active_message(msg_id)
                                    current_msg = AssistantMessage(id=msg_id)
                                    await adapter._mount_message(current_msg)
                                    assistant_message_by_namespace[ns_key] = current_msg

                                # Append just the new text chunk for smoother
                                # streaming (batched plain-text updates on the card)
                                await current_msg.append_content(text)

                            elif block_type in {"tool_call_chunk", "tool_call", "tool_use"}:
                                chunk_name = block.get("name")
                                chunk_args = block.get("args")
                                if chunk_args is None and block_type == "tool_use":
                                    chunk_args = block.get("input")
                                chunk_id = block.get("id")
                                chunk_index = block.get("index")

                                buffer_key: str | int
                                if chunk_index is not None:
                                    buffer_key = chunk_index
                                elif chunk_id is not None:
                                    buffer_key = chunk_id
                                else:
                                    buffer_key = f"unknown-{len(tool_call_buffers)}"

                                buffer = tool_call_buffers.setdefault(
                                    buffer_key,
                                    {
                                        "name": None,
                                        "id": None,
                                        "args": None,
                                        "args_parts": [],
                                    },
                                )

                                if chunk_name:
                                    buffer["name"] = chunk_name
                                if chunk_id:
                                    buffer["id"] = chunk_id

                                if isinstance(chunk_args, dict):
                                    buffer["args"] = chunk_args
                                    buffer["args_parts"] = []
                                elif isinstance(chunk_args, str):
                                    if chunk_args:
                                        parts: list[str] = buffer.setdefault("args_parts", [])
                                        if not parts or chunk_args != parts[-1]:
                                            parts.append(chunk_args)
                                        buffer["args"] = "".join(parts)
                                elif chunk_args is not None:
                                    buffer["args"] = chunk_args

                                buffer_name = buffer.get("name")
                                buffer_id = buffer.get("id")
                                if buffer_name is None:
                                    continue

                                lookup_id = str(buffer_id) if buffer_id is not None else ""
                                if not lookup_id and is_step_scope and buffer_name:
                                    bound_step_id = ""
                                    if len(router.active_step_ids) == 1:
                                        bound_step_id = next(iter(router.active_step_ids))
                                    elif adapter._step_by_namespace.get(ns_key) is not None:
                                        bound_step_id = getattr(
                                            adapter._step_by_namespace[ns_key],
                                            "_step_id",
                                            "",
                                        )
                                    if bound_step_id:
                                        lookup_id = predict_main_execute_tool_call_id(
                                            bound_step_id,
                                            tool_call_id=lookup_id,
                                            tool_name=str(buffer_name),
                                            chunk_index=chunk_index,
                                        )
                                raw_args_stream = ""
                                pend_stream = (
                                    pending_tool_calls_lc.get(lookup_id) if lookup_id else None
                                )
                                if isinstance(pend_stream, dict):
                                    raw_args_stream = str(pend_stream.get("args_str", ""))

                                parsed_args: dict[str, Any] = {}
                                args_still_streaming = False
                                raw_args_field = buffer.get("args")
                                if isinstance(raw_args_field, str):
                                    if not raw_args_field.strip():
                                        args_still_streaming = True
                                    else:
                                        try:
                                            loaded = json.loads(raw_args_field)
                                            parsed_args = (
                                                loaded
                                                if isinstance(loaded, dict)
                                                else {"value": loaded}
                                            )
                                        except json.JSONDecodeError:
                                            args_still_streaming = True
                                            parsed_args = {}
                                elif raw_args_field is None:
                                    args_still_streaming = True
                                elif isinstance(raw_args_field, dict):
                                    parsed_args = raw_args_field
                                else:
                                    parsed_args = {"value": raw_args_field}

                                if isinstance(parsed_args, dict):
                                    parsed_args = extract_tool_args_dict(parsed_args)

                                merge_lookup_id = lookup_id
                                if lookup_id and not is_step_scope:
                                    ts_merge = router.resolve_task_scope(ns_key)
                                    merge_lookup_id, _rk = canonical_subgraph_tool_ids(
                                        ns_key, str(lookup_id), task_scope=ts_merge
                                    )
                                    merge_lookup_id = merge_lookup_id or lookup_id
                                if merge_lookup_id:
                                    parsed_args = merge_tool_display_args(
                                        merge_lookup_id,
                                        block_args=parsed_args,
                                        streaming_overlay=streaming_overlay,
                                        pending_tool_calls_lc=pending_tool_calls_lc,
                                        message=message,
                                        tool_name=buffer_name,
                                    )
                                    resolved_tool_name = resolve_stream_tool_name(
                                        lookup_id,
                                        chunk_name=buffer_name,
                                        pending_tool_calls_lc=pending_tool_calls_lc,
                                    )
                                    if resolved_tool_name:
                                        buffer_name = resolved_tool_name
                                        buffer["name"] = resolved_tool_name

                                if tool_args_meaningful(parsed_args):
                                    args_still_streaming = False

                                args_meaningful = tool_args_meaningful(parsed_args)
                                ingest_for_stats = should_ingest_tool_for_step_stats(
                                    is_step_card_scope=is_step_scope,
                                    tool_name=str(buffer_name or ""),
                                    tool_call_id=str(lookup_id or ""),
                                    args_meaningful=args_meaningful,
                                )

                                if args_still_streaming and not ingest_for_stats:
                                    continue

                                # Flush pending text before a meaningful tool call.
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                        router=router,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)

                                if lookup_id and buffer_name and ingest_for_stats:
                                    if buffer_name in FILE_CHANGE_TOOLS and args_meaningful:
                                        file_tcid = str(lookup_id)
                                        if not is_step_scope:
                                            ts_file = router.resolve_task_scope(ns_key)
                                            file_tcid, _fk = canonical_subgraph_tool_ids(
                                                ns_key, file_tcid, task_scope=ts_file
                                            )
                                            file_tcid = file_tcid or str(lookup_id)
                                        track_file_operation(
                                            file_op_tracker,
                                            buffer_name,
                                            parsed_args,
                                            file_tcid,
                                        )
                                        await mount_file_change_preview(
                                            adapter,
                                            tool_name=buffer_name,
                                            args=parsed_args,
                                            tool_call_id=file_tcid,
                                            assistant_id=assistant_id,
                                        )

                                    if is_step_scope and buffer_name == "task":
                                        if not is_inner_subgraph_task_tool_id(str(lookup_id)):
                                            parsed_step_id, _, _, _ = parse_unified_tool_call_id(
                                                str(lookup_id)
                                            )
                                            bound_step_id = parsed_step_id or (
                                                router.step_id_for_tool(str(lookup_id))
                                            )
                                            subagent_card = _ingest_main_task_tool_on_step_card(
                                                adapter,
                                                router,
                                                str(lookup_id),
                                                parsed_args,
                                                bound_step_id=bound_step_id,
                                            )
                                            await _mount_subagent_card_if_needed(
                                                adapter, subagent_card
                                            )
                                    elif is_step_scope and buffer_name != "task":
                                        parsed_sid, _, _, _ = parse_unified_tool_call_id(
                                            str(lookup_id)
                                        )
                                        bound_step_id = parsed_sid or router.step_id_for_tool(
                                            str(lookup_id)
                                        )
                                        active_step = _resolve_step_widget_for_tool(
                                            adapter,
                                            router,
                                            bound_step_id=bound_step_id,
                                            ns_key=ns_key,
                                        )
                                        if active_step is not None:
                                            # Bind the execute namespace to this step card
                                            # so token-usage chunks resolve correctly
                                            # during parallel waves.
                                            _register_execute_namespace_binding(
                                                adapter,
                                                router,
                                                ns_key,
                                                step_id=str(
                                                    getattr(active_step, "_step_id", "")
                                                    or bound_step_id
                                                ),
                                            )
                                            if active_step.has_tool_call_row(lookup_id):
                                                if not ui_coalesce.should_skip_messages_arg_refresh(
                                                    str(lookup_id)
                                                ):
                                                    active_step.update_tool_args(
                                                        lookup_id, parsed_args
                                                    )
                                            else:
                                                _register_main_tool_on_step_card(
                                                    adapter,
                                                    router,
                                                    active_step,
                                                    str(lookup_id),
                                                    buffer_name,
                                                    parsed_args,
                                                    raw_args=raw_args_stream,
                                                )
                                                await _maybe_set_running_tools_spinner(
                                                    adapter,
                                                    clarification_pending=clarification_pending,
                                                )
                                        else:
                                            router.buffer_main_tool(
                                                str(lookup_id),
                                                buffer_name,
                                                parsed_args,
                                                raw_args=raw_args_stream,
                                            )
                                    elif not is_step_scope:
                                        ts_disp = router.resolve_task_scope(ns_key)
                                        _merge_disp, display_key = canonical_subgraph_tool_ids(
                                            ns_key, str(lookup_id), task_scope=ts_disp
                                        )
                                        display_key = display_key or str(lookup_id)
                                        _route_subgraph_tool_call(
                                            adapter,
                                            router,
                                            ns_key=ns_key,
                                            lookup_id=str(lookup_id),
                                            display_key=display_key,
                                            tool_name=buffer_name,
                                            args=parsed_args,
                                            raw_args=raw_args_stream,
                                        )
                                        await _maybe_set_running_tools_spinner(
                                            adapter,
                                            clarification_pending=clarification_pending,
                                        )

                                tool_call_buffers.pop(buffer_key, None)

                        if is_stream_terminal(message):
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            retain_ns = _retain_assistant_ns_on_stream_terminal(
                                message,
                                ns_key=ns_key,
                                assistant_message_by_namespace=assistant_message_by_namespace,
                                is_main_agent=is_main_agent,
                            )
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                    router=router,
                                )
                                pending_text_by_namespace[ns_key] = ""
                            elif retain_ns:
                                current_msg = assistant_message_by_namespace.get(ns_key)
                                if current_msg is not None:
                                    await current_msg.stop_stream()
                                    if adapter._sync_message_content and current_msg.id:
                                        adapter._sync_message_content(
                                            current_msg.id,
                                            current_msg._content,
                                        )
                            if not retain_ns:
                                assistant_message_by_namespace.pop(ns_key, None)

                    elif current_stream_mode == "custom":
                        if isinstance(data, dict):
                            event_type = str(data.get("type", ""))
                            if event_type == TOOL_CALL_UPDATES_BATCH:
                                updates = data.get("updates")
                                if isinstance(updates, list):
                                    for upd in updates:
                                        if isinstance(upd, dict):
                                            await apply_tool_call_wire_update(
                                                adapter,
                                                router,
                                                data=upd,
                                                ns_key=ns_key,
                                                pending_tool_calls_lc=pending_tool_calls_lc,
                                                streaming_overlay=streaming_overlay,
                                                ui_coalesce=ui_coalesce,
                                                file_op_tracker=file_op_tracker,
                                            )
                                continue
                            if await apply_tool_call_wire_update(
                                adapter,
                                router,
                                data=data,
                                ns_key=ns_key,
                                pending_tool_calls_lc=pending_tool_calls_lc,
                                streaming_overlay=streaming_overlay,
                                ui_coalesce=ui_coalesce,
                                file_op_tracker=file_op_tracker,
                            ):
                                continue
                            if event_type.startswith("soothe.error"):
                                error_text = str(
                                    data.get("error") or data.get("message") or "Agent error"
                                )
                                adapter.finalize_pending_tools_with_error(error_text)
                                adapter.finalize_pending_steps_with_error(error_text)
                                await adapter._mount_message(AppMessage(error_text))
                                if adapter._set_spinner:
                                    await adapter._set_spinner(None)
                                continue

                            if event_type == STRANGE_LOOP_STARTED:
                                if not ns_key:
                                    goal_loop_start_monotonic = time.monotonic()
                                    if adapter._set_spinner:
                                        await adapter._set_spinner(
                                            SPINNER_LABEL_THINKING,
                                            turn_start_mono=goal_loop_start_monotonic,
                                            reset_turn_start_only=True,
                                        )
                                    ui_coalesce.execute_wave_active = True
                                    adapter._last_completed_main_step_execute_prose = ""
                                    adapter._last_main_flushed_assistant_prose = ""
                                    goal = str(data.get("goal", "")).strip()
                                    max_iter = int(data.get("max_iterations", 0) or 0)
                                    await _ensure_goal_tree_message(
                                        adapter,
                                        goal=goal,
                                        max_iterations=max_iter,
                                    )
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                        router=router,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)
                                continue

                            if event_type == STREAM_END:
                                scope = str(data.get("scope", ""))
                                if scope == "turn":
                                    await _finalize_goal_completion_streams_on_turn_end(
                                        adapter,
                                        goal_completion_stream_by_namespace=goal_completion_stream_by_namespace,
                                        assistant_message_by_namespace=assistant_message_by_namespace,
                                        goal_loop_start_monotonic=goal_loop_start_monotonic,
                                        turn_start_monotonic=start_time,
                                    )
                                continue

                            if event_type == STRANGE_LOOP_COMPLETED:
                                if not ns_key:
                                    if adapter._goal_tree_message is not None:
                                        adapter._goal_tree_message.set_loop_finished(
                                            status=str(data.get("status", "done")),
                                            goal_progress=str(data.get("goal_progress", "")),
                                            completion_summary=str(
                                                data.get("completion_summary", "")
                                                or data.get("evidence_summary", "")
                                                or ""
                                            ),
                                            total_steps=int(data.get("total_steps", 0) or 0),
                                        )
                                    if not goal_completed_logged:
                                        _log_goal_completed_event_stats(
                                            ev_stats,
                                            turn_stats,
                                            daemon_session,
                                            status=str(data.get("status", "done")),
                                            goal_progress=str(data.get("goal_progress", "")),
                                            total_steps=int(data.get("total_steps", 0) or 0),
                                            elapsed_seconds=time.monotonic() - start_time,
                                        )
                                        goal_completed_logged = True
                                continue

                            if event_type in (
                                LOOP_CLARIFICATION_REQUESTED,
                                LOOP_CLARIFICATION_DEFERRED,
                            ):
                                clarification_pending = True
                                # Persist on the adapter so the next ``send_turn``
                                # attaches ``clarification_answer=True`` and the
                                # input UI can hint at it.
                                adapter._clarification_pending = True
                                if event_type == LOOP_CLARIFICATION_REQUESTED:
                                    raw_questions = data.get("questions") or []
                                    questions_list = [
                                        str(q) for q in raw_questions if str(q).strip()
                                    ]
                                    if questions_list and _should_show_clarification_prompt(
                                        event_data=data,
                                        fallback_mode=clarification_mode,
                                    ):
                                        # The ask_user step card was put into "running" by
                                        # ``step_started`` just before await_clarification.
                                        # Surface the pending questions on it so the user
                                        # knows what to answer.
                                        target_step_id = ""
                                        for (
                                            sid,
                                            step_widget,
                                        ) in adapter._current_step_messages.items():
                                            if step_widget._status == "running":
                                                step_widget.set_awaiting_clarification(
                                                    questions_list
                                                )
                                                target_step_id = sid
                                                break
                                        # Mount the inline answer widget so the
                                        # user has somewhere to type without it
                                        # being mistaken for a new goal.
                                        if target_step_id:
                                            existing = adapter._clarification_input_by_step.get(
                                                target_step_id
                                            )
                                            if existing is None:
                                                widget_id = f"clarify-{uuid.uuid4().hex[:8]}"
                                                input_widget = ClarificationInputMessage(
                                                    step_id=target_step_id,
                                                    questions=questions_list,
                                                    widget_id=widget_id,
                                                    id=widget_id,
                                                )
                                                adapter._clarification_input_by_step[
                                                    target_step_id
                                                ] = input_widget
                                                await adapter._mount_message(input_widget)
                                        if adapter._pause_spinner:
                                            await adapter._pause_spinner(SPINNER_LABEL_INPUT)
                                continue

                            if event_type == LOOP_CLARIFICATION_ANSWERED:
                                clarification_pending = False
                                adapter._clarification_pending = False
                                if adapter._resume_spinner:
                                    await adapter._resume_spinner()
                                continue

                            if event_type == STRANGE_LOOP_PLAN_DECISION and not ns_key:
                                raw_steps = data.get("steps")
                                if isinstance(raw_steps, list):
                                    execution_mode = str(data.get("execution_mode", "")).strip()
                                    adapter._last_plan_execution_mode = execution_mode or None
                                    _record_plan_step_dag(adapter, raw_steps)
                                    adapter._execute_wave_total = len(raw_steps)
                                    done_steps = int(data.get("done_steps", 0) or 0)
                                    adapter._execute_wave_completed = min(
                                        done_steps,
                                        len(raw_steps),
                                    )
                                    await sync_pending_step_cards_from_plan(
                                        adapter,
                                        steps=raw_steps,
                                    )
                                    if adapter._goal_tree_message is None:
                                        await _ensure_goal_tree_message(adapter)
                                    tree = adapter._goal_tree_message
                                    if tree is not None:
                                        tree.sync_plan_steps(raw_steps)
                                        if execution_mode:
                                            tree.set_execution_mode(execution_mode)
                                    if execution_mode == "parallel":
                                        ui_coalesce.execute_wave_active = True
                                continue

                            if event_type == STRANGE_LOOP_STEP_QUEUED:
                                step_id = str(data.get("step_id", "")).strip()
                                description = str(data.get("description", "")).strip()
                                if step_id:
                                    step_widget = adapter._current_step_messages.get(step_id)
                                    if step_widget is None:
                                        step_widget = CognitionStepMessage(
                                            step_id=step_id,
                                            description=description or "(step)",
                                            id=f"step-{uuid.uuid4().hex[:8]}",
                                        )
                                        await adapter._mount_message(step_widget)
                                        adapter._current_step_messages[step_id] = step_widget
                                    elif description:
                                        step_widget.set_description(description)
                                    step_widget.set_queued()
                                    if not ns_key:
                                        _sync_goal_tree_step_phase(
                                            adapter,
                                            step_id,
                                            "queued",
                                            description=description,
                                        )
                                continue

                            if event_type == STRANGE_LOOP_STEP_STARTED:
                                ui_coalesce.execute_wave_active = True
                                step_id = str(data.get("step_id", "")).strip()
                                description = str(data.get("description", "")).strip()
                                logger.debug(
                                    "[STEP_STARTED] received step_id=%s ns=%r",
                                    step_id,
                                    ns_key,
                                )
                                if step_id:
                                    pending_text = pending_text_by_namespace.get(ns_key, "")
                                    if pending_text:
                                        await _flush_assistant_text_ns(
                                            adapter,
                                            pending_text,
                                            ns_key,
                                            assistant_message_by_namespace,
                                            router=router,
                                        )
                                        pending_text_by_namespace[ns_key] = ""
                                        assistant_message_by_namespace.pop(ns_key, None)
                                    _finalize_stuck_dependency_predecessors(
                                        adapter,
                                        router,
                                        next_step_id=step_id,
                                        ns_key=ns_key,
                                    )
                                    _, step_widget = _lookup_step_card(adapter, step_id)
                                    if step_widget is None:
                                        step_widget = CognitionStepMessage(
                                            step_id=step_id,
                                            description=description or "(step)",
                                            id=f"step-{uuid.uuid4().hex[:8]}",
                                        )
                                        await adapter._mount_message(step_widget)
                                        adapter._current_step_messages[step_id] = step_widget
                                    elif description:
                                        step_widget.set_description(description)
                                    step_widget.set_running()
                                    if not ns_key:
                                        _sync_goal_tree_step_phase(
                                            adapter,
                                            step_id,
                                            "running",
                                            description=description,
                                        )
                                    adapter._step_by_namespace[ns_key] = step_widget
                                    router.on_step_started(step_id)
                                    if adapter._set_spinner and not clarification_pending:
                                        await adapter._set_spinner(
                                            SPINNER_LABEL_EXECUTING,
                                            hint_extra=_execute_progress_hint(adapter),
                                        )
                                    logger.debug(
                                        "[STEP_STARTED] step_card step_id=%s ns=%r",
                                        step_id,
                                        ns_key,
                                    )
                                    router.route_pending_main_tools(
                                        adapter._current_step_messages,
                                        adapter._tool_to_step,
                                        adapter._tool_display_by_call_id,
                                    )
                                    router.route_pending_subgraph_tools(
                                        adapter._current_step_messages,
                                        adapter._tool_to_step,
                                        adapter._tool_display_by_call_id,
                                    )

                                    continue

                            if event_type == STRANGE_LOOP_STEP_COMPLETED:
                                step_id = str(data.get("step_id", "")).strip()
                                if step_id:
                                    # Drain buffered tools that still reference this
                                    # step (or its sibling parallel steps) while
                                    # the widget is reachable via
                                    # ``_current_step_messages`` and
                                    # ``active_step_ids`` still includes
                                    # in-flight siblings. Running this BEFORE
                                    # ``on_step_completed`` prevents the
                                    # single-active-step fallback in
                                    # ``route_pending_main_tools`` from
                                    # misrouting non-unified tools to the only
                                    # remaining sibling.
                                    router.route_pending_main_tools(
                                        adapter._current_step_messages,
                                        adapter._tool_to_step,
                                        adapter._tool_display_by_call_id,
                                    )
                                    router.route_pending_subgraph_tools(
                                        adapter._current_step_messages,
                                        adapter._tool_to_step,
                                        adapter._tool_display_by_call_id,
                                    )
                                    router.on_step_completed(step_id)
                                    if adapter._execute_wave_total > 0:
                                        adapter._execute_wave_completed = min(
                                            adapter._execute_wave_completed + 1,
                                            adapter._execute_wave_total,
                                        )
                                    pending_text = pending_text_by_namespace.get(ns_key, "")
                                    if pending_text:
                                        await _flush_assistant_text_ns(
                                            adapter,
                                            pending_text,
                                            ns_key,
                                            assistant_message_by_namespace,
                                            router=router,
                                        )
                                        pending_text_by_namespace[ns_key] = ""
                                        assistant_message_by_namespace.pop(ns_key, None)
                                    success = bool(data.get("success", True))
                                    if success:
                                        _register_successful_step_id(adapter, step_id)
                                    duration_ms = int(data.get("duration_ms", 0))
                                    tool_call_count = int(data.get("tool_call_count", 0))
                                    summary = str(
                                        data.get("summary", "")
                                        or data.get("output_preview", "")
                                        or ""
                                    )
                                    if not summary.strip():
                                        summary = "Failed" if not success else "Done"
                                    _finalize_subagent_cards_for_step(
                                        adapter,
                                        step_id,
                                        success=success,
                                        duration_ms=duration_ms,
                                        summary=summary,
                                    )
                                    widget = _pop_step_card_from_adapter(adapter, step_id)
                                    if widget is None:
                                        logger.warning(
                                            "step.completed for %s but no tracked step card found",
                                            step_id,
                                        )
                                    if widget is not None:
                                        if adapter._step_by_namespace.get(ns_key) is widget:
                                            adapter._step_by_namespace.pop(ns_key, None)
                                        stale_tool_ids = [
                                            k
                                            for k, sw in adapter._tool_to_step.items()
                                            if sw is widget
                                        ]
                                        for k in stale_tool_ids:
                                            adapter._tool_to_step.pop(k, None)
                                        for k, parent in list(
                                            adapter._tool_display_by_call_id.items()
                                        ):
                                            if parent is widget:
                                                adapter._tool_display_by_call_id.pop(k, None)
                                        # Log step completion with tool stats details
                                        _log_step_completion_stats(
                                            logger,
                                            step_id,
                                            widget,
                                            success,
                                            duration_ms,
                                            tool_call_count,
                                        )
                                        widget.set_complete(
                                            success,
                                            duration_ms,
                                            tool_call_count,
                                            summary,
                                        )
                                        if not ns_key and adapter._goal_tree_message is not None:
                                            adapter._goal_tree_message.complete_step(
                                                step_id,
                                                success,
                                                duration_ms,
                                                tool_call_count,
                                                summary,
                                            )
                                        clarification = data.get("clarification")
                                        if isinstance(clarification, dict) and success:
                                            raw_questions = clarification.get("questions") or []
                                            raw_answers = clarification.get("answers") or []
                                            confidence = clarification.get("confidence")
                                            widget.set_clarification_details(
                                                questions=[str(q) for q in raw_questions],
                                                answers=[str(a) for a in raw_answers],
                                                source=str(clarification.get("source") or ""),
                                                confidence=(
                                                    float(confidence)
                                                    if confidence is not None
                                                    else None
                                                ),
                                            )
                                        if not ns_key:
                                            adapter._last_completed_main_step_execute_prose = (
                                                widget.last_completed_execute_prose
                                            )
                                    if adapter._set_spinner and not clarification_pending:
                                        await _maybe_set_thinking_spinner(
                                            adapter,
                                            clarification_pending=clarification_pending,
                                        )
                                    continue

                            # IG-504: Handle LLM retry events for step card status display
                            if event_type == LLM_RETRY_ATTEMPT:
                                # Find the running step card for this thread and update retry status
                                attempt = int(data.get("attempt", 0))
                                max_attempts = int(data.get("max_attempts", 0))
                                error_type = str(data.get("error_type", "timeout"))
                                # Try to find a running step card via namespace or active steps
                                widget = None
                                if ns_key:
                                    widget = adapter._step_by_namespace.get(ns_key)
                                if widget is None:
                                    # Fallback: find any running step in current step messages
                                    for step_widget in adapter._current_step_messages.values():
                                        if step_widget._status == "running":  # noqa: SLF001
                                            widget = step_widget
                                            break
                                if widget is not None:
                                    widget.set_retry_status(attempt, max_attempts, error_type)
                                elif adapter._set_spinner and not clarification_pending:
                                    await adapter._set_spinner(
                                        SPINNER_LABEL_RETRYING,
                                        hint_extra=retry_spinner_hint(
                                            attempt=attempt,
                                            max_attempts=max_attempts,
                                        ),
                                    )
                                continue

                            if event_type == STRANGE_LOOP_PLAN_PHASE:
                                label = str(data.get("label", "")).strip()
                                if label and adapter._set_spinner:
                                    await adapter._set_spinner(map_plan_phase_spinner_label(label))
                                elif label:
                                    adapter._update_status(label)
                                continue

                            if event_type == INTENT_CLASSIFIED_EVENT_TYPE:
                                reasoning = str(data.get("reasoning", "")).strip()
                                if not reasoning:
                                    continue
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                        router=router,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)
                                intent_widget = CognitionReasonMessage(
                                    status="",
                                    iteration=0,
                                    plan_reasoning=reasoning,
                                    id=f"intent-{uuid.uuid4().hex[:8]}",
                                )
                                await adapter._mount_message(intent_widget)
                                continue

                            if event_type == LOOP_REASON_EVENT_TYPE:
                                assessment_reasoning = str(
                                    data.get("assessment_reasoning", "")
                                ).strip()
                                plan_reasoning = str(data.get("plan_reasoning", "")).strip()
                                if not assessment_reasoning and not plan_reasoning:
                                    continue
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                        router=router,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)
                                pa_raw = data.get("plan_action", "")
                                plan_action = pa_raw if pa_raw in ("keep", "new") else ""
                                plan_widget = CognitionReasonMessage(
                                    status=str(data.get("status", "")),
                                    iteration=int(data.get("iteration", 0)),
                                    plan_action=str(plan_action),
                                    assessment_reasoning=assessment_reasoning,
                                    plan_reasoning=plan_reasoning,
                                    id=f"plan-{uuid.uuid4().hex[:8]}",
                                )
                                await adapter._mount_message(plan_widget)
                                continue

                            if ns_key and not is_step_card_tool_scope(ns_key=ns_key):
                                router.on_subgraph_namespace(ns_key)
                            task_scope = router.resolve_task_scope(ns_key)
                            if (
                                task_scope
                                and event_type.startswith("soothe.subagent.")
                                and is_allowlisted_subagent_event_type(event_type)
                            ):
                                if _apply_subagent_wire_step_event(
                                    adapter,
                                    event_type=event_type,
                                    data=data,
                                    task_scope=task_scope,
                                ):
                                    continue
                                _apply_subagent_wire_lifecycle_event(
                                    adapter,
                                    event_type=event_type,
                                    data=data,
                                    task_scope=task_scope,
                                )
                                continue
                finally:
                    await ui_coalesce.after_chunk()

        await run_turn_pipeline(
            chunk_source,
            lambda raw: prepare_turn_chunk(prep_state, raw),
            _apply_turn_chunk,
            latency_stats=ev_stats.latency,
        )

        await ui_coalesce.flush_final()

        # Reset summarization state if stream ended mid-summarization
        # (e.g. middleware error, stream exhausted before regular chunks).
        if summarization_in_progress:
            summarization_in_progress = False
            try:
                await adapter._mount_message(SummarizationMessage())
            except Exception:
                logger.debug(
                    "Failed to mount summarization notification",
                    exc_info=True,
                )
            await _maybe_set_thinking_spinner(adapter, clarification_pending=clarification_pending)

        # Flush any remaining text from all namespaces (IG-426: parallelized)
        flush_tasks: list[Any] = []
        for ns_key, pending_text in list(pending_text_by_namespace.items()):
            if pending_text:
                flush_tasks.append(
                    _flush_assistant_text_ns(
                        adapter,
                        pending_text,
                        ns_key,
                        assistant_message_by_namespace,
                        router=router,
                    )
                )
        if flush_tasks:
            await asyncio.gather(*flush_tasks)
        pending_text_by_namespace.clear()
        assistant_message_by_namespace.clear()
        task_loop_assistant_by_tcid.clear()

        # Buffered tools without a step card: do not mount standalone tool cards.
        routed_main = router.route_pending_main_tools(
            adapter._current_step_messages,
            adapter._tool_to_step,
            adapter._tool_display_by_call_id,
        )
        routed_sub = _route_pending_subgraph_tools(adapter, router)
        pending_sub = router.pending_subgraph_tools()
        if router.pending_main_tool_count or pending_sub:
            logger.debug(
                "Stream-end tool buffer: routed_main=%d dropped_main=%d routed_sub=%d dropped_sub=%d",
                routed_main,
                router.pending_main_tool_count,
                routed_sub,
                len(pending_sub),
            )

        # Safety net: finalize any steps/tools still in-flight (e.g. worker
        # crash sent a soothe.error.* event but step_completed was never
        # emitted, or stream ended before matching results arrived).
        # Skip in three RFC-622 / RFC-623 cases where the loop is
        # intentionally suspended on ``await_clarification`` rather than
        # crashed:
        #   1. The local turn flag is set (``clarification_pending``).
        #   2. The persisted adapter flag is set (the answered event might
        #      have arrived this turn but a fresh request is queued for the
        #      next turn).
        #   3. Any step card is currently in the awaiting-answer ``pending``
        #      state (set by ``set_awaiting_clarification``); finalizing
        #      those would replace the question UI with "Stream ended
        #      unexpectedly".
        awaiting_step = any(
            getattr(w, "_status", "") == "pending" for w in adapter._current_step_messages.values()
        )
        skip_safety_net = (
            clarification_pending
            or bool(getattr(adapter, "_clarification_pending", False))
            or awaiting_step
        )
        if not skip_safety_net:
            stream_end_error = _stream_end_pending_error_message(adapter, daemon_session)
            if adapter._current_step_messages or adapter._tool_to_step:
                adapter.finalize_pending_tools_with_error(stream_end_error)
                adapter.finalize_pending_steps_with_error(stream_end_error)
            elif (
                adapter._goal_tree_message is not None
                and adapter._goal_tree_message._goal_tree_status() == "running"
            ):
                adapter._goal_tree_message.set_interrupted(stream_end_error)
            if stream_end_error == "Stream cancelled" and adapter._set_spinner:
                await adapter._set_spinner(None)

        await dispatch_hook("task.complete", {"loop_id": loop_id})

    except (asyncio.CancelledError, KeyboardInterrupt):
        app_exiting = bool(is_shutting_down()) if is_shutting_down is not None else False
        await _handle_interrupt_cleanup(
            adapter=adapter,
            config=config,
            daemon_session=daemon_session,
            pending_text_by_namespace=pending_text_by_namespace,
            captured_input_tokens=captured_input_tokens,
            captured_output_tokens=captured_output_tokens,
            turn_stats=turn_stats,
            start_time=start_time,
            app_exiting=app_exiting,
        )
        _log_turn_event_stats(ev_stats, turn_stats, daemon_session)
        return turn_stats

    except Exception:
        raise

    # Update token count and return stats
    turn_stats.wall_time_seconds = time.monotonic() - start_time
    _log_turn_event_stats(ev_stats, turn_stats, daemon_session)

    await _report_and_persist_tokens(
        adapter,
        config,
        captured_input_tokens,
        captured_output_tokens,
        daemon_session=daemon_session,
    )
    return turn_stats


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "TextualUIAdapter",
    "execute_task_textual",
    "print_usage_table",
    "ModelStats",
    "SessionStats",
    "SpinnerStatus",
    "format_token_count",
    "STRANGE_LOOP_COMPLETED",
    "STRANGE_LOOP_STARTED",
    "STRANGE_LOOP_STEP_COMPLETED",
    "STRANGE_LOOP_STEP_QUEUED",
    "STRANGE_LOOP_STEP_STARTED",
    "TurnToolUiCoalescer",
]

_LAZY_EXPORTS: dict[str, str] = {
    "_expand_nonstandard_tool_blocks": "_expand_nonstandard_tool_blocks",
    "_handle_interrupt_cleanup": "_handle_interrupt_cleanup",
    "_tui_effective_ai_blocks": "_tui_effective_ai_blocks",
    "_tui_goal_completion_matches_prior_main_visible_answer": (
        "_tui_goal_completion_matches_prior_main_visible_answer"
    ),
}


def __getattr__(name: str) -> Any:
    if name == "_repair_concatenated_output_text":
        fn = RendererBase.repair_concatenated_output
        globals()[name] = fn
        return fn
    if name in _LAZY_EXPORTS:
        attr = _LAZY_EXPORTS[name]
        value = globals()[attr]
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
