"""Dataclasses and types for execute wave management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage

from soothe.config.constants import DEFAULT_MAX_TOOL_CALLS_PER_STEP
from soothe.sloop.state.schemas import StepAction, StepExecutionRecord

# ``task`` tool return text cap per invocation before joining (delegate finals).
_DELEGATE_FINAL_PER_TASK_CAP = 80_000

_TUPLE_LEN = 3

# Type for stream events yielded during execution
StreamEvent = tuple[tuple[str, ...], str, Any]  # (namespace, mode, data)


@dataclass
class _ExecuteStepResult:
    """Collected result from execute-step stream.

    Used instead of raw tuple for clarity and extensibility.
    """

    events: list[Any] = field(default_factory=list)
    step_result: StepExecutionRecord | None = None
    messages: list[BaseMessage] = field(default_factory=list)
    delegate_final: str = ""
    output: str = ""  # Accumulated text chunks for ledger fallback
    human_core_agent_message_id: str | None = None
    ai_core_agent_message_id: str | None = None
    # True when a clarification (tool_approval / ask_user) interrupt paused the
    # step mid-stream. Step-completion LLM calls (deliverable assess, close
    # report, cognition summary) are skipped because the step resumes after the
    # user answers — any summary now is stale and wasted cost.
    paused_by_clarification: bool = False

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = []
        if self.messages is None:
            self.messages = []


@dataclass
class _ActStreamBudget:
    """Mutable counters for a single CoreAgent stream."""

    max_subagent_tasks_per_wave: int = 0
    max_tool_calls_per_step: int = DEFAULT_MAX_TOOL_CALLS_PER_STEP
    subagent_task_completions: int = 0
    tool_call_count: int = 0
    hit_subagent_cap: bool = False
    hit_tool_budget: bool = False


@dataclass(frozen=True, slots=True)
class _StreamCollectChunk:
    """One yield from `Executor._stream_and_collect` (extension).

    Two modes:
    - Wire event: `event` set, other summary fields at defaults.
    - Final summary: `output` set with accumulated act-stream results.
    """

    output: str | None = None
    event: StreamEvent | None = None
    main_tool_count: int = 0
    messages: tuple[BaseMessage, ...] = ()
    delegate_final: str = ""
    outcomes: tuple[dict[str, Any], ...] = ()
    has_error: bool = False
    subgraph_tool_count: int = 0
    execution_metrics: dict[str, int] = field(default_factory=dict)

    @classmethod
    def wire_event(cls, event: StreamEvent) -> _StreamCollectChunk:
        """Immediate display chunk for TUI / parallel live-event fan-out."""
        return cls(event=event)

    @classmethod
    def finalized(
        cls,
        *,
        output: str,
        main_tool_count: int,
        messages: list[BaseMessage],
        delegate_final: str,
        outcomes: list[dict[str, Any]],
        has_error: bool,
        subgraph_tool_count: int,
        execution_metrics: dict[str, int] | None = None,
    ) -> _StreamCollectChunk:
        """Terminal aggregate after the act stream completes."""
        return cls(
            output=output,
            main_tool_count=main_tool_count,
            messages=tuple(messages),
            delegate_final=delegate_final,
            outcomes=tuple(outcomes),
            has_error=has_error,
            subgraph_tool_count=subgraph_tool_count,
            execution_metrics=dict(execution_metrics or {}),
        )


@dataclass(frozen=True, slots=True)
class _PendingInterruptFetch:
    """Result of reading LangGraph interrupts after an execute stream ends."""

    pending_interrupts: dict[str, Any] = field(default_factory=dict)
    interrupt_occurred: bool = False
    captured_clarification: bool = False
    # Structured ask_user present but detector rejected it (empty questions, etc.).
    uncapturable_ask_user: bool = False


@dataclass(frozen=True, slots=True)
class StepWaveQueued:
    """Ready steps waiting for a later execute batch (`max_parallel_steps` cap)."""

    steps: tuple[StepAction, ...]


@dataclass(frozen=True, slots=True)
class StepCompletionReport:
    """Display-only step completion summary for TUI cognition cards (no ledger write)."""

    step_id: str
    summary: str
    iteration: int = 0


@dataclass(frozen=True, slots=True)
class StepWaveStart:
    """Marks the start of a bounded execute batch (`max_parallel_steps` cap).

    Emitted before a wave runs so UIs can show only actively executing steps as
    `running`; overflow ready steps are announced via :class:`StepWaveQueued`.
    """

    steps: tuple[StepAction, ...]


@dataclass(slots=True)
class _ParallelStepDone:
    """Sentinel placed on the parallel live-event queue when one step finishes."""

    step_id: str
    payload: _ExecuteStepResult | BaseException


def all_tool_outcomes_failed(outcomes: list[dict[str, Any]]) -> bool:
    """Return True when no tool outcome succeeded.

    An empty outcome list means the step produced zero tool calls — the model
    either failed before emitting any tool call or produced only text. In both
    cases nothing succeeded, so this returns ``True``. This prevents a
    model-failure (e.g. blocked API key → ``RuntimeError("all models in pool
    failed")``) from being swallowed as a successful empty step that the DAG
    re-dispatches indefinitely.
    """
    if not outcomes:
        return True
    return all(bool(o.get("has_error")) for o in outcomes)


def _first_tool_error_message(outcomes: list[dict[str, Any]]) -> str:
    """Return the first tool error preview from outcome metadata."""
    for outcome in outcomes:
        if outcome.get("has_error"):
            preview = outcome.get("error_preview")
            if preview:
                return str(preview)[:200]
            tool_name = outcome.get("tool_name") or "tool"
            return f"{tool_name} failed"
    return "Tool execution error"


_ParallelLiveQueueItem = StreamEvent | _ParallelStepDone


def _append_parallel_stream_event(
    events: list[StreamEvent],
    event: StreamEvent,
    live_event_queue: asyncio.Queue[_ParallelLiveQueueItem] | None,
) -> None:
    """Fan out a stream chunk to the live TUI queue or retain it on the step result.

    Production parallel execute always sets `live_event_queue`; the returned
    `_ExecuteStepResult.events` list is not re-yielded in that path. Retain
    events only when no live queue is configured (unit tests, direct callers).
    """
    if live_event_queue is not None:
        live_event_queue.put_nowait(event)
    else:
        events.append(event)


def wave_gather_slot(gather_results: list[Any], index: int) -> Any:
    """Return one parallel-wave result slot, or `None` when missing."""
    if index >= len(gather_results):
        return None
    return gather_results[index]


def wave_gather_failed(raw: Any) -> bool:
    """True when a parallel wave slot has no usable :class:`_ExecuteStepResult`."""
    return raw is None or isinstance(raw, BaseException)


__all__ = [
    "_ActStreamBudget",
    "_DELEGATE_FINAL_PER_TASK_CAP",
    "_ExecuteStepResult",
    "_StreamCollectChunk",
    "_first_tool_error_message",
    "all_tool_outcomes_failed",
    "_PendingInterruptFetch",
    "_ParallelStepDone",
    "_ParallelLiveQueueItem",
    "_TUPLE_LEN",
    "StreamEvent",
    "StepCompletionReport",
    "StepWaveQueued",
    "StepWaveStart",
    "_append_parallel_stream_event",
    "wave_gather_failed",
    "wave_gather_slot",
]
