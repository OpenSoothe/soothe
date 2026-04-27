"""Cognition intention module for LLM-driven query classification.

IG-226: Unified intent classification system with three-tier classification:
- chitchat: Direct response (no goal)
- thread_continuation: Reuse current thread/goal
- new_goal: Create goal via GoalEngine

This module provides:
- IntentClassification: Primary intent classification model
- IntentClassifier: LLM-driven classifier with conversation context
- RoutingClassification: Routing complexity classification for execution path selection

Architecture:
- Pure LLM-driven classification (no keyword heuristics)
- Conversation context awareness (last 8 messages)
- Active goal context for thread continuation
- Robust fallbacks to safe defaults
- Single structured LLM call (~2-4s latency)

Related RFCs: RFC-201, RFC-609, RFC-200, RFC-0016
"""

from __future__ import annotations

from .classifier import IntentClassifier
from .models import IntentClassification, RoutingClassification

__all__ = [
    "IntentClassifier",
    "IntentClassification",
    "RoutingClassification",
]
