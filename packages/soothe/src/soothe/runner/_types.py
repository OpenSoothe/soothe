"""Shared types and utilities for SootheRunner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def generate_thread_id() -> str:
    """Generate a UUID7 thread ID for time-ordered identifiers.

    Uses uuid7 for consistent ID format across loop_id and thread_id.
    """
    from uuid_utils import uuid7

    return str(uuid7())


@dataclass
class RunnerState:
    """Runner state for protocol pre/post-processing (IG-226: added intent_classification).

    Attributes:
        thread_id: Thread context for execution (Layer 1 CoreAgent)
        loop_id: Loop context for goal execution (Layer 2 StrangeLoop, RFC-216)
        workspace: Thread-specific workspace path (RFC-103)
        recalled_memories: Memory items recalled for this query
        recalled_memory_count: Number of memories recalled
        intent_classification: IG-226 Intent classification with goal handling strategy
        protocol_summary: Protocol backend summary for system prompt
        thread_context: Thread metadata for system prompt
        workspace_size_bytes: Workspace size in bytes (RFC-104)
        workspace_file_count: Workspace file count (RFC-104)
        plan: Current plan from planner
        stream_error: Error message if stream failed
        prior_messages: Prior conversation excerpts for subagent context
        langgraph_thread_id: LangGraph thread ID override
    """

    """Mutable state accumulated during a single query execution."""

    thread_id: str = ""
    loop_id: str | None = None  # StrangeLoop identifier for Layer 2 operations (RFC-216)
    langgraph_thread_id: str | None = None  # LangGraph id when parallel goals/steps need isolation
    workspace: str | None = None  # Thread-specific workspace (RFC-103)
    full_response: list[str] = field(default_factory=list)
    plan: Any = None  # Type: Plan | None
    context_projection: Any = None
    recalled_memories: list[Any] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)
    stream_error: str | None = None
    intent_classification: Any = (
        None  # IG-226: Type: IntentClassification with goal handling strategy
    )
    # Context for system prompt XML injection (RFC-104)
    thread_context: dict[str, Any] = field(default_factory=dict)
    protocol_summary: dict[str, Any] = field(default_factory=dict)
    # Thread context for subagents (IG-140)
    prior_messages: str | None = None
