"""Autopilot service package (RFC-222).

This package provides the AutopilotService for Layer 3 autonomous
orchestration with loop pool management and scheduling. Service
configuration is supplied via ``soothe.config.AutonomousConfig`` (RFC-222
fields live in the unified autonomous block per IG-434).

Architecture:
- service.py: AutopilotService - scheduling, lifecycle, webhooks
- loop_pool.py: LoopPool, LoopHandle - worker management models
"""

from __future__ import annotations

from .loop_pool import LoopHandle, LoopPool
from .service import AutopilotService

__all__ = [
    "AutopilotService",
    "LoopHandle",
    "LoopPool",
]
