"""Execution scheduling package - concurrency control and step scheduling.

This package provides:
- Hierarchical concurrency control for goal/step/global limits
- DAG-based step scheduling for parallel execution
- LRU-style tool caching for performance

Architecture:
- concurrency.py: Hierarchical semaphore-based concurrency control (RFC-0009)
- step_scheduler.py: DAG-based plan step scheduler
- tool_cache.py: In-process tool group caching

Usage:
    from soothe.core.scheduling import (
        ConcurrencyController,
        StepScheduler,
        get_cached_tools,
        cache_tools,
    )

RFC-0009: DAG-based step execution with parallel execution
"""

from __future__ import annotations

# Concurrency control
from .concurrency import ConcurrencyController

# Step scheduling
from .step_scheduler import StepScheduler

# Tool caching
from .tool_cache import (
    cache_tools,
    clear_tool_cache,
    get_cache_stats,
    get_cached_tools,
)

__all__ = [
    # Concurrency
    "ConcurrencyController",
    # Step scheduling
    "StepScheduler",
    # Tool caching
    "get_cached_tools",
    "cache_tools",
    "clear_tool_cache",
    "get_cache_stats",
]
