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
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langgraph.types import Command, Interrupt
from soothe_sdk.ux.task_namespace import (
    _shorten_tool_call_id,
    normalize_unified_tool_call_id,
    parse_unified_tool_call_id,
)

from soothe.core.context.model_override import (
    attach_stream_model_override,
    reset_stream_model_override,
)
from soothe.core.loop.engine.graph_interrupt import (
    _MAX_INTERRUPT_ITERATIONS,
    await_next_graph_stream_chunk,
    build_auto_resume_payload,
)
from soothe.core.loop.engine.metadata_generator import (
    PLANNER_OUTCOME_PREVIEW_CAP,
)
from soothe.core.loop.engine.predecessor_branch_context import (
    predecessor_execute_messages_for_branch,
    prior_loop_execute_messages,
    transitive_dependency_step_ids,
)
from soothe.core.loop.engine.thread_fork_manager import ThreadForkManager
from soothe.core.loop.engine.tool_call_args import (
    ToolCallArgsCollector,
    filter_redundant_stream_tool_updates,
    format_args_for_log,
    wire_updates_from_ai_message,
)
from soothe.core.loop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepResult,
)
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.middleware.tool_concurrency import init_tool_concurrency_for_thread
from soothe.utils.network_errors import (
    format_tool_network_error as _format_tool_network_error,
)
from soothe.utils.network_errors import (
    is_recoverable_tool_network_error as _is_recoverable_tool_network_error,
)
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config
from soothe.utils.text_preview import create_output_summary, log_preview, preview, preview_first

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent

    from .goal_context_manager import GoalContextManager

logger = logging.getLogger(__name__)

# Per execute-step cap on root-graph tool results consumed from the Act stream.
_DEFAULT_MAX_TOOL_CALLS_PER_STEP = 99


def _wire_subagent_from_routing(routing_classification: Any | None) -> str | None:
    """Subagent name when wire routing requests explicit subagent delegation (IG-349)."""
    if routing_classification is None:
        return None
    if isinstance(routing_classification, dict):
        routing_hint = routing_classification.get("routing_hint")
        preferred = routing_classification.get("preferred_subagent")
    else:
        routing_hint = getattr(routing_classification, "routing_hint", None)
        preferred = getattr(routing_classification, "preferred_subagent", None)
    if routing_hint != "subagent" or not preferred:
        return None
    if isinstance(preferred, str):
        stripped = preferred.strip()
        return stripped or None
    return str(preferred) if preferred is not None else None


def _make_step_tool_call_id(step_id: str, raw_tid: str, call_idx: int) -> str:
    """Generate unified step-level tool call ID.

    Format: {step_wire}:s:{tool}:{idx}

    Examples:
        ('GHT-01', 'functions.task:0', 0) → 'GHT_01:s:task:0'
        ('GHT-01', 'functions.read_file:1', 1) → 'GHT_01:s:read_file:1'
    """
    from soothe_sdk.ux.task_namespace import _format_unified_tool_call_id

    short_tid = _shorten_tool_call_id(raw_tid)
    return _format_unified_tool_call_id(step_id, "s", short_tid)


def _make_task_inner_tool_call_id(
    step_id: str, task_idx: int, raw_tid: str, inner_call_idx: int
) -> str:
    """Generate unified task-level (subagent inner) tool call ID.

    Format: {step_wire}:t{task_idx}:{tool}:{idx}

    Examples:
        ('GHT-01', 0, 'functions.read_file:1', 0) → 'GHT_01:t0:read_file:1'
        ('GHT-01', 0, 'functions.grep:2', 1) → 'GHT_01:t0:grep:2'
    """
    from soothe_sdk.ux.task_namespace import _format_unified_tool_call_id

    short_tid = _shorten_tool_call_id(raw_tid)
    return _format_unified_tool_call_id(step_id, f"t{task_idx}", short_tid)


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


_TASK_KWARG_DESC_KEYS = ("description", "prompt", "task", "instruction")


def _coerce_tool_call_args_mapping(raw: Any) -> dict[str, Any]:
    """Normalize tool-call ``args`` to a dict when possible."""
    if isinstance(raw, dict):
        inp = raw.get("input")
        if isinstance(inp, dict) and inp:
            return dict(inp)
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            import json

            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass
    return {}


def _task_kwargs_have_description(args: dict[str, Any]) -> bool:
    for key in _TASK_KWARG_DESC_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return True
    return False


def _chunk_args_dict(chunk: dict[str, Any]) -> dict[str, Any]:
    """Extract parsed args from one ``tool_call_chunk`` block."""
    cargs = chunk.get("args")
    if isinstance(cargs, dict) and cargs:
        return dict(cargs)
    if isinstance(cargs, str) and cargs.strip():
        return _coerce_tool_call_args_mapping(cargs)
    return {}


def _backfill_tool_calls_args_from_chunks(msg: BaseMessage) -> BaseMessage:
    """Fill empty ``tool_calls[].args`` from ``tool_call_chunks`` on the same message.

      Some providers emit a terminal ``AIMessage`` whose ``tool_calls`` have ``{}`` while
      the accumulated chunk args on the same object are complete. The TUI needs those
    kwargs on ``tool_calls`` for wire deserialization and overlay seeding.
    """
    from copy import deepcopy

    from langchain_core.messages import AIMessage, AIMessageChunk

    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return msg
    chunks = getattr(msg, "tool_call_chunks", None) or []
    calls = getattr(msg, "tool_calls", None) or []
    if not chunks or not calls:
        return msg

    args_by_id: dict[str, dict[str, Any]] = {}
    args_by_index: dict[int, dict[str, Any]] = {}
    for tc in chunks:
        if not isinstance(tc, dict):
            continue
        parsed = _chunk_args_dict(tc)
        if not parsed:
            continue
        tid = str(tc.get("id") or "").strip()
        if tid:
            args_by_id[tid] = parsed
        idx_raw = tc.get("index")
        if idx_raw is not None:
            try:
                args_by_index[int(idx_raw)] = parsed
            except (TypeError, ValueError):
                pass

    if not args_by_id and not args_by_index:
        return msg

    changed = False
    new_calls: list[dict[str, Any]] = []
    for call_idx, tc in enumerate(calls):
        if not isinstance(tc, dict):
            new_calls.append(tc)
            continue
        tid = str(tc.get("id") or "").strip()
        existing_args = tc.get("args")
        empty = existing_args is None or existing_args == {} or existing_args == ""
        fill: dict[str, Any] | None = None
        if empty and tid and tid in args_by_id:
            fill = args_by_id[tid]
        elif empty and call_idx in args_by_index:
            fill = args_by_index[call_idx]
        if fill is not None:
            patched = dict(tc)
            patched["args"] = fill
            new_calls.append(patched)
            changed = True
        else:
            new_calls.append(tc)

    if not changed:
        return msg
    modified = deepcopy(msg)
    if hasattr(modified, "__dict__"):
        modified.__dict__["tool_calls"] = new_calls
    return modified


