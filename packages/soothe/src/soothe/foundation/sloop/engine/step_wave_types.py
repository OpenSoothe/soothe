"""Dataclasses and types for execute wave management (IG-493, IG-130, IG-356).

This module provides the data structures used during parallel and dependency
execute step processing: result containers, budget tracking, wave markers,
and stream event types.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage

from soothe.config.constants import DEFAULT_MAX_TOOL_CALLS_PER_STEP
from soothe.foundation.sloop.state.schemas import StepAction, StepResult

# Re-export for executor tests and legacy imports.
_DEFAULT_MAX_TOOL_CALLS_PER_STEP = DEFAULT_MAX_TOOL_CALLS_PER_STEP

# ``task`` tool return text cap per invocation before joining (delegate finals).
_DELEGATE_FINAL_PER_TASK_CAP = 80_000

_TUPLE_LEN = 3

# Type for stream events yielded during execution
StreamEvent = tuple[tuple[str, ...], str, Any]  # (namespace, mode, data)


@dataclass
class _ExecuteStepResult:
    """Collected result from execute-step stream (IG-493).

    Used instead of raw tuple for clarity and extensibility.
    """

    events: list[Any] = field(default_factory=list)
    step_result: StepResult | None = None
    messages: list[BaseMessage] = field(default_factory=list)
    delegate_final: str = ""
    output: str = ""  # Accumulated text chunks for ledger fallback
    human_core_agent_message_id: str | None = None
    ai_core_agent_message_id: str | None = None

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = []
        if self.messages is None:
            self.messages = []


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
class _StreamCollectChunk:
    """One yield from ``Executor._stream_and_collect`` (IG-493 extension).

    Two modes:
    - Wire event: ``event`` set, other summary fields at defaults.
    - Final summary: ``output`` set with accumulated act-stream results.
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


@dataclass(frozen=True, slots=True)
class StepWaveQueued:
    """Ready steps waiting for a later execute batch (``max_parallel_steps`` cap)."""

    steps: tuple[StepAction, ...]


@dataclass(frozen=True, slots=True)
class StepCompletionReport:
    """Display-only step completion summary for TUI cognition cards (no ledger write)."""

    step_id: str
    summary: str
    iteration: int = 0


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
    payload: _ExecuteStepResult | BaseException


def all_tool_outcomes_failed(outcomes: list[dict[str, Any]]) -> bool:
    """Return True when every recorded tool outcome in a step reported an error."""
    if not outcomes:
        return False
    return all(bool(o.get("has_error")) for o in outcomes)


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


_ParallelLiveQueueItem = StreamEvent | _ParallelStepDone


def _append_parallel_stream_event(
    events: list[StreamEvent],
    event: StreamEvent,
    live_event_queue: asyncio.Queue[_ParallelLiveQueueItem] | None,
) -> None:
    """Fan out a stream chunk to the live TUI queue or retain it on the step result.

    Production parallel execute always sets ``live_event_queue``; the returned
    ``_ExecuteStepResult.events`` list is not re-yielded in that path. Retain
    events only when no live queue is configured (unit tests, direct callers).
    """
    if live_event_queue is not None:
        live_event_queue.put_nowait(event)
    else:
        events.append(event)


def max_tool_calls_for_step(
    step: StepAction,
    wire_subagent: str | None,
    *,
    default: int = _DEFAULT_MAX_TOOL_CALLS_PER_STEP,
) -> int:
    """Return per-step tool budget."""
    _ = step
    _ = wire_subagent
    return default


def wave_gather_slot(gather_results: list[Any], index: int) -> Any:
    """Return one parallel-wave result slot, or ``None`` when missing."""
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
    "_DEFAULT_MAX_TOOL_CALLS_PER_STEP",
    "_PendingInterruptFetch",
    "_ParallelStepDone",
    "_ParallelLiveQueueItem",
    "_TUPLE_LEN",
    "StreamEvent",
    "StepCompletionReport",
    "StepWaveQueued",
    "StepWaveStart",
    "_append_parallel_stream_event",
    "max_tool_calls_for_step",
    "wave_gather_failed",
    "wave_gather_slot",
]
