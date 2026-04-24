"""Middleware utility functions."""

from __future__ import annotations

from typing import Any


def create_llm_call_metadata(
    purpose: str,
    component: str,
    phase: str = "unknown",
    **extra: Any,
) -> dict[str, Any]:
    """Create standardized metadata for LLM calls.

    This metadata is used by LLMTracingMiddleware to enrich trace logs
    with call context (purpose, component, phase). All LLM invocation
    sites should use this helper to ensure consistent tracing.

    Args:
        purpose: Call purpose (reason, plan, classify, reflect, consensus_vote, etc.)
        component: Component making the call (planner.simple, classifier.unified, etc.)
        phase: Execution phase (layer1, layer2, pre-stream, post-loop, etc.)
        **extra: Additional metadata fields

    Returns:
        Metadata dict for config["metadata"]

    Example:
        >>> response = await model.ainvoke(
        ...     messages,
        ...     config={
        ...         "metadata": create_llm_call_metadata(
        ...             purpose="classify",
        ...             component="classifier.unified",
        ...             phase="pre-stream",
        ...         )
        ...     },
        ... )
    """
    metadata = {
        "soothe_call_purpose": purpose,
        "soothe_call_component": component,
        "soothe_call_phase": phase,
    }
    metadata.update(extra)
    return metadata