def _patch_task_tool_call_dict(
    tc: dict[str, Any],
    *,
    step_description: str,
    step_subagent: str | None,
) -> tuple[dict[str, Any], bool]:
    """Fill missing ``task`` kwargs from execute-step metadata (main graph only)."""
    if str(tc.get("name") or "").strip() != "task":
        return tc, False
    args = _coerce_tool_call_args_mapping(tc.get("args"))
    desc = (step_description or "").strip()
    sub = (step_subagent or "").strip() if step_subagent else ""
    if _task_kwargs_have_description(args):
        if sub and not str(args.get("subagent_type") or "").strip():
            merged = dict(args)
            merged["subagent_type"] = sub
            patched = dict(tc)
            patched["args"] = merged
            return patched, True
        return tc, False
    if not desc and not sub:
        return tc, False
    merged = dict(args)
    if desc:
        merged.setdefault("description", desc)
    if sub:
        merged.setdefault("subagent_type", sub)
    patched = dict(tc)
    patched["args"] = merged
    return patched, True


def _enrich_execute_step_task_kwargs_on_message(
    msg: BaseMessage,
    *,
    step_description: str,
    step_subagent: str | None,
    task_idx: int | None,
) -> BaseMessage:
    """Ensure main-graph ``task`` tool calls carry a description for TUI delegation cards.

    Parallel execute often streams ``tool_calls`` with empty ``args`` and no
    ``tool_call_chunks`` on the terminal chunk. The model still has the step brief in the
    HumanMessage envelope; copy wire ``preferred_subagent`` onto ``task`` kwargs when set
    at emit time so clients always receive a real delegation description.
    """
    from copy import deepcopy

    from langchain_core.messages import AIMessage, AIMessageChunk

    if task_idx is not None:
        return msg
    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return msg
    desc = (step_description or "").strip()
    sub = (step_subagent or "").strip() if step_subagent else ""
    if not desc and not sub:
        return msg

    changed = False
    modified = deepcopy(msg)

    new_calls: list[Any] = []
    for tc in getattr(modified, "tool_calls", None) or []:
        if isinstance(tc, dict):
            patched, did = _patch_task_tool_call_dict(
                tc, step_description=desc, step_subagent=sub or None
            )
            new_calls.append(patched)
            changed = changed or did
        else:
            new_calls.append(tc)
    if changed and hasattr(modified, "__dict__"):
        modified.__dict__["tool_calls"] = new_calls

    new_chunks: list[Any] = []
    chunk_changed = False
    for tc in getattr(modified, "tool_call_chunks", None) or []:
        if isinstance(tc, dict):
            chunk_tc = dict(tc)
            if str(chunk_tc.get("name") or "").strip() == "task":
                inner_args = _chunk_args_dict(chunk_tc)
                if not _task_kwargs_have_description(inner_args):
                    merged = dict(inner_args)
                    if desc:
                        merged.setdefault("description", desc)
                    if sub:
                        merged.setdefault("subagent_type", sub)
                    import json

                    chunk_tc["args"] = json.dumps(merged, separators=(",", ":"))
                    chunk_changed = True
            new_chunks.append(chunk_tc)
        else:
            new_chunks.append(tc)
    if chunk_changed and hasattr(modified, "__dict__"):
        modified.__dict__["tool_call_chunks"] = new_chunks
        changed = True

    return modified if changed else msg


def _stringify_tool_call_chunk_args_on_message(msg: BaseMessage) -> BaseMessage:
    """Ensure ``tool_call_chunks[].args`` are JSON strings (LangChain wire invariant)."""
    from copy import deepcopy

    from langchain_core.messages import AIMessage, AIMessageChunk

    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return msg
    chunks = getattr(msg, "tool_call_chunks", None) or []
    if not chunks:
        return msg

    changed = False
    new_chunks: list[Any] = []
    for tc in chunks:
        if not isinstance(tc, dict):
            new_chunks.append(tc)
            continue
        block = dict(tc)
        args = block.get("args")
        if isinstance(args, dict):
            block["args"] = json.dumps(args, separators=(",", ":"))
            changed = True
        new_chunks.append(block)
    if not changed:
        return msg
    modified = deepcopy(msg)
    if hasattr(modified, "__dict__"):
        modified.__dict__["tool_call_chunks"] = new_chunks
    return modified


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
        if parsed_sid == sid and type_code == "s":
            return False
        if parsed_sid == sid and type_code == "t" and task_idx is not None:
            return False
        return True

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
        parsed_sid, type_code, _, _ = parse_unified_tool_call_id(raw_id)
        if parsed_sid and type_code in ("s", "t"):
            return normalize_unified_tool_call_id(raw_id)
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
    if parsed_sid and type_code in ("s", "t"):
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
    max_tool_calls_per_step: int = _DEFAULT_MAX_TOOL_CALLS_PER_STEP
    subagent_task_completions: int = 0
    tool_call_count: int = 0
    hit_subagent_cap: bool = False
    hit_tool_budget: bool = False


