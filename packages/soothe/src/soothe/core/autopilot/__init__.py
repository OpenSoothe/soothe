"""Autopilot service package (RFC-222).

This package provides the AutopilotService for Layer 3 autonomous
orchestration with loop pool management and scheduling.

Architecture:
- service.py: AutopilotService - scheduling, lifecycle, webhooks
- loop_pool.py: LoopPool, LoopHandle - worker management models
- scheduling.py: SchedulingLoop - goal → loop assignment logic
"""

from __future__ import annotations

from .loop_pool import LoopHandle, LoopPool
from .service import AutopilotConfig, AutopilotService

__all__ = [
    "AutopilotConfig",
    "AutopilotService",
    "LoopHandle",
    "LoopPool",
]
