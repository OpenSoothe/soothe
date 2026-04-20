"""Textual UI adapter for agent execution."""
# This module has complex streaming logic ported from execution.py

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path
    from typing import Protocol

    from langchain.agents.middleware.human_in_the_loop import (
        ApproveDecision,
        EditDecision,
        HITLRequest,
        RejectDecision,
    )
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.types import Command, Interrupt
    from pydantic import TypeAdapter
    from rich.console import Console

    from soothe_cli.tui._ask_user_types import AskUserWidgetResult, Question

    # Type alias matching HITLResponse["decisions"] element type
    HITLDecision = ApproveDecision | EditDecision | RejectDecision

    class _TokensUpdateCallback(Protocol):
        """Callback signature for `_on_tokens_update`."""

        def __call__(self, count: int, *, approximate: bool = False) -> None: ...

    class _TokensShowCallback(Protocol):
        """Callback signature for `_on_tokens_show`."""

        def __call__(self, *, approximate: bool = False) -> None: ...


from soothe_sdk.langchain_wire import envelope_langchain_message_dict

from soothe_cli.cli.stream.display_line import DisplayLine
from soothe_cli.shared.essential_events import (
    LOOP_REASON_EVENT_TYPE,
    is_essential_progress_event_type,
)
from soothe_cli.shared.message_processing import accumulate_tool_call_chunks, extract_tool_args_dict
from soothe_cli.shared.subagent_routing import parse_subagent_from_input
from soothe_cli.shared.tool_call_resolution import build_streaming_args_overlay
from soothe_cli.shared.tool_card_payload import extract_tool_result_card_payload
from soothe_cli.tui._ask_user_types import AskUserRequest
from soothe_cli.tui._cli_context import CLIContext  # noqa: TC001
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
from soothe_cli.tui.config import build_stream_config
from soothe_cli.tui.file_ops import FileOpTracker
from soothe_cli.tui.formatting import format_duration
from soothe_cli.tui.hooks import dispatch_hook
from soothe_cli.tui.input import MediaTracker, parse_file_mentions
from soothe_cli.tui.media_utils import create_multimodal_content
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    CognitionGoalTreeMessage,
    CognitionPlanReasonMessage,
    CognitionStepMessage,
    DiffMessage,
    SummarizationMessage,
    ToolCallMessage,
)

logger = logging.getLogger(__name__)

AGENT_LOOP_STEP_STARTED = "soothe.cognition.agent_loop.step.started"
AGENT_LOOP_STEP_COMPLETED = "soothe.cognition.agent_loop.step.completed"
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


def print_usage_table(
    stats: SessionStats,
    wall_time: float,
    console: Console,
) -> None:
    """Print a model-usage stats table to a Rich console.

    When the session spans multiple models each gets its own row with a
    totals row appended; single-model sessions show one row.

    Args:
        stats: Cumulative session stats.
        wall_time: Total wall-clock time in seconds.
        console: Rich console for output.
    """
    from rich.table import Table

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


def _is_summarization_chunk(metadata: dict | None) -> bool:
    """Check if a message chunk is from summarization middleware.

    The summarization model is invoked with
    `config={"metadata": {"lc_source": "summarization"}}`
    (see `langchain.agents.middleware.summarization`), which
    LangChain's callback system merges into the stream metadata dict.

    Args:
        metadata: The metadata dict from the stream chunk.

    Returns:
        Whether the chunk is from summarization and should be filtered.
    """
    if metadata is None:
        return False
    return metadata.get("lc_source") == "summarization"


def _extract_custom_output_text(data: dict[str, Any]) -> str | None:
    """Extract assistant-visible text from daemon custom output events."""
    from soothe_sdk.events import (
        AGENT_LOOP_COMPLETED,
        CHITCHAT_RESPONSE,
        FINAL_REPORT,
    )
    from soothe_sdk.ux import strip_internal_tags

    event_type = str(data.get("type", ""))
    if event_type == CHITCHAT_RESPONSE:
        content = data.get("content", "")
        cleaned = strip_internal_tags(str(content))
        return cleaned or None
    if event_type == AGENT_LOOP_COMPLETED:
        content = data.get("final_stdout_message", "")
        cleaned = strip_internal_tags(str(content))
        return cleaned or None
    if event_type == FINAL_REPORT:
        content = data.get("content", data.get("summary", ""))
        cleaned = strip_internal_tags(str(content))
        return cleaned or None
    return None


def _format_display_line_for_tui(line: DisplayLine) -> str:
    """Serialize pipeline ``DisplayLine`` for TUI widgets.

    Leading spaces encode parent/child layout (step result vs step header, etc.).
    Strips only newline separators and trailing whitespace.
    """
    return line.format().lstrip("\n").rstrip()


def _format_progress_event_lines_for_tui(
    event_data: dict[str, Any],
    namespace: tuple[str, ...],
    *,
    pipeline: Any,
) -> list[str]:
    """Format progress events with the same pipeline as CLI.

    ``StreamDisplayPipeline`` applies verbosity tiers: NORMAL milestones
    (e.g. ``browser.started``) vs DETAILED internals (e.g. ``browser.step.running``).
    """
    event_type = str(event_data.get("type", ""))

    # Essential progress events (goal/step/reason) - always show
    if is_essential_progress_event_type(event_type):
        event_for_pipeline = dict(event_data)
        event_for_pipeline["namespace"] = list(namespace)
        lines = pipeline.process(event_for_pipeline)

        rendered: list[str] = []
        for line in lines:
            line_text = _format_display_line_for_tui(line)
            if line_text:
                rendered.append(line_text)
        return rendered

    # All soothe.capability.* events — pipeline classifies NORMAL vs DETAILED
    # (browser step.running, claude text.running, etc. need DETAILED verbosity)
    if event_type.startswith("soothe.capability."):
        event_for_pipeline = dict(event_data)
        event_for_pipeline["namespace"] = list(namespace)
        lines = pipeline.process(event_for_pipeline)

        rendered: list[str] = []
        for line in lines:
            line_text = _format_display_line_for_tui(line)
            if line_text:
                rendered.append(line_text)
        return rendered

    return []


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
        """Map of tool call IDs to their message widgets."""

        self._current_step_messages: dict[str, CognitionStepMessage] = {}
        """Map of agent-loop act step IDs to step card widgets."""

        self._goal_tree_by_namespace: dict[tuple[Any, ...], CognitionGoalTreeMessage] = {}
        """Live Goal→steps tree card per stream namespace (agentic Layer 2)."""

        # Token display callbacks (set by the app after construction)
        self._on_tokens_update: _TokensUpdateCallback | None = None
        """Called with total context tokens after each LLM response."""

        self._on_tokens_hide: Callable[[], None] | None = None
        """Called to hide the token display during streaming."""

        self._on_tokens_show: _TokensShowCallback | None = None
        """Called to restore the token display with the cached value."""

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

        # Clear active streaming message to avoid stale "active" state in the store.
        if self._set_active_message:
            self._set_active_message(None)

    def finalize_pending_steps_with_error(self, message: str) -> None:
        """Mark in-flight step cards as interrupted and clear tracking."""
        for step_msg in list(self._current_step_messages.values()):
            step_msg.set_interrupted(message)
        self._current_step_messages.clear()
        for tree in list(self._goal_tree_by_namespace.values()):
            tree.set_interrupted(message)
        self._goal_tree_by_namespace.clear()