@dataclass(frozen=True, slots=True)
class StepWaveQueued:
    """Ready steps waiting for a later execute batch (``max_parallel_steps`` cap)."""

    steps: tuple[StepAction, ...]


@dataclass(frozen=True, slots=True)
class StepWaveStart:
    """Marks the start of a bounded execute batch (``max_parallel_steps`` cap).

    Emitted before a wave runs so UIs can show only actively executing steps as
    ``running``; overflow ready steps are announced via :class:`StepWaveQueued`.
    """

    steps: tuple[StepAction, ...]


@dataclass(slots=True)
class _ParallelStepDone:
    """Sentinel placed on the parallel live-event queue when one step finishes."""

    step_id: str
    payload: tuple[list[StreamEvent], StepResult, list[BaseMessage], str] | BaseException


_TUPLE_LEN = 3
# ``task`` tool return text cap per invocation before joining (delegate finals).
_DELEGATE_FINAL_PER_TASK_CAP = 80_000


def _first_tool_error_message(outcomes: list[dict[str, Any]]) -> str:
    """Return the first tool error preview from RFC-211 outcome metadata."""
    for outcome in outcomes:
        if outcome.get("has_error"):
            preview = outcome.get("error_preview")
            if preview:
                return str(preview)[:200]
            tool_name = outcome.get("tool_name") or "tool"
            return f"{tool_name} failed"
    return "Tool execution error"


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

    This component handles step execution with two modes:
    - parallel: Execute ready steps with isolated per-step CoreAgent runs (chunked by
      ``max_parallel_steps``)
    - dependency: Execute steps respecting dependency DAG (chunked parallel waves)

    Events from CoreAgent are propagated through for upstream consumption.
    """

    def __init__(
        self,
        core_agent: CoreAgent,
        *,
        checkpointer: Any | None = None,
        max_parallel_steps: int = 16,
        config: SootheConfig | None = None,
        goal_context_manager: GoalContextManager | None = None,
        loop_id: str | None = None,
    ) -> None:
        """Initialize Execute phase.

        Args:
            core_agent: Layer 1 CoreAgent for step execution
            checkpointer: LangGraph checkpointer for thread fork inheritance (RFC-223).
            max_parallel_steps: Max steps to run **concurrently** in one batch. ``execute`` repeats
                batches until all ready steps finish (e.g. 4 ready steps and ``2`` → two batches of 2).
                ``0`` means unlimited (RFC-201 / concurrency).
            config: Optional Soothe config for Act wave caps (IG-130).
            goal_context_manager: Optional GoalContextManager for goal briefing injection (RFC-217).
            loop_id: Optional loop identifier for Langfuse trace correlation.
        """
        self.core_agent = core_agent
        self._checkpointer = checkpointer
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
        return max(0, int(self._config.agent.loop.max_subagent_tasks_per_wave))

    @staticmethod
    def _max_tool_calls_per_step() -> int:
        return _DEFAULT_MAX_TOOL_CALLS_PER_STEP

    @staticmethod
    def _build_step_outcome_from_stream(
        *,
        outcomes: list[dict[str, Any]],
        output: str,
        hit_tool_budget: bool,
        step_id: str | None = None,
        fallback_tool_name: str = "unknown",
    ) -> dict[str, Any]:
        """Merge streamed tool outcomes and text into one StepResult outcome dict."""
        if outcomes:
            primary: dict[str, Any] = dict(outcomes[-1])
            if len(outcomes) > 1:
                primary["tools_completed"] = len(outcomes)
        else:
            primary = {
                "type": "generic",
                "tool_name": fallback_tool_name,
                "tool_call_id": f"step_{step_id}" if step_id else "",
                "success_indicators": {},
                "entities": [],
                "size_bytes": len(output.encode("utf-8")) if output else 0,
            }
        if output.strip():
            primary["output_summary"] = create_output_summary(output)
            stripped = output.strip()
            cap = PLANNER_OUTCOME_PREVIEW_CAP
            primary["wave_join_preview"] = stripped[:cap] + ("…" if len(stripped) > cap else "")
        if hit_tool_budget:
            primary["tool_budget_exhausted"] = True
            primary["tools_completed"] = primary.get("tools_completed") or len(outcomes)
        return primary

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
        cap = int(self._config.agent.loop.plan_prompt_ledger.plan_ledger_max_messages)
        if cap > 0:
            return min(cap, 256)
        return DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES

    async def _core_agent_astream_with_interrupt_resume(
        self,
        stream_input: dict[str, Any] | Command,
        graph_config: dict[str, Any],
    ) -> AsyncGenerator[Any, None]:
        """Run ``CoreAgent.astream`` with LangGraph interrupt auto-resume."""
        interrupt_iterations = 0
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

            interrupt_iterations += 1
            if interrupt_iterations > _MAX_INTERRUPT_ITERATIONS:
                logger.warning(
                    "CoreAgent interrupt resume: exceeded iteration limit (%d); stopping stream",
                    _MAX_INTERRUPT_ITERATIONS,
                )
                return

            resume_payload = build_auto_resume_payload(pending_interrupts)
            current_input = Command(resume=resume_payload)

    @staticmethod
    def _execute_graph_input(
        messages: list[Any],
        *,
        routing_classification: Any | None = None,
        workspace: str | None = None,
        git_status: dict[str, Any] | None = None,
        continue_loop_mode: bool = False,
        synthesis_scenario: str | None = None,
        skill_activation: dict[str, Any] | None = None,
        mcp_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build LangGraph input for execute waves (RFC-225 carries continue_loop_mode)."""
        out: dict[str, Any] = {"messages": messages}
        if routing_classification is not None:
            out["routing_classification"] = routing_classification
        if workspace:
            out["workspace"] = workspace
        if git_status is not None:
            out["git_status"] = git_status
        if continue_loop_mode:
            out["continue_loop_mode"] = True
        if synthesis_scenario:
            out["synthesis_scenario"] = synthesis_scenario
        if skill_activation is not None:
            out["skill_activation"] = skill_activation
        if mcp_state is not None:
            out.update(mcp_state)
        return out

    @staticmethod
    def _seed_skill_activation(loop_state: LoopState) -> dict[str, Any] | None:
        """Rehydrate ``skill_activation`` from LoopState for graph input (RFC-105).

        Also registers slash-invoked skills (``/skill:`` expansion) via
        ``mark_invoked`` so the progressive loading registry tracks them.

        Returns ``None`` when no skill-activation data exists on the LoopState,
        so the middleware's ``abefore_agent`` will lazy-init a fresh dict.
        """
        has_prior = loop_state.activated_skill_names or loop_state.invoked_skill_names
        has_slash = loop_state.slash_invoked_skill_name and loop_state.slash_invoked_skill_body

        if not has_prior and not has_slash:
            return None

        activation: dict[str, Any] = {
            "sent": set(loop_state.sent_skill_names),
            "activated": set(loop_state.activated_skill_names),
            "invoked": set(loop_state.invoked_skill_names),
            "invoked_bodies": dict(loop_state.invoked_skill_bodies),
            "just_invoked": set(),
        }

        if has_slash:
            from soothe.skills.registry import ProgressiveSkillRegistry

            registry = ProgressiveSkillRegistry()
            registry.mark_invoked(
                activation,
                loop_state.slash_invoked_skill_name,  # type: ignore[arg-type]
                loop_state.slash_invoked_skill_body,  # type: ignore[arg-type]
            )

        return activation

    @staticmethod
    def _snapshot_skill_activation(
        graph_output: dict[str, Any] | None,
        loop_state: LoopState,
    ) -> None:
        """Copy ``skill_activation`` from graph output back into LoopState (RFC-105).

        Also clears slash invocation signal fields — they are consumed once by
        ``_seed_skill_activation`` and should not persist across iterations.

        Best-effort: missing or malformed ``skill_activation`` is silently skipped.
        """
        if not graph_output:
            return
        activation = graph_output.get("skill_activation")
        if not isinstance(activation, dict):
            return
        loop_state.sent_skill_names = set(activation.get("sent", ()))
        loop_state.activated_skill_names = set(activation.get("activated", ()))
        loop_state.invoked_skill_names = set(activation.get("invoked", ()))
        loop_state.invoked_skill_bodies = dict(activation.get("invoked_bodies", {}))
        # Slash invocation signal consumed once — clear to prevent re-seeding
        loop_state.slash_invoked_skill_name = None
        loop_state.slash_invoked_skill_body = None

    @staticmethod
    def _seed_mcp_state(loop_state: LoopState) -> dict[str, Any] | None:
        """Rehydrate MCP progressive disclosure state from LoopState for graph input.

        Returns ``None`` when no MCP state exists, so middleware ``abefore_agent``
        will lazy-init fresh fields.
        """
        has_data = (
            loop_state.sent_mcp_tool_names
            or loop_state.invoked_mcp_tools
            or loop_state.disabled_mcp_servers
            or loop_state.cached_mcp_resources
        )
        if not has_data:
            return None

        return {
            "sent_mcp_tool_names": set(loop_state.sent_mcp_tool_names),
            "invoked_mcp_tools": dict(loop_state.invoked_mcp_tools),
            "disabled_mcp_servers": set(loop_state.disabled_mcp_servers),
            "cached_mcp_resources": dict(loop_state.cached_mcp_resources),
        }

    @staticmethod
    def _snapshot_mcp_state(
        graph_output: dict[str, Any] | None,
        loop_state: LoopState,
    ) -> None:
        """Copy MCP progressive disclosure state from graph output back into LoopState.

        Best-effort: missing or malformed data is silently skipped.
        """
        if not graph_output:
            return
        sent = graph_output.get("sent_mcp_tool_names")
        invoked = graph_output.get("invoked_mcp_tools")
        disabled = graph_output.get("disabled_mcp_servers")
        cached = graph_output.get("cached_mcp_resources")
        if isinstance(sent, (set, list, tuple)):
            loop_state.sent_mcp_tool_names = set(sent)
        if isinstance(invoked, dict):
            loop_state.invoked_mcp_tools = dict(invoked)
        if isinstance(disabled, (set, list, tuple)):
            loop_state.disabled_mcp_servers = set(disabled)
        if isinstance(cached, dict):
            loop_state.cached_mcp_resources = dict(cached)

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

        Called after an execute wave completes.

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
        hit_tool_budget = any(r.hit_tool_budget for r in step_results)

        # Count errors
        error_count = sum(1 for r in step_results if not r.success)

        # Measure output length
        output_length = len(output) if output else 0

        # Update state
        state.last_wave_tool_call_count = total_tool_calls
        state.last_wave_subagent_task_count = total_subagent_tasks
        state.last_wave_hit_subagent_cap = hit_cap
        state.last_wave_hit_tool_budget = hit_tool_budget
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
            context_limit = self._config.agent.loop.context_window_limit
            state.context_percentage_consumed = min(1.0, state.total_tokens_used / context_limit)

    async def execute(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult | StepWaveQueued | StepWaveStart, None]:
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

        max_parallel_tools = self._max_parallel_tools_limit()

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
        if effective_execution_mode == "dependency" and decision.execution_mode != "dependency":
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

    def _max_parallel_tools_limit(self) -> int:
        """Configured concurrent tool-call cap for a single execute step stream."""
        if self._config is None:
            return 5
        return self._config.agent.loop.limits.max_parallel_tools

    def _wave_size(self, remaining: int) -> int:
        """Concurrent step count for the next execute batch (``0`` = unlimited).

        One batch does not exhaust ``execute``; callers loop until all ready steps are scheduled.
        """
        if remaining <= 0:
            return 0
        if self._max_parallel_steps <= 0:
            return remaining
        return min(self._max_parallel_steps, remaining)

    @staticmethod
    def _collect_wave_queued_steps(
        ready: list[StepAction],
        wave_size: int,
        queued_emitted: set[str],
    ) -> tuple[StepAction, ...]:
        """Return ready steps not in the current wave that have not been queued yet."""
        newly: list[StepAction] = []
        for step in ready[wave_size:]:
            if step.id in queued_emitted:
                continue
            queued_emitted.add(step.id)
            newly.append(step)
        return tuple(newly)

    async def _execute_parallel_waves(
        self,
        ready_steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult | StepWaveQueued | StepWaveStart, None]:
        """Run parallel mode in waves bounded by ``max_parallel_steps``."""
        idx = 0
        n = len(ready_steps)
        queued_emitted: set[str] = set()
        while idx < n:
            w = self._wave_size(n - idx)
            chunk = ready_steps[idx : idx + w]
            if idx == 0:
                queued = self._collect_wave_queued_steps(ready_steps, w, queued_emitted)
                if queued:
                    yield StepWaveQueued(steps=queued)
            idx += w
            yield StepWaveStart(steps=tuple(chunk))
            async for item in self._execute_parallel(chunk, state):
                yield item

    def _append_parallel_wave_ledger(
        self,
        state: LoopState,
        steps: list[StepAction],
        gather_results: list[Any],
    ) -> None:
        """Append RFC-214 Human/AI ledger pairs for each parallel step (IG-374).

        Execute waves record per-step ledger rows so subsequent ``plan-assess`` /
        ``plan-generate`` prompts built in ``PromptBuilder`` see prior step evidence.

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
        continue_loop_mode = bool(getattr(state, "continue_loop", False))
        n_steps = len(steps)
        live_queue: asyncio.Queue[_ParallelLiveQueueItem] = asyncio.Queue()
        gather_results: list[Any] = [None] * n_steps
        step_wave_index: dict[str, int] = {step.id: i for i, step in enumerate(steps)}

        async def _run_parallel_step(step: StepAction, *, first_in_wave: bool) -> None:
            sid = step.id
            try:
                # Per-step thread isolation; predecessor context flows via
                # message injection (no checkpoint fork — see RFC-223 revised).
                payload = await self._execute_step_collecting_events(
                    step,
                    logical_tid,
                    state.workspace,
                    routing_classification=getattr(state, "routing_classification", None),
                    git_status=state.git_status,
                    continue_loop_mode=continue_loop_mode,
                    loop_state=state,
                    live_event_queue=live_queue,
                    first_human_in_wave=first_in_wave,
                )
                live_queue.put_nowait(_ParallelStepDone(sid, payload))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                live_queue.put_nowait(_ParallelStepDone(sid, exc))

        tasks = [
            asyncio.create_task(_run_parallel_step(step, first_in_wave=(i == 0)))
            for i, step in enumerate(steps)
        ]

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
                            hit_tool_budget=False,
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

        # RFC-214: parallel waves must update the ledger so Plan-assess
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

    async def _execute_dependency(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult | StepWaveQueued | StepWaveStart, None]:
        """Execute steps respecting dependency DAG.

        Args:
            decision: AgentDecision with dependency information
            state: Loop state

        Yields:
            StreamEvent during execution, then StepResult.
        """
        local_done = set(state.dependency_completion_ids())
        failed_sticky: set[str] = set()
        queued_emitted: set[str] = set()

        while True:
            ready_all = decision.get_ready_steps(local_done)
            ready = [s for s in ready_all if s.id not in failed_sticky]
            if not ready:
                break
            w = self._wave_size(len(ready))
            chunk = ready[:w]
            queued = self._collect_wave_queued_steps(ready, w, queued_emitted)
            if queued:
                yield StepWaveQueued(steps=queued)
            yield StepWaveStart(steps=tuple(chunk))
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
        routing_classification: Any | None = None,
        git_status: dict[str, Any] | None = None,
        continue_loop_mode: bool = False,
        loop_state: LoopState | None = None,
        live_event_queue: asyncio.Queue[_ParallelLiveQueueItem] | None = None,
        first_human_in_wave: bool = True,
    ) -> tuple[list[StreamEvent], StepResult, list[BaseMessage], str]:
        """Execute single step, collecting events for the parallel merge queue.

        When ``live_event_queue`` is set (parallel execute), each stream chunk is pushed
        immediately for upstream TUI/WebSocket display. The returned event list is kept
        for tests and ledger helpers but is not re-yielded by ``_execute_parallel``.

        RFC-211: Collects outcome metadata instead of full output string.
        IG-355: Fourth tuple element is joined ``task`` tool delegate-final text for finalize.
        RFC-223: ThreadForkManager handles checkpoint fork for parallel isolation and
        predecessor inheritance. Multi-dep steps inject transitive predecessor ledger messages.

        Args:
            step: StepAction with description and optional hints
            thread_id: Logical thread ID for StepResult, logs, and durability lookups
            workspace: Thread-specific workspace path (RFC-103)
            routing_classification: Loop routing payload for middleware (IG-349, IG-383).
            git_status: Optional git snapshot for prompt XML (RFC-104).
            continue_loop_mode: True when this loop has prior goals (RFC-225);
                flows into LangGraph state so middleware injects loop-continuation guidance.
            loop_state: When set, ThreadForkManager creates isolated thread with inherited
                checkpoint history; multi-dep steps inject predecessor ledger messages.

        Returns:
            Tuple of ``(events, StepResult, AI messages for IG-199, delegate_final_text)``.
        """
        start = time.perf_counter()
        events: list[StreamEvent] = []
        output = ""  # Still collect for Layer 1 final report
        budget = _ActStreamBudget(
            max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave(),
            max_tool_calls_per_step=self._max_tool_calls_per_step(),
        )
        # Per-step ContextVar so parallel execute tasks each get a full tool budget.
        init_tool_concurrency_for_thread(self._max_parallel_tools_limit())

        try:
            wire_subagent = _wire_subagent_from_routing(routing_classification)

            logger.debug(
                "execute step: id=%s desc=%s hints: wire_subagent=%s",
                step.id,
                preview_first(step.description, 100),
                wire_subagent,
            )

            # RFC-223: Thread fork for checkpoint inheritance.
            # Use ThreadForkManager to prepare a forked thread with inherited
            # history from the predecessor. Sole-child optimization: when a
            # singleton-dependency step is the only child of its predecessor,
            # the manager reuses the predecessor's thread directly (no copy).
            fork_thread_id = thread_id  # Default to main thread
            direct_deps = step.dependencies or []
            is_multi_dep = len(direct_deps) > 1

            if loop_state is not None and loop_state.current_decision is not None:
                fork_manager = ThreadForkManager(self._checkpointer)
                fork_thread_id = await fork_manager.prepare_thread_for_step(
                    step=step,
                    decision=loop_state.current_decision,
                    state=loop_state,
                    main_thread_id=thread_id,
                )

            configurable: dict[str, Any] = {
                "thread_id": fork_thread_id,
                "soothe_step_subagent": wire_subagent,
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
            # when available on ``loop_state``; parallel branches
            # may still omit it here because middleware reads configurable elsewhere.
            config: dict[str, Any] = {"configurable": configurable}
            if self._config is not None:
                config = self._executor_langfuse_merge_for_stream(config, thread_id=fork_thread_id)

            # Build user message envelope with execution hints (RFC-214)
            from soothe.core.prompts.user_envelope import build_execute_step_envelope

            graph_input_messages: list[BaseMessage] = []

            # RFC-223: Multi-dep steps need message injection for all transitive predecessors
            # Singleton deps get full history via checkpoint fork (no injection needed)
            if is_multi_dep and loop_state is not None and loop_state.current_decision is not None:
                transitive_preds = transitive_dependency_step_ids(step, loop_state.current_decision)
                if transitive_preds:
                    cap = self._branch_predecessor_message_cap()
                    graph_input_messages = predecessor_execute_messages_for_branch(
                        loop_state.loop_messages,
                        transitive_preds,
                        max_messages=cap,
                    )
                    if graph_input_messages:
                        logger.info(
                            "[ThreadFork] step=%s multi-dep injected %d transitive predecessor msgs",
                            step.id,
                            len(graph_input_messages),
                        )

            # RFC-225: Loop-continuation bootstrap injection.
            # The bootstrap step (iter=0, no deps, continue_loop=True) forks from the
            # main loop thread, which has NO LangChain checkpoints (prior goal steps
            # ran on their own forked threads). The seeded LoopState.loop_messages
            # carries the prior goal's execute_step ledger; inject it so the agent
            # actually sees the prior conversation it needs to address.
            elif (
                not direct_deps
                and loop_state is not None
                and getattr(loop_state, "continue_loop", False)
                and loop_state.iteration == 0
                and loop_state.loop_messages
            ):
                cap = self._branch_predecessor_message_cap()
                graph_input_messages = prior_loop_execute_messages(
                    loop_state.loop_messages, max_messages=cap
                )
                if graph_input_messages:
                    logger.info(
                        "[LoopContinuation] step=%s bootstrap injected %d prior-goal execute msgs",
                        step.id,
                        len(graph_input_messages),
                    )

            hints_parts: list[str] = []
            if wire_subagent:
                hints_parts.append(f"Suggested subagent: {wire_subagent}")
            if step.expected_output:
                hints_parts.append(f"Expected output: {step.expected_output}")
            execution_hints = None
            if hints_parts:
                execution_hints = (
                    ". ".join(hints_parts) + ". Consider using the suggested approach first."
                )

            envelope = build_execute_step_envelope(
                step.description,
                execution_hints=execution_hints,
                skill_context=loop_state.skill_context if loop_state else None,
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
            skill_activation = self._seed_skill_activation(loop_state) if loop_state else None
            mcp_state = self._seed_mcp_state(loop_state) if loop_state else None
            stream = self._core_agent_astream_with_interrupt_resume(
                self._execute_graph_input(
                    graph_input_messages,
                    routing_classification=routing_classification,
                    workspace=workspace,
                    git_status=git_status,
                    continue_loop_mode=continue_loop_mode,
                    skill_activation=skill_activation,
                    mcp_state=mcp_state,
                ),
                config,
            )

            # Stream events and collect outcome metadata (RFC-211)
            tool_call_count = 0
            messages: list[BaseMessage] = []
            delegate_final = ""
            stream_outcomes: list[dict[str, Any]] = []
            has_tool_error = False  # IG-454: Track tool errors for StepResult.success
            async for (
                final_output,
                event,
                tc_count,
                msg_list,
                df,
                chunk_outcomes,
                stream_has_error,
            ) in self._stream_and_collect(
                stream,
                budget=budget,
                step_id=step.id,
                step_description=step.description,
                step_subagent=wire_subagent,
            ):
                if event is not None:
                    _append_parallel_stream_event(events, event, live_event_queue)
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count
                    messages = msg_list
                    delegate_final = df
                    stream_outcomes = chunk_outcomes
                    has_tool_error = stream_has_error

            duration_ms = int((time.perf_counter() - start) * 1000)

            # RFC-105: Snapshot skill_activation from graph state back into LoopState
            if loop_state is not None:
                try:
                    graph_state = await self.core_agent.graph.aget_state(
                        config={"configurable": {"thread_id": fork_thread_id}},
                    )
                    if graph_state and graph_state.values:
                        self._snapshot_skill_activation(graph_state.values, loop_state)
                        self._snapshot_mcp_state(graph_state.values, loop_state)
                except Exception:  # noqa: BLE001
                    logger.debug("[Skill] Failed to snapshot skill_activation from graph state")

                # Clear skill_context after first execute wave — body now lives in
                # system prompt <SKILL_CONTEXT> via progressive loading (RFC-105).
                if loop_state.skill_context:
                    loop_state.skill_context = None

            # Note: tool_call_ids are now in unified format within messages chunks
            # No separate binding events needed (IG-416 simplified design)

            primary_outcome = self._build_step_outcome_from_stream(
                outcomes=stream_outcomes,
                output=output,
                hit_tool_budget=budget.hit_tool_budget,
                step_id=step.id,
            )

            # IG-148: Add CoreAgent input/output evidence
            primary_outcome["step_input"] = envelope  # HumanMessage content sent to Layer 1
            primary_outcome["output_summary"] = create_output_summary(output)  # Truncated findings

            # IG-454: Determine step success based on tool errors
            step_success = not has_tool_error
            step_error = _first_tool_error_message(stream_outcomes) if has_tool_error else None

            if step_success:
                logger.info(
                    "Step %s completed successfully in %dms (tool_calls: %d, subagent_cap_hit=%s, tool_budget_hit=%s)",
                    step.id,
                    duration_ms,
                    tool_call_count,
                    budget.hit_subagent_cap,
                    budget.hit_tool_budget,
                )
            else:
                # Include error info in outcome for planner visibility
                primary_outcome["has_tool_error"] = True
                logger.warning(
                    "Step %s completed with tool errors in %dms (tool_calls: %d)",
                    step.id,
                    duration_ms,
                    tool_call_count,
                )

            return (
                events,
                StepResult(
                    step_id=step.id,
                    success=step_success,
                    outcome=primary_outcome,  # RFC-211: outcome metadata
                    error=step_error,
                    duration_ms=duration_ms,
                    thread_id=thread_id,
                    tool_call_count=tool_call_count,
                    subagent_task_completions=budget.subagent_task_completions,
                    hit_subagent_cap=budget.hit_subagent_cap,
                    hit_tool_budget=budget.hit_tool_budget,
                ),
                messages,
                delegate_final,
            )

        except asyncio.CancelledError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "Step %s cancelled after %dms [wire_subagent=%s]",
                step.id,
                duration_ms,
                wire_subagent,
            )
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if _is_recoverable_tool_network_error(e):
                logger.warning(
                    "Step %s failed after %dms [wire_subagent=%s]: %s",
                    step.id,
                    duration_ms,
                    wire_subagent,
                    _format_tool_network_error(e),
                )
            else:
                logger.exception(
                    "Step %s failed after %dms [wire_subagent=%s]",
                    step.id,
                    duration_ms,
                    wire_subagent,
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
                    hit_tool_budget=False,
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
        step_description: str = "",
        step_subagent: str | None = None,
    ) -> AsyncGenerator[
        tuple[
            str | None, StreamEvent | None, int, list[BaseMessage], str, list[dict[str, Any]], bool
        ],
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
        IG-454: Tracks ToolMessage.status="error" to mark step failures.

        Args:
            stream: Async iterator from agent.astream()
            budget: Optional Act wave budget (subagent ``task`` cap, IG-130).
            step_id: When set, rewrite root-graph tool_call_ids to unified format
                ``{step_id}:s:{tool_fragment}`` for consistent TUI rendering.
            step_description: Execute-step brief copied onto ``task`` kwargs when the
                model streams empty delegation args (parallel execute).
            step_subagent: Optional planner subagent hint for ``subagent_type``.

        Yields:
            Tuple of ``(output, event, tool_call_count, messages, delegate_final_text, outcomes, has_error)``:
            - When event is not None: immediate display chunk (outcomes empty, has_error False).
            - At end: combined_output, ``tool_call_count`` (root graph plus namespaced
              subgraph ``ToolMessage`` totals), root AIMessages list, joined ``task``
              tool bodies (ordered, capped), RFC-211 outcome metadata per tool, and
              ``has_error`` flag True if any ToolMessage had status="error".
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
        tool_args = ToolCallArgsCollector()

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
            stream_ns: tuple[str, ...] = ()

            # Handle tuple format (namespace, mode, data) - canonical format
            if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                _ns_chunk, mode_chunk, data_chunk = chunk
                stream_ns = _ns_chunk if _ns_chunk else ()
                # IG-416: Unify message tool_call_ids for client row/result matching.
                emit_chunk = chunk
                tool_update_events: list[dict[str, Any]] = []
                if (
                    step_id
                    and mode_chunk == "messages"
                    and isinstance(data_chunk, (list, tuple))
                    and len(data_chunk) >= 2
                ):
                    msg0 = data_chunk[0]
                    task_idx = 0 if _ns_chunk else None
                    if isinstance(msg0, (AIMessage, AIMessageChunk)):
                        filled_msg = _backfill_tool_calls_args_from_chunks(msg0)
                        rewritten_msg = _rewrite_tool_call_ids_to_unified(
                            filled_msg, step_id, task_idx=task_idx
                        )
                        tool_args.record_ai_pair(
                            filled_msg,
                            rewritten_msg,
                            step_id=step_id,
                            task_idx=task_idx,
                        )
                        enriched_msg = _enrich_execute_step_task_kwargs_on_message(
                            rewritten_msg,
                            step_description=step_description,
                            step_subagent=step_subagent,
                            task_idx=task_idx,
                        )
                        wire_msg = _stringify_tool_call_chunk_args_on_message(enriched_msg)
                        if wire_msg is not msg0:
                            emit_chunk = (_ns_chunk, mode_chunk, (wire_msg, data_chunk[1]))
                        tool_update_events = filter_redundant_stream_tool_updates(
                            wire_updates_from_ai_message(enriched_msg)
                        )
                    elif isinstance(msg0, ToolMessage):
                        modified_msg, tool_update_events = tool_args.promote_tool_message(
                            msg0,
                            step_id=step_id,
                            task_idx=task_idx,
                        )
                        if modified_msg is not msg0:
                            emit_chunk = (_ns_chunk, mode_chunk, (modified_msg, data_chunk[1]))
                yield None, emit_chunk, 0, [], "", [], False
                for tool_ev in tool_update_events:
                    yield None, (_ns_chunk, "custom", tool_ev), 0, [], "", [], False
                chunk = emit_chunk

            stop_act_stream = False
            for msg in iter_messages_for_act_aggregation(chunk):
                if isinstance(msg, ToolMessage):
                    tool_call_count += 1
                    tool_call_id = msg.tool_call_id
                    tool_name = msg.name or "unknown"

                    content = msg.content
                    msg_status = getattr(msg, "status", None)

                    if _maybe_cap_subagent_tasks(msg):
                        stop_act_stream = True
                        break
                    text_out = extract_text_from_message_content(content)
                    if text_out:
                        # Truncate large tool outputs in aggregated stream text; full payloads
                        # remain in CoreAgent graph state (and LangGraph eviction when enabled).
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

                    tool_meta_cfg = None
                    if self._config and hasattr(self._config, "optimization"):
                        tool_meta_cfg = self._config.optimization.tool_result_registry
                    outcome = generate_outcome_metadata(
                        tool_name,
                        content,
                        tool_call_id,
                        registry_config=tool_meta_cfg,
                        tool_status=msg_status,
                    )

                    outcomes.append(outcome)

                    if outcome.get("has_error"):
                        logger.warning(
                            "[Tool#%d] %s returned error: %s",
                            tool_call_count,
                            tool_name,
                            log_preview(str(outcome.get("error_preview", content))[:100], 80),
                        )

                    if tool_name == "task" and text_out.strip():
                        tc_id = tool_call_id or ""
                        if not (tc_id and tc_id in delegate_task_ids_seen):
                            if tc_id:
                                delegate_task_ids_seen.add(tc_id)
                            clipped = text_out.strip()
                            if len(clipped) > _DELEGATE_FINAL_PER_TASK_CAP:
                                clipped = clipped[:_DELEGATE_FINAL_PER_TASK_CAP]
                            delegate_task_final_parts.append(clipped)

                    logged_args = tool_args.lookup(tool_call_id or "")
                    logger.debug(
                        "[Tool#%d] %s(%s) args=%s → %s, %dB",
                        tool_call_count,
                        tool_name,
                        tool_call_id,
                        format_args_for_log(logged_args),
                        outcome.get("type", "unknown"),
                        outcome.get("size_bytes", 0),
                    )

                    if budget is not None and budget.max_tool_calls_per_step > 0:
                        budget.tool_call_count = tool_call_count
                        if tool_call_count >= budget.max_tool_calls_per_step:
                            budget.hit_tool_budget = True
                            logger.warning(
                                "Tool budget reached (count=%d, max=%d), stopping Act stream with partial results",
                                tool_call_count,
                                budget.max_tool_calls_per_step,
                            )
                            stop_act_stream = True
                            break
                elif isinstance(msg, AIMessageChunk):
                    if not step_id:
                        tool_args.record_ai_pair(
                            msg,
                            msg,
                            step_id="",
                            task_idx=0 if stream_ns else None,
                        )
                    messages.append(msg)  # Collect chunks for assistant text extraction
                    t = extract_text_from_message_content(msg.content)
                    if t:
                        chunks.append(t)
                elif isinstance(msg, AIMessage):
                    if not step_id:
                        tool_args.record_ai_pair(
                            msg,
                            msg,
                            step_id="",
                            task_idx=0 if stream_ns else None,
                        )
                    messages.append(msg)
                    t = extract_text_from_message_content(msg.content)
                    if t:
                        chunks.append(t)
                        logger.debug("[AI Message] %s", log_preview(t, chars=150))

            subgraph_tool_updates: list[tuple[tuple[str, ...], dict[str, Any]]] = []
            for ns_tuple, tm in iter_namespaced_tool_messages(chunk):
                subgraph_tool_call_count += 1
                body_preview = log_preview(
                    extract_text_from_message_content(getattr(tm, "content", "")),
                    chars=160,
                )
                tcid = str(getattr(tm, "tool_call_id", "") or "").strip()
                tname = str(getattr(tm, "name", "") or "unknown").strip() or "unknown"
                logger.info(
                    "[SubagentTool] ns=%s name=%s id=%s preview=%s",
                    "/".join(ns_tuple) if ns_tuple else "()",
                    tname,
                    tcid,
                    body_preview,
                )
                if tcid and tname != "task":
                    tool_ev = tool_args.subgraph_placeholder_update(tcid, tname)
                    if tool_ev is not None:
                        subgraph_tool_updates.append((ns_tuple, tool_ev))
            for ns_tuple, tool_ev in subgraph_tool_updates:
                yield None, (ns_tuple, "custom", tool_ev), 0, [], "", [], False

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
        has_tool_error = any(o.get("has_error") for o in outcomes)
        # Final yield with combined output and tool call count
        # IG-416: No longer return tool_call_ids set - IDs are now in unified format in messages
        # IG-454: Include has_tool_error flag for StepResult.success detection
        yield (
            join_text_fragments(chunks),
            None,
            total_tool_calls,
            messages,
            delegate_final_text,
            outcomes,
            has_tool_error,
        )

    async def _build_batch_human_messages(
        self,
        steps: list,
        state: LoopState,
    ) -> list[LoopHumanMessage]:
        """Build N LoopHumanMessage inputs for batch execution (RFC-214).

        Each step gets its own LoopHumanMessage with the user message envelope:
        <USER_QUERY>, then ``--- Context ---`` and <DYNAMIC_CONTEXT>
        (execution hints, timestamp, and related context).

        Args:
            steps: Steps to execute in this wave
            state: Current loop state with iteration/thread context

        Returns:
            List of LoopHumanMessage instances (one per step)
        """
        from soothe.core.prompts.user_envelope import build_execute_step_envelope

        wire_subagent = _wire_subagent_from_routing(getattr(state, "routing_classification", None))
        messages = []
        for step_index, step in enumerate(steps):
            # Build execution hints from step metadata (RFC-214: hints in user envelope)
            hints_parts: list[str] = []
            if wire_subagent:
                hints_parts.append(f"Suggested subagent: {wire_subagent}")
            if step.expected_output:
                hints_parts.append(f"Expected output: {step.expected_output}")
            execution_hints = None
            if hints_parts:
                execution_hints = (
                    ". ".join(hints_parts) + ". Consider using the suggested approach first."
                )

            envelope = build_execute_step_envelope(
                step.description,
                execution_hints=execution_hints,
                skill_context=state.skill_context,
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
            final_ai_msg: AIMessage chosen for this step's ledger entry.
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

        if _is_recoverable_tool_network_error(exc):
            return _format_tool_network_error(exc)

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
