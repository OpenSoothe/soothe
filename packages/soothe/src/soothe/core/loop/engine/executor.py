"""Execute phase logic for AgentLoop (RFC-201).

Act-wave visible answer resolution is integrated here (IG-355, IG-356, IG-357).

After each Execute wave, adaptive goal completion and headless replay use
``LoopState.last_execute_assistant_text``. That string may come from:

- **root_assistant_stream** — aggregated root-graph ``AIMessage`` / chunk text (same path as act
  aggregation for the main graph).
- **task_tool_aggregate** — ordered ``task`` ``ToolMessage`` bodies (delegate finals), including
  parallel waves merged with ``\\n\\n---\\n\\n`` (IG-356).
- **none** — no usable text (empty wave).

``last_wave_answer_from_delegate_final`` on ``LoopState`` remains the boolean hook for runner
replay (IG-355); it is True iff provenance is ``task_tool_aggregate``.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langgraph.types import Command, Interrupt
from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

from soothe.core.context.model_override import (
    attach_stream_model_override,
    reset_stream_model_override,
)
from soothe.core.loop.engine.hitl_scope import (
    _MAX_HITL_ITERATIONS,
    auto_approve_interrupt_resume_payload,
    await_next_graph_stream_chunk,
    get_hitl_interrupt_resolver,
)
from soothe.core.loop.engine.metadata_generator import (
    PLANNER_OUTCOME_PREVIEW_CAP,
)
from soothe.core.loop.engine.predecessor_branch_context import (
    predecessor_execute_messages_for_branch,
    transitive_dependency_step_ids,
)
from soothe.core.loop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepResult,
)
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.middleware.tool_concurrency import init_tool_concurrency_for_thread
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config
from soothe.utils.text_preview import create_output_summary, log_preview, preview, preview_first

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent

    from .goal_context_manager import GoalContextManager

logger = logging.getLogger(__name__)


def _shorten_tool_call_id(raw_tid: str) -> str:
    """Shorten provider tool_call_id for compact display.

    Strips 'functions.' prefix and keeps last numeric index.

    Examples:
        'functions.task:0' → 'task.0'
        'functions.read_file:18' → 'read_file.18'
        'call_abc123' → 'call_abc123' (no pattern match, return as-is)
    """
    tid = str(raw_tid).strip()
    # Strip common prefix
    if tid.startswith("functions."):
        tid = tid[len("functions.") :]
    return tid


def _make_step_tool_call_id(step_id: str, raw_tid: str, call_idx: int) -> str:
    """Generate unified step-level tool call ID.

    Format: {step_id}:s:{tool}.{idx}

    Examples:
        ('GHT-01', 'functions.task:0', 0) → 'GHT-01:s:task.0'
        ('GHT-01', 'functions.read_file:1', 1) → 'GHT-01:s:read_file.1'
    """
    short_tid = _shorten_tool_call_id(raw_tid)
    return f"{step_id}:s:{short_tid}"


def _make_task_inner_tool_call_id(
    step_id: str, task_idx: int, raw_tid: str, inner_call_idx: int
) -> str:
    """Generate unified task-level (subagent inner) tool call ID.

    Format: {step_id}:t{task_idx}:{tool}.{idx}

    Examples:
        ('GHT-01', 0, 'functions.read_file:1', 0) → 'GHT-01:t0:read_file.1'
        ('GHT-01', 0, 'functions.grep:2', 1) → 'GHT-01:t0:grep.2'
    """
    short_tid = _shorten_tool_call_id(raw_tid)
    return f"{step_id}:t{task_idx}:{short_tid}"


def _unified_tool_call_id_for_stream(
    step_id: str,
    raw_tid: str,
    *,
    task_idx: int | None,
) -> str:
    """Build step- or task-level unified tool_call_id for stream rewriting."""
    if task_idx is None:
        return _make_step_tool_call_id(step_id, raw_tid, 0)
    return _make_task_inner_tool_call_id(step_id, task_idx, raw_tid, 0)


def _rewrite_tool_call_ids_to_unified(
    msg: BaseMessage,
    step_id: str,
    *,
    task_idx: int | None = None,
) -> BaseMessage:
    """Rewrite tool_call_ids in AI message/chunk to unified format.

    IG-416: Transforms provider tool_call_ids like ``functions.task:0`` to
    ``{step_id}:s:{tool}`` (root) or ``{step_id}:t{idx}:{tool}`` (subgraph).

    Returns the original message if no modifications needed, or a new
    message object with rewritten IDs.
    """
    from copy import deepcopy

    sid = str(step_id).strip()
    if not sid:
        return msg

    def _needs_unified(raw_id: str) -> bool:
        if not raw_id:
            return False
        parsed_sid, type_code, _, _ = parse_unified_tool_call_id(raw_id)
        if parsed_sid == sid and type_code in ("s", "t"):
            return False
        return ":" not in raw_id or not raw_id.startswith(sid)

    needs_rewrite = False
    seen_ids: set[str] = set()

    if isinstance(msg, AIMessageChunk):
        for tc in getattr(msg, "tool_call_chunks", None) or []:
            if isinstance(tc, dict) and "id" in tc:
                raw_id = str(tc.get("id", ""))
                if raw_id and raw_id not in seen_ids:
                    seen_ids.add(raw_id)
                    if _needs_unified(raw_id):
                        needs_rewrite = True
                        break
        if not needs_rewrite:
            for tc in getattr(msg, "tool_calls", None) or []:
                if isinstance(tc, dict) and "id" in tc:
                    raw_id = str(tc.get("id", ""))
                    if raw_id and raw_id not in seen_ids:
                        seen_ids.add(raw_id)
                        if _needs_unified(raw_id):
                            needs_rewrite = True
                            break
    elif isinstance(msg, AIMessage):
        for tc in getattr(msg, "tool_calls", None) or []:
            if isinstance(tc, dict) and "id" in tc:
                raw_id = str(tc.get("id", ""))
                if raw_id and raw_id not in seen_ids:
                    seen_ids.add(raw_id)
                    if _needs_unified(raw_id):
                        needs_rewrite = True
                        break

    if not needs_rewrite:
        return msg

    modified = deepcopy(msg)

    def _unified(raw_id: str) -> str:
        return _unified_tool_call_id_for_stream(sid, raw_id, task_idx=task_idx)

    if isinstance(modified, AIMessageChunk):
        new_chunks = []
        for tc in getattr(modified, "tool_call_chunks", None) or []:
            if isinstance(tc, dict):
                new_tc = dict(tc)
                raw_id = str(tc.get("id", ""))
                if raw_id:
                    new_tc["id"] = _unified(raw_id)
                new_chunks.append(new_tc)
        if hasattr(modified, "tool_call_chunks") and new_chunks:
            if hasattr(modified, "__dict__"):
                modified.__dict__["tool_call_chunks"] = new_chunks

        new_calls = []
        for tc in getattr(modified, "tool_calls", None) or []:
            if isinstance(tc, dict):
                new_tc = dict(tc)
                raw_id = str(tc.get("id", ""))
                if raw_id:
                    new_tc["id"] = _unified(raw_id)
                new_calls.append(new_tc)
        if hasattr(modified, "tool_calls") and new_calls:
            if hasattr(modified, "__dict__"):
                modified.__dict__["tool_calls"] = new_calls

    elif isinstance(modified, AIMessage):
        new_calls = []
        for tc in getattr(modified, "tool_calls", None) or []:
            if isinstance(tc, dict):
                new_tc = dict(tc)
                raw_id = str(tc.get("id", ""))
                if raw_id:
                    new_tc["id"] = _unified(raw_id)
                new_calls.append(new_tc)
        if hasattr(modified, "__dict__"):
            modified.__dict__["tool_calls"] = new_calls

    return modified


def _rewrite_tool_message_tool_call_id(
    msg: BaseMessage,
    step_id: str,
    *,
    task_idx: int | None = None,
) -> BaseMessage:
    """Align ``ToolMessage.tool_call_id`` with unified AIMessage ids (IG-416).

    Args:
        msg: Stream message (typically ``ToolMessage``).
        step_id: Current execute step id.
        task_idx: When set, use task-level ``{step_id}:t{idx}:…`` ids (subgraph).

    Returns:
        Original message when unchanged, or a shallow-copied ``ToolMessage``.
    """
    if not isinstance(msg, ToolMessage):
        return msg
    sid = str(step_id).strip()
    if not sid:
        return msg
    raw_id = str(getattr(msg, "tool_call_id", "") or "").strip()
    if not raw_id:
        return msg
    parsed_sid, type_code, _, _ = parse_unified_tool_call_id(raw_id)
    if parsed_sid == sid and type_code in ("s", "t"):
        return msg
    unified = _unified_tool_call_id_for_stream(sid, raw_id, task_idx=task_idx)
    return msg.model_copy(update={"tool_call_id": unified})


def _rewrite_root_tool_message_tool_call_id(msg: BaseMessage, step_id: str) -> BaseMessage:
    """Align root-graph ``ToolMessage.tool_call_id`` with unified AIMessage ids."""
    return _rewrite_tool_message_tool_call_id(msg, step_id, task_idx=None)


def _extract_tool_name_from_ai_chunk(msg: BaseMessage, tool_call_id: str) -> str:
    """Extract tool name for a specific tool_call_id from AI message/chunk.

    Args:
        msg: AIMessage or AIMessageChunk containing tool call info.
        tool_call_id: The tool_call_id to extract info for.

    Returns:
        Tool name string, or empty string if not found.
    """
    tool_name: str = ""

    if isinstance(msg, AIMessageChunk):
        # Check tool_call_chunks first (streaming)
        for tc in getattr(msg, "tool_call_chunks", None) or []:
            if not isinstance(tc, dict):
                continue
            tid = tc.get("id")
            if isinstance(tid, str) and tid.strip() == tool_call_id:
                tool_name = str(tc.get("name", "") or "").strip()
                break
        # Fallback to tool_calls if not found in chunks
        if not tool_name:
            for tc in getattr(msg, "tool_calls", None) or []:
                if not isinstance(tc, dict):
                    continue
                tid = tc.get("id")
                if isinstance(tid, str) and tid.strip() == tool_call_id:
                    tool_name = str(tc.get("name", "") or "").strip()
                    break
    elif isinstance(msg, AIMessage):
        for tc in getattr(msg, "tool_calls", None) or []:
            if not isinstance(tc, dict):
                continue
            tid = tc.get("id")
            if isinstance(tid, str) and tid.strip() == tool_call_id:
                tool_name = str(tc.get("name", "") or "").strip()
                break

    return tool_name


# --- Act-wave finalize resolution (merged from execute_wave_finalize.py) ---

ActWaveAnswerProvenance = Literal["root_assistant_stream", "task_tool_aggregate", "none"]

# Cap for joined delegate text and for root assistant text stored on state (memory bound).
DELEGATE_FINAL_WAVE_CAP = 120_000


@dataclass(frozen=True, slots=True)
class ActWaveFinalizeSnapshot:
    """Resolved user-visible text for the last Execute wave and how it was obtained."""

    visible_text: str | None
    provenance: ActWaveAnswerProvenance


def compute_act_wave_finalize(
    *,
    parallel_multi_step: bool,
    root_assistant_text: str,
    delegate_final_text: str | None,
    wave_text_cap: int = DELEGATE_FINAL_WAVE_CAP,
) -> ActWaveFinalizeSnapshot:
    """Compute visible assistant text and provenance for one Execute wave.

    Args:
        parallel_multi_step: Whether this wave ran multiple parallel steps.
        root_assistant_text: Pre-aggregated root-graph assistant text (ignored when
            ``parallel_multi_step`` is True except conceptually empty).
        delegate_final_text: Joined ``task`` tool return bodies for this wave, if any.
        wave_text_cap: Maximum stored length for delegate (and enforced consistently upstream).

    Returns:
        Snapshot with trimmed ``visible_text`` and ``provenance``.
    """
    delegate = (delegate_final_text or "").strip()
    if parallel_multi_step:
        if delegate:
            text = delegate[:wave_text_cap] if len(delegate) > wave_text_cap else delegate
            return ActWaveFinalizeSnapshot(text, "task_tool_aggregate")
        return ActWaveFinalizeSnapshot(None, "none")

    if delegate:
        text = delegate[:wave_text_cap] if len(delegate) > wave_text_cap else delegate
        return ActWaveFinalizeSnapshot(text, "task_tool_aggregate")

    root = root_assistant_text.strip()
    if root:
        return ActWaveFinalizeSnapshot(root, "root_assistant_stream")
    return ActWaveFinalizeSnapshot(None, "none")


def provenance_is_task_delegate(snapshot: ActWaveFinalizeSnapshot) -> bool:
    """True when visible text came from ``task`` tool returns (delegate finals)."""
    return snapshot.provenance == "task_tool_aggregate"


# --- Helper functions ---


def _collect_related_exceptions(exc: BaseException) -> list[BaseException]:
    """Collect this exception plus chained ``__cause__`` / ``__context__`` (deduplicated)."""
    out: list[BaseException] = []
    seen: set[int] = set()

    def visit(e: BaseException | None) -> None:
        if e is None or id(e) in seen:
            return
        seen.add(id(e))
        out.append(e)
        visit(e.__cause__)
        ctx = getattr(e, "__context__", None)
        if ctx is not None and ctx is not e.__cause__:
            visit(ctx)

    visit(exc)
    return out


def _is_expected_connection_refusal(exc: BaseException) -> bool:
    """True when failure is connection refused (local service down / wrong port)."""
    for e in _collect_related_exceptions(exc):
        if isinstance(e, ConnectionRefusedError):
            return True
        if isinstance(e, OSError) and getattr(e, "errno", None) == errno.ECONNREFUSED:
            return True
    return False


def _format_connection_refusal_message(exc: BaseException) -> str:
    """Short, actionable message for connection-refused chains (e.g. aiohttp → OSError)."""
    combined = " ".join(str(e) for e in _collect_related_exceptions(exc))
    m = re.search(r"Connect call failed\s*\(\s*'([^']+)'\s*,\s*(\d+)", combined)
    if m:
        host, port = m.group(1), m.group(2)
        return (
            f"Connection refused to {host}:{port} — nothing is listening there. "
            "Start the service or correct the host/port."
        )
    return (
        "Connection refused — the target service is not accepting connections. "
        "Verify it is running and that the host and port are correct."
    )


def _log_dependency_execution_residual(
    decision: AgentDecision,
    *,
    local_done: set[str],
    failed_sticky: set[str],
) -> None:
    """Emit a warning when dependency execution stopped with steps never started (IG-379).

    Typical causes: unsatisfied or mistyped dependency ids, cycles, or steps blocked behind
    failures (failed step ids are not in ``local_done`` but are excluded from ``never_started``).
    """
    never_started = [
        s for s in decision.steps if s.id not in local_done and s.id not in failed_sticky
    ]
    if not never_started:
        return
    details: list[str] = []
    for s in never_started:
        deps = s.dependencies or []
        unresolved = [x for x in deps if x not in local_done]
        details.append(f"id={s.id!r} unresolved_dependencies={unresolved!r}")
    logger.warning(
        "[Execute] dependency mode finished with %d/%d step(s) never started: %s",
        len(never_started),
        len(decision.steps),
        "; ".join(details),
    )


@dataclass
class _ActStreamBudget:
    """Mutable counters for a single CoreAgent stream (IG-130)."""

    max_subagent_tasks_per_wave: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False


@dataclass(slots=True)
class _ParallelStepDone:
    """Sentinel placed on the parallel live-event queue when one step finishes."""

    step_id: str
    payload: tuple[list[StreamEvent], StepResult, list[BaseMessage], str] | BaseException


_TUPLE_LEN = 3
# ``task`` tool return text cap per invocation before joining (delegate finals).
_DELEGATE_FINAL_PER_TASK_CAP = 80_000

# Type for stream events yielded during execution
StreamEvent = tuple[tuple[str, ...], str, Any]  # (namespace, mode, data)

_ParallelLiveQueueItem = StreamEvent | _ParallelStepDone


def _append_parallel_stream_event(
    events: list[StreamEvent],
    event: StreamEvent,
    live_event_queue: asyncio.Queue[_ParallelLiveQueueItem] | None,
) -> None:
    """Record a stream chunk for the step result and optionally fan out to the TUI queue."""
    events.append(event)
    if live_event_queue is not None:
        live_event_queue.put_nowait(event)


class Executor:
    """Execute phase: Execute steps via Layer 1 CoreAgent.

    This component handles step execution with three modes:
    - parallel: Execute ready steps concurrently with isolated threads (chunked)
    - sequential: Execute ready steps in combined LLM turns (chunked)
    - dependency: Execute steps respecting dependency DAG (chunked parallel waves)

    Events from CoreAgent are propagated through for upstream consumption.
    """

    def __init__(
        self,
        core_agent: CoreAgent,
        *,
        max_parallel_steps: int = 16,
        config: SootheConfig | None = None,
        goal_context_manager: GoalContextManager | None = None,
        loop_id: str | None = None,
    ) -> None:
        """Initialize Execute phase.

        Args:
            core_agent: Layer 1 CoreAgent for step execution
            max_parallel_steps: Max steps to run **concurrently** in one batch. ``execute`` repeats
                batches until all ready steps finish (e.g. 4 ready steps and ``2`` → two batches of 2).
                ``0`` means unlimited (RFC-201 / concurrency).
            config: Optional Soothe config for Act wave caps (IG-130).
            goal_context_manager: Optional GoalContextManager for goal briefing injection (RFC-217).
            loop_id: Optional loop identifier for Langfuse trace correlation.
        """
        self.core_agent = core_agent
        self._max_parallel_steps = max_parallel_steps
        self._config = config
        self._goal_context_manager = goal_context_manager
        self._loop_id = loop_id

    def _executor_langfuse_merge_for_stream(
        self, base: dict[str, Any], *, thread_id: str | None
    ) -> dict[str, Any]:
        """Merge Langfuse callback into RunnableConfig with execute-phase run name (IG-377)."""
        if self._config is None:
            return base
        tn = (self._config.observability.langfuse.trace_name or "").strip()
        run_name = f"{tn}:execute-step" if tn else "execute-step"
        return merge_langfuse_runnable_config(
            base,
            self._config,
            session_id=thread_id,
            run_name=run_name,
            loop_id=self._loop_id,
        )

    async def _claude_runner_config_extras(self, thread_id: str) -> dict[str, Any]:
        """Load Claude session ids + durability handle for subagent resume (IG-202)."""
        if not thread_id or self._config is None:
            return {}
        try:
            from soothe.core.resolver import resolve_durability

            d = resolve_durability(self._config)
            info = await d.get_thread(thread_id)
            extras: dict[str, Any] = {"soothe_durability": d}
            if info:
                extras["claude_sessions"] = dict(info.metadata.claude_sessions)
            return extras
        except Exception:
            logger.debug("Claude runner config extras failed", exc_info=True)
            return {}

    def _max_subagent_tasks_per_wave(self) -> int:
        """Configured cap on root-level ``task`` tool completions (0 = unlimited)."""
        if self._config is None:
            return 0
        return max(0, int(self._config.agent_loop.max_subagent_tasks_per_wave))

    def _branch_predecessor_message_cap(self) -> int:
        """Max ledger messages to deep-copy into a parallel branch CoreAgent input (RFC-214).

        When ``plan_prompt_ledger.plan_ledger_max_messages`` is positive, reuse it as an
        upper bound (capped at 256). Otherwise use ``DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES``.
        """
        from soothe.core.loop.engine.predecessor_branch_context import (
            DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES,
        )

        if self._config is None:
            return DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES
        cap = int(self._config.agent_loop.plan_prompt_ledger.plan_ledger_max_messages)
        if cap > 0:
            return min(cap, 256)
        return DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES

    async def _core_agent_astream_with_hitl(
        self,
        stream_input: dict[str, Any] | Command,
        graph_config: dict[str, Any],
    ) -> AsyncGenerator[Any, None]:
        """Run ``CoreAgent.astream`` with LangGraph HITL interrupt / resume loop.

        When a daemon client registers an interrupt resolver (interactive TUI),
        pauses until ``resume_interrupts`` delivers the payload; otherwise uses
        ``auto_approve_interrupt_resume_payload`` from ``hitl_scope``.
        """
        hitl_iterations = 0
        current_input: dict[str, Any] | Command = stream_input
        while True:
            interrupt_occurred = False
            pending_interrupts: dict[str, Any] = {}
            chunk_iter = self.core_agent.astream(
                current_input,
                config=graph_config,
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
            )
            try:
                while True:
                    try:
                        chunk = await await_next_graph_stream_chunk(chunk_iter)
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        raise

                    if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                        _namespace, mode, data = chunk
                        if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                            interrupts: list[Interrupt] = data["__interrupt__"]
                            for interrupt_obj in interrupts:
                                pending_interrupts[interrupt_obj.id] = interrupt_obj.value
                                interrupt_occurred = True
                    yield chunk
            except asyncio.CancelledError:
                raise

            if not interrupt_occurred:
                return

            hitl_iterations += 1
            if hitl_iterations > _MAX_HITL_ITERATIONS:
                logger.warning(
                    "CoreAgent HITL: exceeded iteration limit (%d); stopping stream",
                    _MAX_HITL_ITERATIONS,
                )
                return

            resolver = get_hitl_interrupt_resolver()
            if resolver is not None:
                resume_payload = await resolver(pending_interrupts)
            else:
                resume_payload = auto_approve_interrupt_resume_payload(pending_interrupts)
            current_input = Command(resume=resume_payload)

    @staticmethod
    def _intent_type_for_prompt(state: LoopState) -> str | None:
        """Intent primary label for CoreAgent prompt scenario blocks (IG-384)."""
        intent = getattr(state, "intent", None)
        if intent is not None and hasattr(intent, "intent_type"):
            raw = getattr(intent, "intent_type", None)
            if raw:
                return str(raw)
        return None

    @staticmethod
    def _execute_graph_input(
        messages: list[Any],
        *,
        routing_classification: Any | None = None,
        workspace: str | None = None,
        git_status: dict[str, Any] | None = None,
        intent_type: str | None = None,
        synthesis_scenario: str | None = None,
    ) -> dict[str, Any]:
        """Build LangGraph input for execute waves (IG-349, IG-383)."""
        out: dict[str, Any] = {"messages": messages}
        if routing_classification is not None:
            out["routing_classification"] = routing_classification
        if workspace:
            out["workspace"] = workspace
        if git_status is not None:
            out["git_status"] = git_status
        if intent_type:
            out["intent_type"] = intent_type
        if synthesis_scenario:
            out["synthesis_scenario"] = synthesis_scenario
        return out

    def _extract_token_usage(self, messages: list[BaseMessage]) -> dict[str, int]:
        """Extract token usage from last AIMessage response metadata.

        Args:
            messages: List of messages from CoreAgent execution

        Returns:
            Dict with prompt_tokens, completion_tokens, total_tokens (or empty dict if unavailable)
        """
        # Find last AIMessage with usage_metadata
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "response_metadata"):
                metadata = msg.response_metadata
                token_usage = metadata.get("token_usage", {})
                if token_usage:
                    return {
                        "prompt": token_usage.get("prompt_tokens", 0),
                        "completion": token_usage.get("completion_tokens", 0),
                        "total": token_usage.get("total_tokens", 0),
                    }
        return {}

    def _record_execute_wave_for_finalize(
        self,
        state: LoopState,
        messages: list[BaseMessage],
        *,
        parallel_multi_step: bool,
        delegate_final_text: str | None = None,
    ) -> None:
        """Apply resolved Act-wave visible text to state (IG-199, IG-355, IG-357).

        Resolution is centralized in :func:`~soothe.core.loop.engine.executor.compute_act_wave_finalize`.
        """
        root_text = (
            ""
            if parallel_multi_step
            else self._assemble_assistant_text_from_stream_messages(messages).strip()
        )
        snap = compute_act_wave_finalize(
            parallel_multi_step=parallel_multi_step,
            root_assistant_text=root_text,
            delegate_final_text=delegate_final_text,
        )
        state.last_execute_wave_parallel_multi_step = parallel_multi_step
        state.last_wave_answer_from_delegate_final = provenance_is_task_delegate(snap)
        state.last_execute_assistant_text = snap.visible_text

    def _assemble_assistant_text_from_stream_messages(self, messages: list[BaseMessage]) -> str:
        """Extract assistant-visible text from CoreAgent stream message list.

        Matches the selection rules used for AgentLoop final-report streaming: prefer
        concatenated ``AIMessageChunk`` text over a trailing non-chunk ``AIMessage``.

        Args:
            messages: Messages collected from ``_stream_and_collect`` (AI entries only).

        Returns:
            Stripped assistant text, or empty string if none.
        """
        accumulated_chunks = ""
        final_ai_message_text = ""
        for msg in messages:
            if not isinstance(msg, (AIMessage, AIMessageChunk)):
                continue
            content = msg.content
            extracted_text = ""
            if isinstance(content, str):
                extracted_text = content
            elif isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        parts.append(block["text"])
                    elif isinstance(block, str):
                        parts.append(block)
                extracted_text = "".join(parts)

            if isinstance(msg, AIMessageChunk) and extracted_text:
                accumulated_chunks += extracted_text
            elif isinstance(msg, AIMessage) and extracted_text:
                final_ai_message_text = extracted_text

        last_ai_text = (
            accumulated_chunks
            if len(accumulated_chunks) >= len(final_ai_message_text)
            else final_ai_message_text
        )
        return last_ai_text.strip()

    def _aggregate_wave_metrics(
        self,
        step_results: list[StepResult],
        output: str,
        messages: list[BaseMessage],
        state: LoopState,
    ) -> None:
        """Aggregate metrics from wave execution into LoopState.

        Called after sequential or parallel wave completes.

        Args:
            step_results: List of step results from the wave
            output: Combined output text from the wave
            messages: Messages from CoreAgent execution (for token extraction)
            state: LoopState to update with aggregated metrics
        """
        # Sum tool calls and subagent tasks
        total_tool_calls = sum(r.tool_call_count for r in step_results)
        total_subagent_tasks = sum(r.subagent_task_completions for r in step_results)

        # OR cap hit (any step hit cap)
        hit_cap = any(r.hit_subagent_cap for r in step_results)

        # Count errors
        error_count = sum(1 for r in step_results if not r.success)

        # Measure output length
        output_length = len(output) if output else 0

        # Update state
        state.last_wave_tool_call_count = total_tool_calls
        state.last_wave_subagent_task_count = total_subagent_tasks
        state.last_wave_hit_subagent_cap = hit_cap
        state.last_wave_output_length = output_length
        state.last_wave_error_count = error_count

        # Context window metrics with actual token usage (IG-151)
        token_usage = self._extract_token_usage(messages)

        if token_usage and "total" in token_usage:
            # Use actual token count from LLM response
            actual_tokens = token_usage["total"]
            state.total_tokens_used += actual_tokens
            logger.debug(
                "tokens: actual=%d prompt=%d completion=%d",
                actual_tokens,
                token_usage.get("prompt", 0),
                token_usage.get("completion", 0),
            )
        elif output:
            # Fallback: use tiktoken for accurate estimation
            from soothe.utils.token_counting import count_tokens

            estimated_tokens = count_tokens(output)
            state.total_tokens_used += estimated_tokens

        # Use configurable context limit (IG-151)
        if self._config is not None:
            context_limit = self._config.agent_loop.context_window_limit
            state.context_percentage_consumed = min(1.0, state.total_tokens_used / context_limit)

    async def execute(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute steps based on execution mode, yielding events and results.

        This method yields stream events (custom events from tool execution)
        during execution, then yields final StepResult objects.

        IG-XXX: Uses fast model for tool-heavy execution phase to reduce latency.
        IG-XXX: Bounds concurrent tool calls per thread via semaphore.

        Args:
            decision: AgentDecision with steps to execute
            state: Current loop state

        Yields:
            StreamEvent during execution, then StepResult for each step.
        """
        ready_steps = decision.get_ready_steps(state.dependency_completion_ids())

        if not ready_steps:
            logger.warning("No ready steps to execute (all completed or blocked)")
            return

        # Initialize tool concurrency semaphore for this thread
        max_parallel_tools = 5  # Default
        if self._config is not None:
            max_parallel_tools = self._config.agent_loop.limits.max_parallel_tools
        init_tool_concurrency_for_thread(max_parallel_tools)

        # IG-XXX: Use fast model for execute phase (tool-heavy operations)
        # The execute phase runs tools which benefit from a faster/cheaper model
        # rather than the default heavy model used for planning/reasoning
        model_override_token = None
        if self._config is not None:
            fast_model_spec = self._config.router.fast
            if fast_model_spec:
                model_override_token = attach_stream_model_override(fast_model_spec, {})
                logger.info("[Execute] Using fast model override: %s", fast_model_spec)

        has_dependency_edges = any(step.dependencies for step in decision.steps)
        effective_execution_mode = "dependency" if has_dependency_edges else decision.execution_mode
        if effective_execution_mode != decision.execution_mode:
            logger.info(
                "[Execute] dependency edges present; draining plan as dependency DAG "
                "(planner mode=%s)",
                decision.execution_mode,
            )

        logger.info(
            "[Execute] steps=%d mode=%s max_parallel=%d tool_limit=%d",
            len(ready_steps),
            effective_execution_mode,
            self._max_parallel_steps,
            max_parallel_tools,
        )

        try:
            if effective_execution_mode == "parallel":
                async for item in self._execute_parallel_waves(ready_steps, state):
                    yield item
            elif effective_execution_mode == "sequential":
                async for item in self._execute_sequential_waves(ready_steps, state):
                    yield item
            elif effective_execution_mode == "dependency":
                async for item in self._execute_dependency(decision, state):
                    yield item
            else:
                msg = f"Unknown execution mode: {decision.execution_mode}"
                raise ValueError(msg)
        finally:
            # Reset model override after execute phase completes
            if model_override_token is not None:
                reset_stream_model_override(model_override_token)
                logger.debug("[Execute] Fast model override reset")

    def _wave_size(self, remaining: int) -> int:
        """Concurrent step count for the next execute batch (``0`` = unlimited).

        One batch does not exhaust ``execute``; callers loop until all ready steps are scheduled.
        """
        if remaining <= 0:
            return 0
        if self._max_parallel_steps <= 0:
            return remaining
        return min(self._max_parallel_steps, remaining)

    async def _execute_parallel_waves(
        self,
        ready_steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Run parallel mode in waves bounded by ``max_parallel_steps``."""
        idx = 0
        n = len(ready_steps)
        while idx < n:
            w = self._wave_size(n - idx)
            chunk = ready_steps[idx : idx + w]
            idx += w
            async for item in self._execute_parallel(chunk, state):
                yield item

    def _step_results_for_chunk(
        self,
        steps: list[StepAction],
        combined_description: str | None = None,
        *,
        success: bool,
        output: str | None,
        error: str | None,
        error_type: str | None,
        duration_ms: int,
        tool_call_count: int,
        thread_id: str,
        subagent_task_completions: int = 0,
        hit_subagent_cap: bool = False,
    ) -> list[StepResult]:
        """One ``StepResult`` per step in a combined sequential turn (scheme B)."""
        n = len(steps)
        if n == 0:
            return []
        base, rem = divmod(max(duration_ms, 0), n)
        durations = [base + (1 if i < rem else 0) for i in range(n)]
        tool_counts = [0] * n
        if n > 0:
            tool_counts[0] = tool_call_count
        results: list[StepResult] = []
        for i, step in enumerate(steps):
            if success:
                # IG-148: Add CoreAgent input/output evidence for sequential execution
                outcome_data = {
                    "type": "subagent" if subagent_task_completions > 0 else "generic",
                    "size_bytes": len(output.encode("utf-8")) if output else 0,
                }
                if subagent_task_completions > 0:
                    outcome_data["tool_name"] = "task"
                # Add step input (combined_description for sequential waves)
                if combined_description:
                    outcome_data["step_input"] = combined_description
                # Add output summary (truncated)
                if output:
                    outcome_data["output_summary"] = create_output_summary(output)
                    stripped = output.strip()
                    if stripped:
                        cap = PLANNER_OUTCOME_PREVIEW_CAP
                        outcome_data["wave_join_preview"] = stripped[:cap] + (
                            "…" if len(stripped) > cap else ""
                        )

                results.append(
                    StepResult(
                        step_id=step.id,
                        success=True,
                        outcome=outcome_data,  # RFC-211 + IG-148
                        duration_ms=durations[i],
                        thread_id=thread_id,
                        tool_call_count=tool_counts[i],
                        subagent_task_completions=subagent_task_completions if i == 0 else 0,
                        hit_subagent_cap=hit_subagent_cap if i == 0 else False,
                    )
                )
            else:
                results.append(
                    StepResult(
                        step_id=step.id,
                        success=False,
                        outcome={"type": "error", "error": error or ""},  # RFC-211
                        error=error or "",
                        error_type=error_type,
                        duration_ms=durations[i],
                        thread_id=thread_id,
                        tool_call_count=0,
                        subagent_task_completions=0,
                        hit_subagent_cap=False,
                    )
                )
        return results

    def _append_parallel_wave_ledger(
        self,
        state: LoopState,
        steps: list[StepAction],
        gather_results: list[Any],
    ) -> None:
        """Append RFC-214 Human/AI ledger pairs for each parallel step (IG-374).

        Sequential execution records the ledger inside ``_execute_sequential_chunk``. Parallel
        waves historically skipped ``state.loop_messages``, which hid execute evidence from
        subsequent ``plan-assess`` / ``plan-generate`` prompts built in ``PromptBuilder``.

        Args:
            state: Loop state whose ``loop_messages`` list is extended in wave order.
            steps: Ready steps for this wave (same order as ``gather_results``).
            gather_results: Results from ``asyncio.gather`` over per-step tasks — each entry is
                either an exception or the tuple returned by ``_execute_step_collecting_events``.
        """
        from langchain_core.messages import AIMessage

        from soothe.core.loop.utils.stream_normalize import extract_text_from_message_content

        for i, step in enumerate(steps):
            raw = gather_results[i]
            human_msg = LoopHumanMessage(
                content=f"Execute: {step.description}",
                thread_id=state.thread_id,
                iteration=state.iteration,
                goal_summary=(state.goal[:200] if state.goal else None),
                workspace=state.workspace,
                phase="execute_step",
                step_id=step.id,
            )
            if isinstance(raw, Exception):
                err_text = str(raw).strip() or repr(raw)
                state.loop_messages.append(human_msg)
                state.loop_messages.append(
                    LoopAIMessage(
                        content=f"Step failed: {err_text}",
                        thread_id=state.thread_id,
                        iteration=state.iteration,
                        phase="execute_step",
                        step_id=step.id,
                    )
                )
                continue

            _events, step_result, step_messages, delegate_final = raw
            ai_messages = [m for m in step_messages if isinstance(m, AIMessage)]
            final_ai = ai_messages[-1] if ai_messages else None

            if step_result.success:
                content = ""
                if final_ai is not None:
                    ledger_body = self._ledger_execute_ai_content(
                        messages=step_messages,
                        final_ai_msg=final_ai,
                        total_steps=1,
                    )
                    content = (ledger_body or "").strip()
                    if not content:
                        content = extract_text_from_message_content(
                            getattr(final_ai, "content", None)
                        ).strip()
                df = (delegate_final or "").strip()
                if not content and df:
                    content = (
                        df if len(df) <= DELEGATE_FINAL_WAVE_CAP else df[:DELEGATE_FINAL_WAVE_CAP]
                    )
                if not content:
                    content = "Step completed with no AI text captured"
            else:
                content = (step_result.error or "").strip() or "Step failed"
                if final_ai is not None:
                    ledger_body = self._ledger_execute_ai_content(
                        messages=step_messages,
                        final_ai_msg=final_ai,
                        total_steps=1,
                    )
                    lb = (ledger_body or "").strip()
                    if lb:
                        content = lb

            meta = getattr(final_ai, "response_metadata", {}) if final_ai is not None else {}
            state.loop_messages.append(human_msg)
            state.loop_messages.append(
                LoopAIMessage(
                    content=content,
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    phase="execute_step",
                    step_id=step.id,
                    response_metadata=meta,
                )
            )

    async def _execute_parallel(
        self,
        steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute steps in parallel with isolated threads.

        Stream events are merged onto a shared queue and yielded as they arrive so
        daemon/TUI clients see tool and subagent activity during the wave, not only
        after ``asyncio.gather`` completes.

        Args:
            steps: Steps to execute
            state: Loop state

        Yields:
            StreamEvent chunks in arrival order, then each ``StepResult`` when its step
            finishes (completion order, not necessarily step list order).
        """
        # Branched LangGraph thread_id for parallel checkpoint isolation; StepResult keeps logical thread_id.
        logical_tid = state.thread_id
        itype = self._intent_type_for_prompt(state)
        n_steps = len(steps)
        live_queue: asyncio.Queue[_ParallelLiveQueueItem] = asyncio.Queue()
        gather_results: list[Any] = [None] * n_steps
        step_wave_index: dict[str, int] = {step.id: i for i, step in enumerate(steps)}

        async def _run_parallel_step(step: StepAction) -> None:
            sid = step.id
            try:
                payload = await self._execute_step_collecting_events(
                    step,
                    logical_tid,
                    state.workspace,
                    stream_thread_id=(f"{logical_tid}__p{sid}" if n_steps > 1 else logical_tid),
                    routing_classification=getattr(state, "routing_classification", None),
                    git_status=state.git_status,
                    intent_type=itype,
                    loop_state=state,
                    live_event_queue=live_queue,
                )
                live_queue.put_nowait(_ParallelStepDone(sid, payload))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                live_queue.put_nowait(_ParallelStepDone(sid, exc))

        tasks = [asyncio.create_task(_run_parallel_step(step)) for step in steps]

        all_step_results: list[StepResult] = []
        single_wave_messages: list[BaseMessage] = []
        wave_delegate_final = ""
        wave_delegate_parts: list[str] = []
        completed = 0

        try:
            while completed < n_steps:
                item = await live_queue.get()
                if isinstance(item, _ParallelStepDone):
                    completed += 1
                    sid = item.step_id
                    wave_i = step_wave_index.get(sid)
                    if wave_i is None:
                        logger.warning(
                            "Parallel step completion for unknown step_id=%r; skipping",
                            sid,
                        )
                        continue
                    result = item.payload
                    gather_results[wave_i] = result
                    if isinstance(result, Exception):
                        logger.error(
                            "Parallel step %s failed with exception: %s",
                            sid,
                            result,
                            exc_info=result,
                        )
                        step_result = StepResult(
                            step_id=sid,
                            success=False,
                            outcome={"type": "error", "error": str(result)},  # RFC-211
                            error=str(result),
                            error_type=self._classify_error_severity(result),
                            duration_ms=0,
                            thread_id=state.thread_id,
                            subagent_task_completions=0,
                            hit_subagent_cap=False,
                        )
                        all_step_results.append(step_result)
                        yield step_result
                    else:
                        _events, step_result, step_messages, delegate_final = result
                        if n_steps == 1:
                            single_wave_messages = step_messages
                            wave_delegate_final = delegate_final
                        df = (delegate_final or "").strip()
                        if df:
                            wave_delegate_parts.append(df)
                        all_step_results.append(step_result)
                        yield step_result
                else:
                    yield item
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            await asyncio.gather(*tasks, return_exceptions=True)

        results = gather_results

        # RFC-214: parallel waves must update the ledger like sequential chunks so Plan-assess
        # receives prior execute evidence via ``state.loop_messages`` (IG-374).
        self._append_parallel_wave_ledger(state, steps, results)

        parallel_multi = len(steps) > 1
        merged_parallel_delegate = "\n\n---\n\n".join(wave_delegate_parts)
        if parallel_multi:
            self._record_execute_wave_for_finalize(
                state,
                [],
                parallel_multi_step=True,
                delegate_final_text=merged_parallel_delegate or None,
            )
        else:
            self._record_execute_wave_for_finalize(
                state,
                single_wave_messages,
                parallel_multi_step=False,
                delegate_final_text=wave_delegate_final or None,
            )

        # Aggregate metrics from parallel execution
        if all_step_results:
            # For parallel, use max output length across steps
            # RFC-211: Use outcome metadata to get size
            output_lengths = [
                r.outcome.get("size_bytes", 0) for r in all_step_results if r.success and r.outcome
            ]
            max_output_len = max(output_lengths) if output_lengths else 0
            # Token totals: parallel steps stream independently; per-step messages are not merged here.
            self._aggregate_wave_metrics(all_step_results, "", [], state)
            state.last_wave_output_length = max_output_len

    async def _execute_sequential_waves(
        self,
        ready_steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Run sequential mode in waves; each wave yields one result per step (scheme B)."""
        idx = 0
        n = len(ready_steps)
        while idx < n:
            w = self._wave_size(n - idx)
            chunk = ready_steps[idx : idx + w]
            idx += w
            async for item in self._execute_sequential_chunk(chunk, state):
                yield item

    async def _execute_sequential_chunk(
        self,
        steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute a wave of steps with ledger recording (RFC-214).

        Args:
            steps: Non-empty slice of ready steps
            state: Loop state

        Yields:
            StreamEvent during execution, then one StepResult per step in ``steps``.
        """
        # RFC-214: Build N Human messages (one per step) instead of combined description
        step_messages = self._build_batch_human_messages(steps, state)

        # Compact input summary log
        logger.debug(
            "[Execute-Seq] steps=%d thread=%s workspace=%s",
            len(steps),
            state.thread_id[:12] if state.thread_id else "none",
            state.workspace if state.workspace else "none",
        )

        start = time.perf_counter()
        event_count = 0
        budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())

        try:
            configurable: dict[str, Any] = {"thread_id": state.thread_id}
            if state.workspace:
                configurable["workspace"] = state.workspace
            # Pass current_decision for middleware to inject agent loop output contract
            if state.current_decision:
                configurable["current_decision"] = state.current_decision
            # RFC-217: Inject goal briefing on thread switch
            if self._goal_context_manager:
                goal_briefing = await self._goal_context_manager.get_execute_briefing()
                if goal_briefing:
                    configurable["soothe_goal_briefing"] = goal_briefing
                    logger.info("Execute briefing injected (%d chars)", len(goal_briefing))
            configurable.update(await self._claude_runner_config_extras(state.thread_id))

            # RFC-214: Execute batch with N Human messages
            graph_config: dict[str, Any] = {"configurable": configurable}
            if self._config is not None:
                graph_config = self._executor_langfuse_merge_for_stream(
                    graph_config, thread_id=state.thread_id
                )
            stream = self._core_agent_astream_with_hitl(
                self._execute_graph_input(
                    step_messages,  # N messages instead of combined description
                    routing_classification=getattr(state, "routing_classification", None),
                    workspace=state.workspace,
                    git_status=state.git_status,
                    intent_type=self._intent_type_for_prompt(state),
                ),
                graph_config,
            )

            tool_call_count = 0
            messages: list[BaseMessage] = []
            output = ""
            async for (
                final_output,
                event,
                tc_count,
                msg_list,
                _,
            ) in self._stream_and_collect(stream, budget=budget):
                if event is not None:
                    event_count += 1
                    yield event
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count
                    messages = msg_list

            duration_ms = int((time.perf_counter() - start) * 1000)

            logger.info(
                "[Wave-Seq] steps=%d dur=%dms evts=%d tools=%d subagents=%d cap=%s (RFC-214)",
                len(steps),
                duration_ms,
                event_count,
                tool_call_count,
                budget.subagent_task_completions,
                budget.hit_subagent_cap,
            )

            # RFC-214: Extract N outcomes and record N adjacent pairs in ledger
            step_outcomes = self._extract_sequential_outcomes(messages, steps, state)
            step_results = self._record_batch_ledger_pairs(
                state,
                step_messages,
                step_outcomes,
                steps,
                duration_ms=duration_ms,
                subagent_task_completions=budget.subagent_task_completions,
                hit_subagent_cap=budget.hit_subagent_cap,
                tool_call_count=tool_call_count,
            )

            # Aggregate metrics into LoopState
            self._aggregate_wave_metrics(step_results, output, messages, state)
            self._record_execute_wave_for_finalize(
                state,
                messages,
                parallel_multi_step=False,
            )

            # Yield step results
            for sr in step_results:
                yield sr

        except asyncio.CancelledError:
            logger.info("Sequential execution cancelled")
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if _is_expected_connection_refusal(e):
                logger.warning(
                    "Sequential execution failed: %s",
                    _format_connection_refusal_message(e),
                )
            else:
                logger.exception("Sequential execution failed")

            error_msg = self._extract_error_message(e, "Sequential execution failed")
            self._classify_error_severity(e)

            # RFC-214: Record error outcomes in ledger
            step_outcomes = {}
            for step in steps:
                step_outcomes[step.id] = LoopAIMessage(
                    content=f"Step failed: {error_msg}",
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    phase="execute_step",
                    step_id=step.id,
                )

            # Record error pairs in ledger
            step_messages_err = self._build_batch_human_messages(steps, state)
            from soothe.core.loop.state.schemas import StepResult

            n_err = len(steps)
            eb, er = divmod(max(duration_ms, 0), n_err) if n_err else (0, 0)
            err_durations = [eb + (1 if j < er else 0) for j in range(n_err)]

            step_results = []
            for i, step in enumerate(steps):
                # Append Human-AI error pair
                state.loop_messages.append(step_messages_err[i])
                state.loop_messages.append(step_outcomes[step.id])

                # Build error StepResult
                result = StepResult(
                    step_id=step.id,
                    success=False,
                    outcome={"type": "error", "error": error_msg},
                    duration_ms=err_durations[i],
                    thread_id=state.thread_id,
                    error=error_msg,
                )
                step_results.append(result)

            # Aggregate metrics (includes error count)
            self._aggregate_wave_metrics(step_results, "", [], state)
            self._record_execute_wave_for_finalize(state, [], parallel_multi_step=False)

            # Yield step results
            for sr in step_results:
                yield sr

    async def _execute_dependency(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute steps respecting dependency DAG.

        Args:
            decision: AgentDecision with dependency information
            state: Loop state

        Yields:
            StreamEvent during execution, then StepResult.
        """
        local_done = set(state.dependency_completion_ids())
        failed_sticky: set[str] = set()

        while True:
            ready_all = decision.get_ready_steps(local_done)
            ready = [s for s in ready_all if s.id not in failed_sticky]
            if not ready:
                break
            w = self._wave_size(len(ready))
            chunk = ready[:w]
            async for item in self._execute_parallel(chunk, state):
                yield item
                if isinstance(item, StepResult):
                    if item.success:
                        local_done.add(item.step_id)
                    else:
                        failed_sticky.add(item.step_id)

        _log_dependency_execution_residual(
            decision, local_done=local_done, failed_sticky=failed_sticky
        )

    async def _execute_step_collecting_events(
        self,
        step: StepAction,
        thread_id: str,
        workspace: str | None = None,
        *,
        stream_thread_id: str | None = None,
        routing_classification: Any | None = None,
        git_status: dict[str, Any] | None = None,
        intent_type: str | None = None,
        loop_state: LoopState | None = None,
        live_event_queue: asyncio.Queue[_ParallelLiveQueueItem] | None = None,
    ) -> tuple[list[StreamEvent], StepResult, list[BaseMessage], str]:
        """Execute single step, collecting events for the parallel merge queue.

        When ``live_event_queue`` is set (parallel execute), each stream chunk is pushed
        immediately for upstream TUI/WebSocket display. The returned event list is kept
        for tests and ledger helpers but is not re-yielded by ``_execute_parallel``.

        RFC-211: Collects outcome metadata instead of full output string.
        IG-355: Fourth tuple element is joined ``task`` tool delegate-final text for finalize.
        RFC-214: When ``stream_thread_id`` branches off ``thread_id``, prepends deep-copied
        ``execute_step`` ledger rows for transitive dependency predecessors.

        Args:
            step: StepAction with description and optional hints
            thread_id: Logical thread ID for StepResult, logs, and durability lookups
            workspace: Thread-specific workspace path (RFC-103)
            stream_thread_id: Optional LangGraph ``thread_id`` for this stream (parallel isolation)
            routing_classification: Loop routing payload for middleware (IG-349, IG-383).
            git_status: Optional git snapshot for prompt XML (RFC-104).
            intent_type: Optional intent label for scenario guidance (IG-384).
            loop_state: When set and the graph uses a branched ``thread_id``, predecessor
                execute-step ledger messages are injected before this step's envelope.

        Returns:
            Tuple of ``(events, StepResult, AI messages for IG-199, delegate_final_text)``.
        """
        start = time.perf_counter()
        events: list[StreamEvent] = []
        output = ""  # Still collect for Layer 1 final report
        budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())
        outcomes: list[dict] = []  # RFC-211: Collect outcome metadata

        try:
            logger.debug(
                "execute step: id=%s desc=%s hints: subagent=%s",
                step.id,
                preview_first(step.description, 100),
                step.subagent,
            )

            cfg_thread = stream_thread_id or thread_id
            configurable: dict[str, Any] = {
                "thread_id": cfg_thread,
                "soothe_step_subagent": step.subagent,
                "soothe_step_expected_output": step.expected_output,
            }
            if workspace:
                configurable["workspace"] = workspace
            # RFC-217: Inject goal briefing on thread switch (for single-step execution)
            if self._goal_context_manager:
                goal_briefing = await self._goal_context_manager.get_execute_briefing()
                if goal_briefing:
                    configurable["soothe_goal_briefing"] = goal_briefing
                    logger.info(
                        "Execute briefing injected for step %s (%d chars)",
                        step.id,
                        len(goal_briefing),
                    )
            configurable.update(await self._claude_runner_config_extras(thread_id))
            # Pass current_decision for middleware to inject agent loop output contract
            # when available on ``loop_state`` (sequential chunk path); parallel branches
            # may still omit it here because middleware reads configurable elsewhere.
            config: dict[str, Any] = {"configurable": configurable}
            if self._config is not None:
                config = self._executor_langfuse_merge_for_stream(config, thread_id=cfg_thread)

            # Build user message envelope with execution hints (RFC-214)
            from soothe.core.prompts.user_envelope import build_execute_step_envelope

            goal_for_envelope = loop_state.goal if loop_state else None
            graph_input_messages: list[BaseMessage] = []
            use_parallel_branch = (
                stream_thread_id is not None
                and stream_thread_id != thread_id
                and loop_state is not None
                and loop_state.current_decision is not None
            )
            if use_parallel_branch:
                preds = transitive_dependency_step_ids(step, loop_state.current_decision)
                if preds:
                    cap = self._branch_predecessor_message_cap()
                    graph_input_messages = predecessor_execute_messages_for_branch(
                        loop_state.loop_messages,
                        preds,
                        max_messages=cap,
                    )
                    if graph_input_messages:
                        logger.info(
                            "[BranchPred] step=%s injected %d predecessor ledger msgs (cap=%d)",
                            step.id,
                            len(graph_input_messages),
                            cap,
                        )

            hints_parts: list[str] = []
            if step.subagent:
                hints_parts.append(f"Suggested subagent: {step.subagent}")
            if step.expected_output:
                hints_parts.append(f"Expected output: {step.expected_output}")
            execution_hints = None
            if hints_parts:
                execution_hints = (
                    ". ".join(hints_parts) + ". Consider using the suggested approach first."
                )

            envelope = build_execute_step_envelope(
                goal=goal_for_envelope,
                step_description=step.description,
                execution_hints=execution_hints,
                goal_user_submission=loop_state.goal_user_submission if loop_state else None,
            )
            logger.debug("[Human Message Envelope] %s", log_preview(envelope, chars=150))
            human_msg = LoopHumanMessage(
                content=envelope,
                thread_id=thread_id,
                iteration=None,
                goal_summary=None,
                workspace=workspace,
                phase="execute_step",
            )
            graph_input_messages.append(human_msg)
            stream = self._core_agent_astream_with_hitl(
                self._execute_graph_input(
                    graph_input_messages,
                    routing_classification=routing_classification,
                    workspace=workspace,
                    git_status=git_status,
                    intent_type=intent_type,
                ),
                config,
            )

            # Stream events and collect outcome metadata (RFC-211)
            tool_call_count = 0
            messages: list[BaseMessage] = []
            delegate_final = ""
            async for (
                final_output,
                event,
                tc_count,
                msg_list,
                df,
            ) in self._stream_and_collect(
                stream,
                budget=budget,
                step_id=step.id,
            ):
                if event is not None:
                    _append_parallel_stream_event(events, event, live_event_queue)
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count
                    messages = msg_list
                    delegate_final = df

            duration_ms = int((time.perf_counter() - start) * 1000)

            # Note: tool_call_ids are now in unified format within messages chunks
            # No separate binding events needed (IG-416 simplified design)

            # RFC-211: Aggregate outcomes from all tools in this step
            # Use the first outcome as primary (future: merge multiple)
            primary_outcome = (
                outcomes[0]
                if outcomes
                else {
                    "type": "generic",
                    "tool_name": "unknown",
                    "tool_call_id": f"step_{step.id}",
                    "success_indicators": {},
                    "entities": [],
                    "size_bytes": len(output.encode("utf-8")),
                }
            )

            # IG-148: Add CoreAgent input/output evidence
            primary_outcome["step_input"] = envelope  # HumanMessage content sent to Layer 1
            primary_outcome["output_summary"] = create_output_summary(output)  # Truncated findings

            logger.info(
                "Step %s completed successfully in %dms (tool_calls: %d, subagent_cap_hit=%s)",
                step.id,
                duration_ms,
                tool_call_count,
                budget.hit_subagent_cap,
            )

            return (
                events,
                StepResult(
                    step_id=step.id,
                    success=True,
                    outcome=primary_outcome,  # RFC-211: outcome metadata
                    duration_ms=duration_ms,
                    thread_id=thread_id,
                    tool_call_count=tool_call_count,
                    subagent_task_completions=budget.subagent_task_completions,
                    hit_subagent_cap=budget.hit_subagent_cap,
                ),
                messages,
                delegate_final,
            )

        except asyncio.CancelledError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "Step %s cancelled after %dms [subagent=%s]",
                step.id,
                duration_ms,
                step.subagent,
            )
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if _is_expected_connection_refusal(e):
                logger.warning(
                    "Step %s failed after %dms [subagent=%s]: %s",
                    step.id,
                    duration_ms,
                    step.subagent,
                    _format_connection_refusal_message(e),
                )
            else:
                logger.exception(
                    "Step %s failed after %dms [subagent=%s]",
                    step.id,
                    duration_ms,
                    step.subagent,
                )

            error_msg = self._extract_error_message(e, "Step execution failed")

            return (
                events,
                StepResult(
                    step_id=step.id,
                    success=False,
                    outcome={"type": "error", "error": error_msg},  # RFC-211: error outcome
                    error=error_msg,
                    error_type=self._classify_error_severity(e),
                    duration_ms=duration_ms,
                    thread_id=thread_id,
                    subagent_task_completions=0,
                    hit_subagent_cap=False,
                ),
                [],
                "",
            )

    async def _stream_and_collect(
        self,
        stream: AsyncGenerator,
        *,
        budget: _ActStreamBudget | None = None,
        step_id: str | None = None,
    ) -> AsyncGenerator[
        tuple[str | None, StreamEvent | None, int, list[BaseMessage], str],
        None,
    ]:
        """Stream events immediately while accumulating output and counting tool calls.

        This is the canonical streaming method that yields events as they arrive
        for real-time display, while also collecting output content for the final
        result.

        RFC-211: Also extracts tool_call_id and generates outcome metadata.
        IG-151: Collects AIMessage objects for token usage extraction.
        IG-355: Collects ``task`` tool return text (delegate finals) for goal completion when
        subgraph AIMessages are not folded into root-graph act aggregation.
        IG-416: Rewrites root-graph AI and ``ToolMessage`` ``tool_call_id`` values to unified
        ``{step_id}:s:{tool_fragment}`` so streamed tool rows and tool results share stable ids.

        Args:
            stream: Async iterator from agent.astream()
            budget: Optional Act wave budget (subagent ``task`` cap, IG-130).
            step_id: When set, rewrite root-graph tool_call_ids to unified format
                ``{step_id}:s:{tool_fragment}`` for consistent TUI rendering.

        Yields:
            Tuple of ``(output, event, tool_call_count, messages, delegate_final_text)``:
            - When event is not None: immediate display chunk (delegate_final_text empty).
            - At end: combined_output, ``tool_call_count`` (root graph plus namespaced
              subgraph ``ToolMessage`` totals), root AIMessages list, and joined ``task``
              tool bodies (ordered, capped)—empty string when no ``task`` tools ran.
        """
        from langchain_core.messages import AIMessage, AIMessageChunk

        from soothe.core.loop.engine.metadata_generator import (
            generate_outcome_metadata,
        )
        from soothe.core.loop.utils.stream_normalize import (
            extract_text_from_message_content,
            iter_messages_for_act_aggregation,
            iter_messages_for_delegate_task_scan,
            iter_namespaced_tool_messages,
            join_text_fragments,
        )

        chunks: list[str] = []
        tool_call_count = 0
        subgraph_tool_call_count = 0
        messages: list[BaseMessage] = []  # IG-151: Collect messages for token extraction
        delegate_task_final_parts: list[str] = []
        delegate_task_ids_seen: set[str] = set()

        # RFC-211: Collect per-tool outcome metadata (structured, no filesystem cache; IG-387)
        outcomes: list[dict] = []

        stream_chunk_count = 0  # Debug counter

        def _maybe_cap_subagent_tasks(msg: ToolMessage) -> bool:
            """Return True if the stream must stop (cap exceeded)."""
            if budget is None:
                return False
            if getattr(msg, "name", "") != "task":
                return False
            budget.subagent_task_completions += 1
            cap = budget.max_subagent_tasks_per_wave
            if cap > 0 and budget.subagent_task_completions > cap:
                budget.hit_subagent_cap = True
                logger.warning(
                    "Subagent task cap reached (%s > %s); stopping Act stream consumption",
                    budget.subagent_task_completions,
                    cap,
                )
                return True
            return False

        async for chunk in stream:
            stream_chunk_count += 1

            # Handle tuple format (namespace, mode, data) - deepagents canonical
            if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                _ns_chunk, mode_chunk, data_chunk = chunk
                # IG-416: Unify message tool_call_ids for client row/result matching.
                emit_chunk = chunk
                if (
                    step_id
                    and mode_chunk == "messages"
                    and isinstance(data_chunk, (list, tuple))
                    and len(data_chunk) >= 2
                ):
                    msg0 = data_chunk[0]
                    task_idx = 0 if _ns_chunk else None
                    if isinstance(msg0, (AIMessage, AIMessageChunk)):
                        modified_msg = _rewrite_tool_call_ids_to_unified(
                            msg0, step_id, task_idx=task_idx
                        )
                        if modified_msg is not msg0:
                            emit_chunk = (_ns_chunk, mode_chunk, (modified_msg, data_chunk[1]))
                    elif isinstance(msg0, ToolMessage):
                        modified_msg = _rewrite_tool_message_tool_call_id(
                            msg0, step_id, task_idx=task_idx
                        )
                        if modified_msg is not msg0:
                            emit_chunk = (_ns_chunk, mode_chunk, (modified_msg, data_chunk[1]))
                yield None, emit_chunk, 0, [], ""
                chunk = emit_chunk

            stop_act_stream = False
            for msg in iter_messages_for_act_aggregation(chunk):
                if isinstance(msg, ToolMessage):
                    tool_call_count += 1
                    tool_call_id = msg.tool_call_id
                    tool_name = msg.name or "unknown"

                    if _maybe_cap_subagent_tasks(msg):
                        stop_act_stream = True
                        break

                    content = msg.content
                    text_out = extract_text_from_message_content(content)
                    if text_out:
                        # Truncate large tool outputs in aggregated stream text; full payloads
                        # remain in CoreAgent graph state (and deepagents eviction when enabled).
                        max_tool_output_chars = 10_000
                        if len(text_out) > max_tool_output_chars:
                            truncated = preview(
                                text_out,
                                mode="chars",
                                first=max_tool_output_chars // 2,
                                last=max_tool_output_chars // 2,
                            )
                            chunks.append(truncated)
                        else:
                            chunks.append(text_out)

                    outcome = generate_outcome_metadata(tool_name, content, tool_call_id)

                    outcomes.append(outcome)

                    if tool_name == "task" and text_out.strip():
                        tc_id = tool_call_id or ""
                        if not (tc_id and tc_id in delegate_task_ids_seen):
                            if tc_id:
                                delegate_task_ids_seen.add(tc_id)
                            clipped = text_out.strip()
                            if len(clipped) > _DELEGATE_FINAL_PER_TASK_CAP:
                                clipped = clipped[:_DELEGATE_FINAL_PER_TASK_CAP]
                            delegate_task_final_parts.append(clipped)

                    # Log tool outcome (IG-416: args no longer tracked separately)
                    logger.debug(
                        "Tool #%d %s(%s) → %s, %dB",
                        tool_call_count,
                        tool_name,
                        tool_call_id,
                        outcome.get("type", "unknown"),
                        outcome.get("size_bytes", 0),
                    )
                elif isinstance(msg, AIMessageChunk):
                    messages.append(msg)  # Collect chunks for assistant text extraction
                    t = extract_text_from_message_content(msg.content)
                    if t:
                        chunks.append(t)
                elif isinstance(msg, AIMessage):
                    messages.append(msg)
                    t = extract_text_from_message_content(msg.content)
                    if t:
                        chunks.append(t)
                        logger.debug("[AI Message] %s", log_preview(t, chars=150))

            for ns_tuple, tm in iter_namespaced_tool_messages(chunk):
                subgraph_tool_call_count += 1
                body_preview = log_preview(
                    extract_text_from_message_content(getattr(tm, "content", "")),
                    chars=160,
                )
                logger.info(
                    "[SubagentTool] ns=%s name=%s id=%s preview=%s",
                    "/".join(ns_tuple) if ns_tuple else "()",
                    getattr(tm, "name", "") or "unknown",
                    getattr(tm, "tool_call_id", "") or "",
                    body_preview,
                )

            for task_msg in iter_messages_for_delegate_task_scan(chunk):
                text_out = extract_text_from_message_content(task_msg.content)
                if not text_out.strip():
                    continue
                tc_id = getattr(task_msg, "tool_call_id", "") or ""
                if tc_id and tc_id in delegate_task_ids_seen:
                    continue
                if tc_id:
                    delegate_task_ids_seen.add(tc_id)
                clipped = text_out.strip()
                if len(clipped) > _DELEGATE_FINAL_PER_TASK_CAP:
                    clipped = clipped[:_DELEGATE_FINAL_PER_TASK_CAP]
                delegate_task_final_parts.append(clipped)

            if stop_act_stream:
                break

            if isinstance(chunk, dict) and "model" not in chunk:
                if "content" in chunk:
                    chunks.append(str(chunk["content"]))
                elif "output" in chunk:
                    chunks.append(str(chunk["output"]))
                elif "text" in chunk:
                    chunks.append(str(chunk["text"]))
            elif hasattr(chunk, "content") and not isinstance(chunk, (tuple, dict)):
                chunks.append(str(chunk.content))

        delegate_final_text = ""
        if delegate_task_final_parts:
            delegate_final_text = "\n\n".join(delegate_task_final_parts)
            if len(delegate_final_text) > DELEGATE_FINAL_WAVE_CAP:
                delegate_final_text = delegate_final_text[:DELEGATE_FINAL_WAVE_CAP]

        total_tool_calls = tool_call_count + subgraph_tool_call_count
        # Final yield with combined output and tool call count
        # IG-416: No longer return tool_call_ids set - IDs are now in unified format in messages
        yield (
            join_text_fragments(chunks),
            None,
            total_tool_calls,
            messages,
            delegate_final_text,
        )

    def _build_batch_human_messages(
        self,
        steps: list,
        state: LoopState,
    ) -> list[LoopHumanMessage]:
        """Build N LoopHumanMessage inputs for batch execution (RFC-214).

        Each step gets its own LoopHumanMessage with the user message envelope:
        <CURRENT_GOAL>, <USER_QUERY>, then ``--- Context ---`` and <DYNAMIC_CONTEXT>
        (execution hints, timestamp, and related context).

        Args:
            steps: Steps to execute in this wave
            state: Current loop state with iteration/thread context

        Returns:
            List of LoopHumanMessage instances (one per step)
        """
        from soothe.core.prompts.user_envelope import build_execute_step_envelope

        messages = []
        for step in steps:
            # Build execution hints from step metadata (RFC-214: hints in user envelope)
            hints_parts: list[str] = []
            if step.subagent:
                hints_parts.append(f"Suggested subagent: {step.subagent}")
            if step.expected_output:
                hints_parts.append(f"Expected output: {step.expected_output}")
            execution_hints = None
            if hints_parts:
                execution_hints = (
                    ". ".join(hints_parts) + ". Consider using the suggested approach first."
                )

            envelope = build_execute_step_envelope(
                goal=state.goal,
                step_description=step.description,
                execution_hints=execution_hints,
                goal_user_submission=state.goal_user_submission,
            )
            msg = LoopHumanMessage(
                content=envelope,
                thread_id=state.thread_id,
                iteration=state.iteration,
                goal_summary=state.goal[:200] if state.goal else None,
                workspace=state.workspace,
                phase="execute_step",
                step_id=step.id,
            )
            messages.append(msg)

        return messages

    def _ledger_execute_ai_content(
        self,
        *,
        messages: list[BaseMessage],
        final_ai_msg: BaseMessage,
        total_steps: int,
    ) -> str:
        """Body for ``LoopAIMessage`` ledger entries (RFC-214, IG-373).

        The stream collector may end with an ``AIMessage`` whose ``content`` is empty while
        assistant-visible text lives in earlier ``AIMessageChunk`` entries — same situation as
        ``_assemble_assistant_text_from_stream_messages`` / Act-wave finalize.

        Args:
            messages: Full message list from ``_stream_and_collect`` (AI + chunk entries).
            final_ai_msg: AIMessage chosen for this step by sequential pairing.
            total_steps: Number of steps in this execute wave.

        Returns:
            Non-empty string when any root assistant text exists; otherwise ``""``.
        """
        from soothe.core.loop.utils.stream_normalize import extract_text_from_message_content

        direct = extract_text_from_message_content(getattr(final_ai_msg, "content", None)).strip()
        if direct:
            return direct
        if total_steps != 1:
            return ""
        assembled = self._assemble_assistant_text_from_stream_messages(messages).strip()
        return assembled

    def _extract_sequential_outcomes(
        self,
        messages: list[BaseMessage],
        steps: list,
        state: LoopState,
    ) -> dict[str, LoopAIMessage]:
        """Extract outcomes from sequential batch (RFC-214).

        Sequential execution produces messages in order.
        Rule: For N steps, assign last N AIMessages to steps in order.

        Args:
            messages: All messages from batch execution stream
            steps: Steps being executed (for step_id matching)
            state: Current loop state

        Returns:
            step_id → LoopAIMessage mapping (one outcome per step)
        """
        from langchain_core.messages import AIMessage

        ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]

        step_outcomes = {}
        if len(ai_messages) >= len(steps):
            # Assign last N AIMessages to steps (sequential order)
            for i, step in enumerate(steps):
                final_ai_msg = ai_messages[-(len(steps) - i)]
                ledger_body = self._ledger_execute_ai_content(
                    messages=messages,
                    final_ai_msg=final_ai_msg,
                    total_steps=len(steps),
                )

                step_outcomes[step.id] = LoopAIMessage(
                    content=ledger_body or final_ai_msg.content,
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    phase="execute_step",
                    step_id=step.id,
                    response_metadata=getattr(final_ai_msg, "response_metadata", {}),
                )
        else:
            # Fallback: insufficient messages → error outcomes
            for i, step in enumerate(steps):
                if i < len(ai_messages):
                    final_ai_msg = ai_messages[i]
                    ledger_body = self._ledger_execute_ai_content(
                        messages=messages,
                        final_ai_msg=final_ai_msg,
                        total_steps=len(steps),
                    )
                    step_outcomes[step.id] = LoopAIMessage(
                        content=ledger_body or final_ai_msg.content,
                        thread_id=state.thread_id,
                        iteration=state.iteration,
                        phase="execute_step",
                        step_id=step.id,
                    )
                else:
                    # No AIMessage for this step → error outcome
                    step_outcomes[step.id] = LoopAIMessage(
                        content="Step execution failed: no AI response",
                        thread_id=state.thread_id,
                        iteration=state.iteration,
                        phase="execute_step",
                        step_id=step.id,
                    )

        return step_outcomes

    def _record_batch_ledger_pairs(
        self,
        state: LoopState,
        step_messages: list[LoopHumanMessage],
        step_outcomes: dict[str, LoopAIMessage],
        steps: list,
        *,
        duration_ms: int,
        subagent_task_completions: int = 0,
        hit_subagent_cap: bool = False,
        tool_call_count: int = 0,
    ) -> list:
        """Record N adjacent Human-AI pairs in ledger (RFC-214).

        Each step gets paired Human-AI messages in ledger:
        - LoopHumanMessage (input)
        - LoopAIMessage (outcome)
        - Both share same step_id
        - Adjacent in ledger

        Args:
            state: LoopState with ledger (loop_messages field)
            step_messages: Human inputs (one per step)
            step_outcomes: AI outcomes (one per step)
            steps: Step metadata
            duration_ms: Wall time for the whole wave; split across steps so sums match
                goal duration aggregation.
            subagent_task_completions: Count of completed ``task`` tool returns this wave (IG-130).
            hit_subagent_cap: True when the wave stopped early due to subagent cap.
            tool_call_count: Total tool messages observed this wave (first step carries count).

        Returns:
            List of StepResult for metrics/execution tracking
        """
        from soothe.core.loop.state.schemas import StepResult

        # Validate pairing
        assert len(step_messages) == len(steps)
        assert set(step_outcomes.keys()) == {s.id for s in steps}

        n = len(steps)
        base, rem = divmod(max(duration_ms, 0), n) if n else (0, 0)
        step_durations = [base + (1 if j < rem else 0) for j in range(n)]

        # Append N adjacent pairs to ledger
        for i, step in enumerate(steps):
            human_msg = step_messages[i]
            ai_msg = step_outcomes[step.id]

            # Append Human message
            state.loop_messages.append(human_msg)

            # Append AI message (adjacent)
            state.loop_messages.append(ai_msg)

        # Build StepResult for metrics (RFC-211 outcome metadata)
        step_results = []
        for idx, step in enumerate(steps):
            ai_msg = step_outcomes[step.id]

            result = StepResult(
                step_id=step.id,
                success=True,  # Or based on AI message content analysis
                outcome={
                    "type": "generic",
                    "output_summary": ai_msg.content[:300] if ai_msg.content else "",
                },
                duration_ms=step_durations[idx],
                thread_id=state.thread_id,
                tool_call_count=tool_call_count if idx == 0 else 0,
                subagent_task_completions=subagent_task_completions if idx == 0 else 0,
                hit_subagent_cap=hit_subagent_cap if idx == 0 else False,
            )
            step_results.append(result)

        return step_results

    def _build_sequential_input(self, steps: list) -> str:
        """Build combined input for sequential execution.

        Args:
            steps: Steps to combine

        Returns:
            Combined input string
        """
        descriptions = [f"{i + 1}. {step.description}" for i, step in enumerate(steps)]
        body = "Execute these steps sequentially:\n" + "\n".join(descriptions)
        return body

    def _extract_error_message(self, exc: Exception, fallback: str) -> str:
        """Extract meaningful error message from exception.

        Parses common error types (especially OpenAI API errors) to extract
        actionable information for the judge to understand failures.

        IG-295: Enhanced timeout errors include retry metadata for planner revision.

        Args:
            exc: The exception that occurred
            fallback: Fallback message if no specific info found

        Returns:
            Meaningful error message string
        """
        from soothe.middleware.llm_rate_limit import EnhancedTimeoutError

        if _is_expected_connection_refusal(exc):
            return _format_connection_refusal_message(exc)

        # IG-295: Enhanced timeout error with metadata
        if isinstance(exc, EnhancedTimeoutError):
            parts = [
                f"Request timed out after {exc.retries} retries",
                f"({exc.timeout_seconds}s timeout)",
            ]
            if exc.prompt_chars > 50000:
                parts.append(f"- large prompt ({exc.prompt_chars:,} chars)")

            return " ".join(parts)

        error_str = str(exc)

        # Check for OpenAIBadRequestError with context length issues
        if "invalid_parameter_error" in error_str or "Range of input length should be" in error_str:
            return "Input exceeded model context limit (too large)"

        # Check for rate limiting
        if "rate_limit" in error_str.lower() or "429" in error_str:
            return "Rate limited - too many requests"

        # Check for authentication/permission errors
        if "401" in error_str or "403" in error_str or "permission" in error_str.lower():
            return "Permission/authentication error"

        # Check for timeout (generic TimeoutError)
        if "timeout" in error_str.lower():
            return "Request timed out"

        # Check for connection errors
        if "connection" in error_str.lower() or "network" in error_str.lower():
            return "Network/connection error"

        # For other errors, try to extract the error type but keep it concise
        exc_type = type(exc).__name__
        if exc_type != "Exception":
            # Include exception type but truncate long messages
            return f"{exc_type}: {preview_first(error_str, 200)}"

        return fallback

    def _classify_error_severity(self, exc: Exception) -> str:
        """Classify error severity using structured SDK error codes.

        Determines whether an error is fatal (non-retryable) or retryable
        by checking SDK-specific attributes rather than keyword matching.

        Non-retryable errors:
        - LangChain ContextOverflowError (context limit exceeded)
        - HTTP 401 (authentication error)
        - HTTP 403 (permission denied)
        - HTTP 413 (request too large)
        - OpenAI error code "invalid_parameter_error"

        Retryable errors (IG-295):
        - EnhancedTimeoutError (timeout with retries exhausted at middleware)

        Args:
            exc: The exception to classify

        Returns:
            "fatal" for non-retryable errors, "execution" for retryable errors
        """
        from langchain_core.exceptions import ContextOverflowError

        from soothe.middleware.llm_rate_limit import EnhancedTimeoutError

        # Enhanced timeout error (IG-295) - retries exhausted at middleware
        if isinstance(exc, EnhancedTimeoutError):
            # Classified as "execution" (retryable) but retries already attempted
            # Planner can still revise plan based on timeout metadata
            return "execution"

        # LangChain dedicated context limit exception
        if isinstance(exc, ContextOverflowError):
            return "fatal"

        # Check status_code attribute (OpenAI/Anthropic APIStatusError)
        status_code = getattr(exc, "status_code", None)
        if status_code in (401, 403, 413):  # Auth/Permission/Too Large
            return "fatal"

        # OpenAI error code attribute
        error_code = getattr(exc, "code", None)
        if error_code == "invalid_parameter_error":
            return "fatal"

        return "execution"