def _build_interrupted_ai_message(
    pending_text_by_namespace: dict[tuple, str],
    current_tool_messages: dict[str, Any],
) -> AIMessage | None:
    """Build an AIMessage capturing interrupted state (text + tool calls).

    Args:
        pending_text_by_namespace: Dict of accumulated text by namespace
        current_tool_messages: Dict of tool_id -> ToolCallMessage widget

    Returns:
        AIMessage with accumulated content and tool calls, or None if empty.
    """
    from langchain_core.messages import AIMessage

    main_ns_key = ()
    accumulated_text = pending_text_by_namespace.get(main_ns_key, "").strip()

    # Reconstruct tool_calls from displayed tool messages
    tool_calls = []
    for tool_id, tool_widget in list(current_tool_messages.items()):
        tool_calls.append(
            {
                "id": tool_id,
                "name": tool_widget._tool_name,
                "args": tool_widget._args,
            }
        )

    if not accumulated_text and not tool_calls:
        return None

    return AIMessage(
        content=accumulated_text,
        tool_calls=tool_calls or [],
    )


def _read_mentioned_file(file_path: Path, max_embed_bytes: int) -> str:
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


def _normalize_lc_stream_message(message: Any) -> Any:
    """Turn daemon JSON dicts into LangChain message objects when possible.

    ``DaemonSession._normalize_stream_data`` already does this; this is a safety net
    for any path that still yields a raw dict (restore failure, alternate transports).
    """
    if not isinstance(message, dict):
        return message
    try:
        from langchain_core.messages import messages_from_dict

        wrapped = envelope_langchain_message_dict(message)
        restored = messages_from_dict([wrapped])
        if restored:
            return restored[0]
    except Exception:
        logger.debug("TUI could not restore LangChain message from dict", exc_info=True)
    return message


def _coerce_ai_message_for_blocks(message: Any) -> Any:
    """Best-effort dict → ``AIMessage`` / ``AIMessageChunk`` for block extraction.

    If the wire payload uses ``type: \"AIMessage\"`` (class name) instead of ``ai``,
    :func:`messages_from_dict` would fail; :func:`envelope_langchain_message_dict`
    canonicalizes first (see ``daemon_session``).
    """
    from langchain_core.messages import AIMessage, AIMessageChunk, messages_from_dict

    if isinstance(message, (AIMessage, AIMessageChunk)):
        return message
    if not isinstance(message, dict):
        return message
    try:
        wrapped = envelope_langchain_message_dict(message)
        restored = messages_from_dict([wrapped])
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


def _defer_tool_card_for_empty_streaming_args(message: Any) -> bool:
    """True when more tool args may arrive on a later ``AIMessageChunk``."""
    from langchain_core.messages import AIMessageChunk

    if not isinstance(message, AIMessageChunk):
        return False
    return getattr(message, "chunk_position", None) != "last"


def _defer_first_tool_card_mount_until_final_stream_chunk(message: Any) -> bool:
    """True when the first tool card for this call should wait for a terminal chunk.

    Mounting only on the final ``AIMessageChunk`` avoids header flicker when name/args
    are refined across chunks. Chunks with no ``chunk_position`` use legacy behavior
    (mount as soon as args are meaningful) so streams that never mark ``last`` still work.
    """
    from langchain_core.messages import AIMessageChunk

    if not isinstance(message, AIMessageChunk):
        return False
    pos = getattr(message, "chunk_position", None)
    if pos == "last":
        return False
    if pos is None:
        return False
    return True


def _tui_effective_ai_blocks(
    message: Any,
    *,
    ns_key: tuple[Any, ...],
    direct_subagent_turn: bool,
    streaming_overlay: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build content blocks for TUI streaming (text + tool calls).

    Tool kwargs are merged in
    :func:`soothe_cli.shared.tool_call_resolution.materialize_ai_blocks_with_resolved_tools`.
    """
    from langchain_core.messages import AIMessage, AIMessageChunk

    from soothe_cli.shared.tool_call_resolution import materialize_ai_blocks_with_resolved_tools

    message = _coerce_ai_message_for_blocks(message)
    if not isinstance(message, (AIMessage, AIMessageChunk)):
        return []

    allow_plain_string = (not ns_key) or direct_subagent_turn
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


async def execute_task_textual(
    user_input: str,
    agent: Any,  # noqa: ANN401  # Dynamic agent graph type
    assistant_id: str | None,
    session_state: Any,  # noqa: ANN401  # Dynamic session state type
    adapter: TextualUIAdapter,
    image_tracker: MediaTracker | None = None,
    context: CLIContext | None = None,
    *,
    daemon_session: Any = None,  # noqa: ANN401  # Daemon-backed TUI session
    sandbox_type: str | None = None,
    message_kwargs: dict[str, Any] | None = None,
    turn_stats: SessionStats | None = None,
    skip_daemon_send_turn: bool = False,
) -> SessionStats:
    """Execute a task with output directed to Textual UI.

    This is the Textual-compatible version of execute_task() that uses
    the TextualUIAdapter for all UI operations.

    Args:
        user_input: The user's input message
        agent: The LangGraph agent to execute
        daemon_session: Optional daemon-backed session for direct websocket
            streaming. When provided, this becomes the primary execution path.
        assistant_id: The agent identifier
        session_state: Session state with auto_approve flag
        adapter: The TextualUIAdapter for UI operations
        image_tracker: Optional tracker for images
        context: Optional `CLIContext` with model override and params, passed
            to the graph via `context=`.
        sandbox_type: Sandbox provider name for trace metadata, or `None`
            if no sandbox is active.
        message_kwargs: Extra fields merged into the stream input message
            dict (e.g., `additional_kwargs` for persisting skill metadata
            in the checkpoint).
        turn_stats: Pre-created `SessionStats` to accumulate into.

            When the caller holds a reference to the same object, stats are
            available even if this coroutine is cancelled before it can return.

            If `None`, a new instance is created internally.
        skip_daemon_send_turn: When ``True`` with ``daemon_session`` set, skip
            ``send_turn`` and only consume chunks (daemon already queued the
            prompt, e.g. after ``invoke_skill``).

    Note:
        Progress verbosity (``quiet`` … ``debug``) for tool UI and the stream
        pipeline is read from ``cli_config.yml`` via
        :func:`soothe_cli.shared.load_config`.

    Returns:
        Stats accumulated over this turn (request count, token counts,
            wall-clock time).

    Raises:
        ValidationError: If HITL request validation fails (re-raised).
    """
    from langchain.agents.middleware.human_in_the_loop import (
        ApproveDecision,
        HITLRequest,
        RejectDecision,
    )
    from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
    from langgraph.types import Command
    from pydantic import ValidationError

    from soothe_cli.cli.stream import StreamDisplayPipeline
    from soothe_cli.shared.config_loader import load_config
    from soothe_cli.shared.display_policy import normalize_verbosity, should_show_tool_call_ui

    hitl_request_adapter = _get_hitl_request_adapter(HITLRequest)
    ask_user_adapter = _get_ask_user_adapter()
    pv = normalize_verbosity(load_config().verbosity)
    show_tool_ui = should_show_tool_call_ui(pv)
    logger.debug(
        "TUI turn: verbosity=%r show_tool_ui=%s (tool-call rows follow this flag)",
        pv,
        show_tool_ui,
    )
    progress_pipeline = StreamDisplayPipeline(verbosity=pv)

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

    thread_id = session_state.thread_id
    config = build_stream_config(thread_id, assistant_id, sandbox_type=sandbox_type)

    await dispatch_hook("session.start", {"thread_id": thread_id})

    captured_input_tokens = 0
    captured_output_tokens = 0
    if turn_stats is None:
        turn_stats = SessionStats()
    start_time = time.monotonic()

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
        await adapter._set_spinner("Thinking")

    # Hide token display during streaming (will be shown with accurate count at end)
    if adapter._on_tokens_hide:
        adapter._on_tokens_hide()

    file_op_tracker = FileOpTracker(assistant_id=assistant_id)
    displayed_tool_ids: set[str] = set()
    tool_call_buffers: dict[str | int, dict] = {}
    # Streaming tool-call args (``tool_call_chunks``) — mirrors EventProcessor / IG-053
    pending_tool_calls_lc: dict[str, dict[str, Any]] = {}

    # Track pending text and assistant messages PER NAMESPACE to avoid interleaving
    # when multiple subagents stream in parallel
    pending_text_by_namespace: dict[tuple, str] = {}
    assistant_message_by_namespace: dict[tuple, Any] = {}

    # Clear media from tracker after creating the message
    if image_tracker:
        image_tracker.clear()

    user_msg: dict[str, Any] = {"role": "user", "content": message_content}
    if message_kwargs:
        user_msg.update(message_kwargs)
    stream_input: dict | Command = {"messages": [user_msg]}

    # Track summarization lifecycle so spinner status and notification stay in sync.
    summarization_in_progress = False
    # True when this daemon turn used explicit /browser, /claude, or /research routing
    # (``send_turn(..., subagent=...)``). Replies stream on subgraph namespaces, not ().
    direct_subagent_turn = False

    try:
        while True:
            interrupt_occurred = False
            suppress_resumed_output = False
            pending_interrupts: dict[str, HITLRequest] = {}
            pending_ask_user: dict[str, AskUserRequest] = {}

            if daemon_session is None:
                chunk_source = agent.astream(
                    stream_input,
                    stream_mode=["messages", "updates"],
                    subgraphs=True,
                    config=config,
                    context=context,
                    durability="exit",
                )
            else:
                if isinstance(stream_input, Command):
                    resume_data = getattr(stream_input, "resume", None)
                    if not isinstance(resume_data, dict):
                        raise ValueError("Invalid daemon resume payload")
                    await daemon_session.resume_interrupts(resume_data)
                    chunk_source = daemon_session.iter_turn_chunks()
                elif skip_daemon_send_turn:
                    chunk_source = daemon_session.iter_turn_chunks()
                else:
                    daemon_text = (
                        message_content if isinstance(message_content, str) else final_input
                    )
                    subagent_name, routed_text = parse_subagent_from_input(
                        daemon_text if isinstance(daemon_text, str) else final_input
                    )
                    direct_subagent_turn = subagent_name is not None
                    ctx_model = context.get("model") if context else None
                    raw_mp = context.get("model_params") if context else None
                    mp = raw_mp if isinstance(raw_mp, dict) else None
                    await daemon_session.send_turn(
                        routed_text,
                        interactive=True,
                        subagent=subagent_name,
                        model=ctx_model
                        if isinstance(ctx_model, str) and ctx_model.strip()
                        else None,
                        model_params=mp,
                    )
                    chunk_source = daemon_session.iter_turn_chunks()

            async for chunk in chunk_source:
                if not isinstance(chunk, tuple) or len(chunk) != 3:  # noqa: PLR2004  # stream chunk is a 3-tuple (namespace, mode, data)
                    logger.debug("Skipping non-3-tuple chunk: %s", type(chunk).__name__)
                    continue

                namespace, current_stream_mode, data = chunk

                # Convert namespace to hashable tuple for dict keys
                ns_key = tuple(namespace) if namespace else ()

                # Root graph uses namespace ``()``; delegated subgraphs use non-empty
                # namespaces. Assistant *text* from subgraphs is suppressed unless the
                # user routed with /browser|/claude|/research (avoids duplicate prose).
                # Tool-call UI is gated by ``show_tool_ui`` (logging verbosity), not namespace.
                is_main_agent = ns_key == ()
                suppress_subgraph_assistant_text = (not is_main_agent) and (
                    not direct_subagent_turn
                )

                # Handle UPDATES stream - for interrupts and todos
                if current_stream_mode == "updates":
                    if not isinstance(data, dict):
                        continue

                    # Check for interrupts
                    if "__interrupt__" in data:
                        interrupts: list[Interrupt] = data["__interrupt__"]
                        if interrupts:
                            for interrupt_obj in interrupts:
                                iv = interrupt_obj.value
                                if isinstance(iv, dict) and iv.get("type") == "ask_user":
                                    try:
                                        validated_ask_user = ask_user_adapter.validate_python(iv)
                                        pending_ask_user[interrupt_obj.id] = validated_ask_user
                                        interrupt_occurred = True
                                        await dispatch_hook("input.required", {})
                                    except ValidationError:
                                        logger.exception("Invalid ask_user interrupt payload")
                                        raise
                                else:
                                    try:
                                        validated_request = hitl_request_adapter.validate_python(iv)
                                        pending_interrupts[interrupt_obj.id] = validated_request
                                        interrupt_occurred = True
                                        await dispatch_hook("input.required", {})
                                    except ValidationError:  # noqa: TRY203  # Re-raise preserves exception context in handler
                                        raise

                    # Check for todo updates (not yet implemented in Textual UI)
                    chunk_data = next(iter(data.values())) if data else None
                    if chunk_data and isinstance(chunk_data, dict) and "todos" in chunk_data:
                        pass  # Future: render todo list widget

                # Handle MESSAGES stream - for content and tool calls
                elif current_stream_mode == "messages":
                    if not isinstance(data, tuple) or len(data) != 2:  # noqa: PLR2004  # message stream data is a 2-tuple (message, metadata)
                        logger.debug(
                            "Skipping non-2-tuple message data: type=%s",
                            type(data).__name__,
                        )
                        continue

                    message, metadata = data
                    message = _normalize_lc_stream_message(message)

                    # Filter out summarization model output, but keep UI feedback.
                    # The summarization model streams AIMessage chunks tagged
                    # with lc_source="summarization" in the callback metadata.
                    # These are hidden from the user; only the spinner and a
                    # notification widget provide feedback.
                    if _is_summarization_chunk(metadata):
                        if not summarization_in_progress:
                            summarization_in_progress = True
                            if adapter._set_spinner:
                                await adapter._set_spinner("Offloading")
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
                        if adapter._set_spinner and not adapter._current_tool_messages:
                            await adapter._set_spinner("Thinking")

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
                            )
                            pending_text_by_namespace[ns_key] = ""
                        continue

                    tool_card = extract_tool_result_card_payload(message)
                    if tool_card is not None:
                        tool_id = tool_card.tool_call_id or None
                        if tool_id:
                            pending_tool_calls_lc.pop(str(tool_id), None)

                        if not show_tool_ui:
                            logger.debug(
                                "Tool result skipped (tool UI off): tool_call_id=%r name=%r",
                                tool_id,
                                tool_card.tool_name,
                            )
                            continue

                        if not tool_id:
                            logger.debug(
                                "Tool result has no tool_call_id (cannot match card): name=%r",
                                tool_card.tool_name,
                            )

                        record = file_op_tracker.complete_with_message(message)

                        # Update tool call status with output (unified ToolMessage / wire dict)
                        sid = str(tool_id) if tool_id else ""
                        if sid and sid in adapter._current_tool_messages:
                            # Pop before widget calls so the dict drains even
                            # if set_success/set_error raises.
                            tool_msg = adapter._current_tool_messages.pop(sid)
                            output_str = tool_card.output_display
                            logger.debug(
                                "Tool result matched pending card: tool_call_id=%s name=%s error=%s",
                                sid,
                                tool_msg._tool_name,
                                tool_card.is_error,
                            )
                            if not tool_card.is_error:
                                tool_msg.set_success(output_str)
                            else:
                                tool_msg.set_error(output_str or "Error")
                                await dispatch_hook(
                                    "tool.error",
                                    {"tool_names": [tool_msg._tool_name]},
                                )
                        elif tool_id and show_tool_ui:
                            # Orphan result: no prior AIMessage tool card (daemon wire
                            # shape, streaming chunks, or missing tool_call blocks).
                            # ``extract_tool_result_card_payload`` normalizes name + id;
                            # ``ToolCallMessage`` applies the same id→name inference as cards.
                            tname = tool_card.tool_name or "tool"
                            logger.debug(
                                "Tool result orphan (no pending card): tool_call_id=%s name=%s",
                                tool_id,
                                tname,
                            )
                            orphan = ToolCallMessage(
                                tname,
                                {},
                                tool_call_id=str(tool_id),
                            )
                            await adapter._mount_message(orphan)
                            output_str = tool_card.output_display
                            if not tool_card.is_error:
                                orphan.set_success(output_str)
                            else:
                                orphan.set_error(output_str or "Error")
                                await dispatch_hook(
                                    "tool.error",
                                    {"tool_names": [orphan._tool_name]},
                                )

                        # Reshow spinner only when all in-flight tools have
                        # completed (avoids premature "Thinking..." when
                        # parallel tool calls are active).
                        if adapter._set_spinner and not adapter._current_tool_messages:
                            await adapter._set_spinner("Thinking")

                        # Show file operation results - always show diffs in chat
                        if record:
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                )
                                pending_text_by_namespace[ns_key] = ""
                            if record.diff:
                                await adapter._mount_message(
                                    DiffMessage(record.diff, record.display_path)
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
                            elif total_toks:
                                # Fallback: model gives only total (no split)
                                turn_stats.record_request(active_model, total_toks, 0)
                                captured_input_tokens = max(captured_input_tokens, total_toks)

                    streaming_overlay: dict[str, dict[str, Any]] = {}
                    if isinstance(message, (AIMessage, AIMessageChunk)):
                        accumulate_tool_call_chunks(
                            pending_tool_calls_lc,
                            getattr(message, "tool_call_chunks", None) or [],
                            is_main=(ns_key == ()),
                        )
                        streaming_overlay = build_streaming_args_overlay(
                            message, pending_tool_calls_lc
                        )

                    blocks = _tui_effective_ai_blocks(
                        message,
                        ns_key=ns_key,
                        direct_subagent_turn=direct_subagent_turn,
                        streaming_overlay=streaming_overlay or None,
                    )
                    if not blocks:
                        continue

                    for block in blocks:
                        block_type = block.get("type")

                        if block_type == "text":
                            if suppress_subgraph_assistant_text:
                                continue
                            text = block.get("text", "")
                            if text:
                                # Track accumulated text for reference
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                pending_text += text
                                pending_text_by_namespace[ns_key] = pending_text

                                # Get or create assistant message for this namespace
                                current_msg = assistant_message_by_namespace.get(ns_key)
                                if current_msg is None:
                                    # Hide spinner when assistant starts responding
                                    if adapter._set_spinner:
                                        await adapter._set_spinner(None)
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
                                # streaming (uses MarkdownStream internally for
                                # better performance)
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

                            parsed_args = buffer.get("args")
                            if isinstance(parsed_args, str):
                                if not parsed_args:
                                    continue
                                try:
                                    parsed_args = json.loads(parsed_args)
                                except json.JSONDecodeError:
                                    continue
                            elif parsed_args is None:
                                continue

                            if not isinstance(parsed_args, dict):
                                parsed_args = {"value": parsed_args}

                            if isinstance(parsed_args, dict):
                                parsed_args = extract_tool_args_dict(parsed_args)

                            lookup_id = str(buffer_id) if buffer_id is not None else ""

                            # Flush pending text before tool call
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)

                            args_meaningful = bool(parsed_args)
                            if not args_meaningful and _defer_tool_card_for_empty_streaming_args(
                                message
                            ):
                                # Keep buffer; a later chunk should carry real kwargs.
                                logger.debug(
                                    "Tool call card deferred (streaming args incomplete): "
                                    "name=%s id=%r chunk_position=%r",
                                    buffer_name,
                                    chunk_id,
                                    getattr(message, "chunk_position", None),
                                )
                                continue

                            if (
                                lookup_id
                                and args_meaningful
                                and lookup_id in adapter._current_tool_messages
                            ):
                                existing = adapter._current_tool_messages[lookup_id]
                                existing.refresh_tool_args(parsed_args)
                                logger.debug(
                                    "Tool call args refreshed on existing card: id=%s name=%s",
                                    lookup_id,
                                    buffer_name,
                                )
                                tool_call_buffers.pop(buffer_key, None)
                                continue

                            if lookup_id and lookup_id not in displayed_tool_ids:
                                if _defer_first_tool_card_mount_until_final_stream_chunk(message):
                                    logger.debug(
                                        "Tool call first mount deferred (non-final stream chunk): "
                                        "name=%s tool_call_id=%r chunk_position=%r",
                                        buffer_name,
                                        lookup_id,
                                        getattr(message, "chunk_position", None),
                                    )
                                    continue
                                displayed_tool_ids.add(lookup_id)
                                if show_tool_ui:
                                    file_op_tracker.start_operation(
                                        buffer_name, parsed_args, buffer_id
                                    )

                                    # Hide spinner before showing tool call
                                    if adapter._set_spinner:
                                        await adapter._set_spinner(None)

                                    # Mount tool call message
                                    tool_msg = ToolCallMessage(
                                        buffer_name,
                                        parsed_args,
                                        tool_call_id=lookup_id,
                                    )
                                    logger.debug(
                                        "Tool call card mounted: name=%s tool_call_id=%s "
                                        "namespace=%s direct_subagent_turn=%s",
                                        buffer_name,
                                        lookup_id,
                                        ns_key,
                                        direct_subagent_turn,
                                    )
                                    await adapter._mount_message(tool_msg)
                                    adapter._current_tool_messages[lookup_id] = tool_msg
                                else:
                                    logger.debug(
                                        "Tool call block not shown as card (tool UI off): "
                                        "name=%s tool_call_id=%s",
                                        buffer_name,
                                        lookup_id,
                                    )
                            elif show_tool_ui and args_meaningful and buffer_name and not lookup_id:
                                logger.debug(
                                    "Tool call has no stable id; card not mounted: "
                                    "name=%s namespace=%s",
                                    buffer_name,
                                    ns_key,
                                )

                            tool_call_buffers.pop(buffer_key, None)

                    if getattr(message, "chunk_position", None) == "last":
                        pending_text = pending_text_by_namespace.get(ns_key, "")
                        if pending_text:
                            await _flush_assistant_text_ns(
                                adapter,
                                pending_text,
                                ns_key,
                                assistant_message_by_namespace,
                            )
                            pending_text_by_namespace[ns_key] = ""
                            assistant_message_by_namespace.pop(ns_key, None)

                elif current_stream_mode == "custom":
                    if isinstance(data, dict):
                        event_type = str(data.get("type", ""))
                        if event_type.startswith("soothe.error"):
                            error_text = str(
                                data.get("error") or data.get("message") or "Agent error"
                            )
                            await adapter._mount_message(AppMessage(error_text))
                            if adapter._set_spinner:
                                await adapter._set_spinner(None)
                            continue

                        if event_type == AGENT_LOOP_GOAL_STARTED:
                            goal = str(data.get("goal", "")).strip()
                            max_it = int(data.get("max_iterations", 0))
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)
                            tree = CognitionGoalTreeMessage(
                                goal=goal or "(goal)",
                                max_iterations=max_it,
                                id=f"goaltree-{uuid.uuid4().hex[:8]}",
                            )
                            adapter._goal_tree_by_namespace[ns_key] = tree
                            await adapter._mount_message(tree)
                            continue

                        if event_type == AGENT_LOOP_GOAL_COMPLETED:
                            tr = adapter._goal_tree_by_namespace.get(ns_key)
                            if tr is not None:
                                tr.set_loop_finished(
                                    status=str(data.get("status", "")),
                                    goal_progress=float(data.get("goal_progress", 0.0)),
                                    completion_summary=str(data.get("completion_summary", "")),
                                    total_steps=int(data.get("total_steps", 0)),
                                )
                                adapter._goal_tree_by_namespace.pop(ns_key, None)

                        if output_text := _extract_custom_output_text(data):
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)
                            output_widget = AssistantMessage(
                                output_text, id=f"asst-{uuid.uuid4().hex[:8]}"
                            )
                            await adapter._mount_message(output_widget)
                            await output_widget.write_initial_content()
                            if adapter._sync_message_content and output_widget.id:
                                adapter._sync_message_content(output_widget.id, output_text)
                            if adapter._set_active_message:
                                adapter._set_active_message(None)
                            if adapter._set_spinner:
                                await adapter._set_spinner(None)
                            continue

                        if event_type == AGENT_LOOP_STEP_STARTED:
                            step_id = str(data.get("step_id", "")).strip()
                            description = str(data.get("description", "")).strip()
                            if step_id:
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)
                                goal_tree = adapter._goal_tree_by_namespace.get(ns_key)
                                if goal_tree is not None:
                                    goal_tree.add_step_running(step_id, description or "(step)")
                                    continue
                                step_widget = CognitionStepMessage(
                                    step_id=step_id,
                                    description=description or "(step)",
                                    id=f"step-{uuid.uuid4().hex[:8]}",
                                )
                                await adapter._mount_message(step_widget)
                                step_widget.set_running()
                                adapter._current_step_messages[step_id] = step_widget
                                continue

                        if event_type == AGENT_LOOP_STEP_COMPLETED:
                            step_id = str(data.get("step_id", "")).strip()
                            if step_id:
                                pending_text = pending_text_by_namespace.get(ns_key, "")
                                if pending_text:
                                    await _flush_assistant_text_ns(
                                        adapter,
                                        pending_text,
                                        ns_key,
                                        assistant_message_by_namespace,
                                    )
                                    pending_text_by_namespace[ns_key] = ""
                                    assistant_message_by_namespace.pop(ns_key, None)
                                success = bool(data.get("success", True))
                                duration_ms = int(data.get("duration_ms", 0))
                                tool_call_count = int(data.get("tool_call_count", 0))
                                summary = str(
                                    data.get("summary", "") or data.get("output_preview", "") or ""
                                )
                                if not summary.strip():
                                    summary = "Failed" if not success else "Done"
                                goal_tree = adapter._goal_tree_by_namespace.get(ns_key)
                                if goal_tree is not None:
                                    goal_tree.complete_step(
                                        step_id,
                                        success,
                                        duration_ms,
                                        tool_call_count,
                                        summary,
                                    )
                                    continue
                                widget = adapter._current_step_messages.pop(step_id, None)
                                if widget is not None:
                                    widget.set_complete(
                                        success,
                                        duration_ms,
                                        tool_call_count,
                                        summary,
                                    )
                                else:
                                    ev = dict(data)
                                    ev["namespace"] = list(ns_key)
                                    for line in progress_pipeline.process(ev):
                                        line_text = _format_display_line_for_tui(line)
                                        if line_text:
                                            await adapter._mount_message(AppMessage(line_text))
                                continue

                        if event_type == LOOP_REASON_EVENT_TYPE:
                            ev_plan = dict(data)
                            ev_plan["namespace"] = list(ns_key)
                            plan_lines = progress_pipeline.process(ev_plan)
                            if not plan_lines:
                                continue
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)
                            pa_raw = data.get("plan_action", "new")
                            plan_action = pa_raw if pa_raw in ("keep", "new") else "new"
                            plan_widget = CognitionPlanReasonMessage(
                                next_action=str(data.get("next_action", "")),
                                status=str(data.get("status", "")),
                                iteration=int(data.get("iteration", 0)),
                                plan_action=str(plan_action),
                                assessment_reasoning=str(data.get("assessment_reasoning", "")),
                                plan_reasoning=str(data.get("plan_reasoning", "")),
                                legacy_reasoning=str(data.get("reasoning", "")),
                                id=f"plan-{uuid.uuid4().hex[:8]}",
                            )
                            await adapter._mount_message(plan_widget)
                            continue

                        progress_lines = _format_progress_event_lines_for_tui(
                            data,
                            ns_key,
                            pipeline=progress_pipeline,
                        )
                        if progress_lines:
                            pending_text = pending_text_by_namespace.get(ns_key, "")
                            if pending_text:
                                await _flush_assistant_text_ns(
                                    adapter,
                                    pending_text,
                                    ns_key,
                                    assistant_message_by_namespace,
                                )
                                pending_text_by_namespace[ns_key] = ""
                                assistant_message_by_namespace.pop(ns_key, None)
                            for progress_line in progress_lines:
                                await adapter._mount_message(AppMessage(progress_line))
                            continue

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
                if adapter._set_spinner and not adapter._current_tool_messages:
                    await adapter._set_spinner("Thinking")

            # Flush any remaining text from all namespaces
            for ns_key, pending_text in list(pending_text_by_namespace.items()):
                if pending_text:
                    await _flush_assistant_text_ns(
                        adapter, pending_text, ns_key, assistant_message_by_namespace
                    )
            pending_text_by_namespace.clear()
            assistant_message_by_namespace.clear()

            # Handle HITL after stream completes
            if interrupt_occurred:
                any_rejected = False
                resume_payload: dict[str, Any] = {}

                for interrupt_id, ask_req in list(pending_ask_user.items()):
                    questions = ask_req["questions"]

                    if adapter._request_ask_user:
                        if adapter._set_spinner:
                            await adapter._set_spinner(None)
                        result: dict[str, Any] = {
                            "type": "error",
                            "error": "ask_user callback returned no response",
                        }
                        try:
                            future = await adapter._request_ask_user(questions)
                        except Exception:
                            logger.exception("Failed to mount ask_user widget")
                            result = {
                                "type": "error",
                                "error": "failed to display ask_user prompt",
                            }
                            future = None

                        if future is None:
                            logger.error("ask_user callback returned no Future; reporting as error")
                        else:
                            try:
                                future_result = await future
                                if isinstance(future_result, dict):
                                    result = future_result
                                else:
                                    logger.error(
                                        "ask_user future returned non-dict result: %s",
                                        type(future_result).__name__,
                                    )
                                    result = {
                                        "type": "error",
                                        "error": "invalid ask_user widget result",
                                    }
                            except Exception:
                                logger.exception(
                                    "ask_user future resolution failed; reporting as error"
                                )
                                result = {
                                    "type": "error",
                                    "error": "failed to receive ask_user response",
                                }

                        result_type = result.get("type")
                        if result_type == "answered":
                            answers = result.get("answers", [])
                            if isinstance(answers, list):
                                resume_payload[interrupt_id] = {"answers": answers}
                                tool_id = ask_req["tool_call_id"]
                                tc_sid = str(tool_id) if tool_id is not None else ""
                                if tc_sid and tc_sid in adapter._current_tool_messages:
                                    tool_msg = adapter._current_tool_messages[tc_sid]
                                    tool_msg.set_success("User answered")
                                    adapter._current_tool_messages.pop(tc_sid, None)
                            else:
                                logger.error(
                                    "ask_user answered payload had non-list answers: %s",
                                    type(answers).__name__,
                                )
                                resume_payload[interrupt_id] = {
                                    "status": "error",
                                    "error": "invalid ask_user answers payload",
                                    "answers": ["" for _ in questions],
                                }
                                any_rejected = True
                        elif result_type == "cancelled":
                            resume_payload[interrupt_id] = {
                                "status": "cancelled",
                                "answers": ["" for _ in questions],
                            }
                            any_rejected = True
                        else:
                            error_text = result.get("error")
                            if not isinstance(error_text, str) or not error_text:
                                error_text = "ask_user interaction failed"
                            resume_payload[interrupt_id] = {
                                "status": "error",
                                "error": error_text,
                                "answers": ["" for _ in questions],
                            }
                            any_rejected = True
                    else:
                        logger.warning(
                            "ask_user interrupt received but no UI callback is registered; reporting as error"
                        )
                        resume_payload[interrupt_id] = {
                            "status": "error",
                            "error": "ask_user not supported by this UI",
                            "answers": ["" for _ in questions],
                        }

                for interrupt_id, hitl_request in list(pending_interrupts.items()):
                    action_requests = hitl_request["action_requests"]

                    if session_state.auto_approve:
                        decisions: list[HITLDecision] = [
                            ApproveDecision(type="approve") for _ in action_requests
                        ]
                        resume_payload[interrupt_id] = {"decisions": decisions}
                        for tool_msg in list(adapter._current_tool_messages.values()):
                            tool_msg.set_running()
                    else:
                        # Batch approval - one dialog for all parallel tool calls
                        await dispatch_hook(
                            "permission.request",
                            {"tool_names": [r.get("name", "") for r in action_requests]},
                        )
                        future = await adapter._request_approval(action_requests, assistant_id)
                        decision = await future

                        if isinstance(decision, dict):
                            decision_type = decision.get("type")

                            if decision_type == "auto_approve_all":
                                session_state.auto_approve = True
                                if adapter._on_auto_approve_enabled:
                                    adapter._on_auto_approve_enabled()
                                decisions = [
                                    ApproveDecision(type="approve") for _ in action_requests
                                ]
                                tool_msgs = list(adapter._current_tool_messages.values())
                                for tool_msg in tool_msgs:
                                    tool_msg.set_running()
                                for action_request in action_requests:
                                    tool_name = action_request.get("name")
                                    if tool_name in {
                                        "write_file",
                                        "edit_file",
                                    }:
                                        args = action_request.get("args", {})
                                        if isinstance(args, dict):
                                            file_op_tracker.mark_hitl_approved(tool_name, args)

                            elif decision_type == "approve":
                                decisions = [
                                    ApproveDecision(type="approve") for _ in action_requests
                                ]
                                tool_msgs = list(adapter._current_tool_messages.values())
                                for tool_msg in tool_msgs:
                                    tool_msg.set_running()
                                for action_request in action_requests:
                                    tool_name = action_request.get("name")
                                    if tool_name in {
                                        "write_file",
                                        "edit_file",
                                    }:
                                        args = action_request.get("args", {})
                                        if isinstance(args, dict):
                                            file_op_tracker.mark_hitl_approved(tool_name, args)

                            elif decision_type == "reject":
                                decisions = [RejectDecision(type="reject") for _ in action_requests]
                                tool_msgs = list(adapter._current_tool_messages.values())
                                for tool_msg in tool_msgs:
                                    tool_msg.set_rejected()
                                adapter._current_tool_messages.clear()
                                any_rejected = True
                            else:
                                logger.warning(
                                    "Unexpected HITL decision type: %s",
                                    decision_type,
                                )
                                decisions = [RejectDecision(type="reject") for _ in action_requests]
                                for tool_msg in list(adapter._current_tool_messages.values()):
                                    tool_msg.set_rejected()
                                adapter._current_tool_messages.clear()
                                any_rejected = True
                        else:
                            logger.warning(
                                "HITL decision was not a dict: %s",
                                type(decision).__name__,
                            )
                            decisions = [RejectDecision(type="reject") for _ in action_requests]
                            for tool_msg in list(adapter._current_tool_messages.values()):
                                tool_msg.set_rejected()
                            adapter._current_tool_messages.clear()
                            any_rejected = True

                        resume_payload[interrupt_id] = {"decisions": decisions}

                        if any_rejected:
                            break

                suppress_resumed_output = any_rejected

            if interrupt_occurred and resume_payload:
                if suppress_resumed_output and not pending_ask_user:
                    await adapter._mount_message(
                        AppMessage("Command rejected. Tell the agent what you'd like instead.")
                    )
                    turn_stats.wall_time_seconds = time.monotonic() - start_time
                    return turn_stats

                stream_input = Command(resume=resume_payload)
            else:
                await dispatch_hook("task.complete", {"thread_id": thread_id})
                break

    except (asyncio.CancelledError, KeyboardInterrupt):
        await _handle_interrupt_cleanup(
            adapter=adapter,
            agent=agent,
            config=config,
            pending_text_by_namespace=pending_text_by_namespace,
            captured_input_tokens=captured_input_tokens,
            captured_output_tokens=captured_output_tokens,
            turn_stats=turn_stats,
            start_time=start_time,
        )
        return turn_stats

    # Update token count and return stats
    turn_stats.wall_time_seconds = time.monotonic() - start_time
    await _report_and_persist_tokens(
        adapter,
        agent,
        config,
        captured_input_tokens,
        captured_output_tokens,
    )
    return turn_stats


async def _handle_interrupt_cleanup(
    *,
    adapter: TextualUIAdapter,
    agent: Any,  # noqa: ANN401  # Dynamic agent graph type
    config: RunnableConfig,
    pending_text_by_namespace: dict[tuple, str],
    captured_input_tokens: int,
    captured_output_tokens: int,
    turn_stats: SessionStats,
    start_time: float,
) -> None:
    """Shared cleanup for CancelledError and KeyboardInterrupt.

    Args:
        adapter: UI adapter with display callbacks.
        agent: The LangGraph agent.
        config: Runnable config with `thread_id`.
        pending_text_by_namespace: Accumulated text per namespace.
        captured_input_tokens: Input tokens captured before interrupt.
        captured_output_tokens: Output tokens captured before interrupt.
        turn_stats: Stats for the current turn.
        start_time: Monotonic timestamp when the turn began.
    """
    from langchain_core.messages import HumanMessage

    # Clear active message immediately so it won't block pruning.
    # If we don't do this, the store still thinks it's active and protects
    # from pruning, which breaks get_messages_to_prune(), potentially
    # blocking all future pruning.
    if adapter._set_active_message:
        adapter._set_active_message(None)

    # Hide spinner (may still show a stale status if interrupted)
    if adapter._set_spinner:
        await adapter._set_spinner(None)

    await adapter._mount_message(AppMessage("Interrupted by user"))

    interrupted_msg = _build_interrupted_ai_message(
        pending_text_by_namespace,
        adapter._current_tool_messages,
    )

    # Save accumulated state before marking tools as rejected (best-effort).
    # State update failures shouldn't prevent cleanup.
    # Use shorter timeout (2s) during interrupt cleanup to avoid blocking detachment.
    try:
        if interrupted_msg:
            await agent.aupdate_state(config, {"messages": [interrupted_msg]}, timeout=2.0)

        cancellation_msg = HumanMessage(
            content="[SYSTEM] Task interrupted by user. Previous operation was cancelled."
        )
        await agent.aupdate_state(config, {"messages": [cancellation_msg]}, timeout=2.0)
    except Exception:
        logger.warning("Failed to save interrupted state", exc_info=True)

    # Mark tools as rejected AFTER saving state
    for tool_msg in list(adapter._current_tool_messages.values()):
        tool_msg.set_rejected()
    adapter._current_tool_messages.clear()

    for step_msg in list(adapter._current_step_messages.values()):
        step_msg.set_interrupted("Interrupted by user")
    adapter._current_step_messages.clear()

    for gt in list(adapter._goal_tree_by_namespace.values()):
        gt.set_interrupted("Interrupted by user")
    adapter._goal_tree_by_namespace.clear()

    # Keep the token count marked stale whenever interrupted state was captured,
    # including tool-only turns after assistant text was already flushed.
    approximate = interrupted_msg is not None

    turn_stats.wall_time_seconds = time.monotonic() - start_time
    await _report_and_persist_tokens(
        adapter,
        agent,
        config,
        captured_input_tokens,
        captured_output_tokens,
        shield=True,
        approximate=approximate,
    )


async def _persist_context_tokens(
    agent: Any,  # noqa: ANN401  # Dynamic agent graph type
    config: RunnableConfig,
    tokens: int,
) -> None:
    """Best-effort persist of the context token count into graph state.

    Args:
        agent: The LangGraph agent (must support `aupdate_state`).
        config: Runnable config with `thread_id`.
        tokens: Total context tokens to persist.
    """
    try:
        await agent.aupdate_state(config, {"_context_tokens": tokens})
    except Exception:  # non-critical; stale count on resume is acceptable
        logger.warning(
            "Failed to persist _context_tokens=%d; token count may be stale on resume",
            tokens,
            exc_info=True,
        )


async def _report_and_persist_tokens(
    adapter: TextualUIAdapter,
    agent: Any,  # noqa: ANN401  # Dynamic agent graph type
    config: RunnableConfig,
    captured_input_tokens: int,
    captured_output_tokens: int,
    *,
    shield: bool = False,
    approximate: bool = False,
) -> None:
    """Update the token display and best-effort persist to graph state.

    Args:
        adapter: UI adapter with token callbacks.
        agent: The LangGraph agent.
        config: Runnable config with `thread_id` in its configurable dict.
        captured_input_tokens: Total input tokens captured during the turn.
        captured_output_tokens: Total output tokens captured during the turn.
        shield: When `True`, suppress exceptions and `CancelledError` from the
            persist call so that interrupt handlers can safely await this.
        approximate: When `True`, signal to the UI that the count is stale
            (e.g. after an interrupted generation) by appending "+".
    """
    if captured_input_tokens or captured_output_tokens:
        if adapter._on_tokens_update:
            adapter._on_tokens_update(captured_input_tokens, approximate=approximate)
        if shield:
            try:
                await _persist_context_tokens(agent, config, captured_input_tokens)
            except (Exception, asyncio.CancelledError):
                logger.debug(
                    "Token persist suppressed during interrupt cleanup",
                    exc_info=True,
                )
        else:
            await _persist_context_tokens(agent, config, captured_input_tokens)
    elif adapter._on_tokens_show:
        adapter._on_tokens_show(approximate=approximate)


async def _flush_assistant_text_ns(
    adapter: TextualUIAdapter,
    text: str,
    ns_key: tuple,
    assistant_message_by_namespace: dict[tuple, Any],
) -> None:
    """Flush accumulated assistant text for a specific namespace.

    Finalizes the streaming by stopping the MarkdownStream.
    If no message exists yet, creates one with the full content.
    """
    if not text.strip():
        return

    current_msg = assistant_message_by_namespace.get(ns_key)
    if current_msg is None:
        # No message was created during streaming - create one with full content
        msg_id = f"asst-{uuid.uuid4().hex[:8]}"
        current_msg = AssistantMessage(text, id=msg_id)
        await adapter._mount_message(current_msg)
        await current_msg.write_initial_content()
        assistant_message_by_namespace[ns_key] = current_msg
    else:
        # Stop the stream to finalize the content
        await current_msg.stop_stream()

    # When the AssistantMessage was first mounted and recorded in the
    # MessageStore, it had empty content (streaming hadn't started yet).
    # Now that streaming is done, the widget holds the full text in
    # `_content`, but the store's MessageData still has `content=""`.
    # If the message is later pruned and re-hydrated, `to_widget()` would
    # recreate it from that stale empty string. This call copies the
    # widget's final content back into the store so re-hydration works.
    if adapter._sync_message_content and current_msg.id:
        adapter._sync_message_content(current_msg.id, current_msg._content)

    # Clear active message since streaming is done
    if adapter._set_active_message:
        adapter._set_active_message(None)
