"""Cognition intention module for LLM-driven query classification.

IG-226: Quiz-only classification — the LLM decides quiz vs agentic.
The continue_thread vs new_goal distinction is resolved structurally
by the runner based on loop state (not by the classifier).

Three-tier runtime classification (resolved after LLM + structural rule):
- quiz: Direct minimal reply (greetings, thanks, trivia) without tools
- continue_thread: Same-loop follow-up (prior goals exist)
- new_goal: Fresh loop or first query in a new loop

This module provides:
- IntentClassification: Primary intent classification model
- IntentClassifier: LLM-driven quiz detector
- RoutingClassification: Routing complexity classification for execution path selection
- IntentHint: Enum for suggested intent to bypass LLM classification

Related RFCs: RFC-201, RFC-217, RFC-200, RFC-0016
"""

from __future__ import annotations

from .classifier import IntentClassifier
from .models import (
    IntentClassification,
    IntentHint,
    RoutingClassification,
    TaskComplexity,
    build_loop_routing_classification,
)

__all__ = [
    "IntentClassifier",
    "IntentClassification",
    "IntentHint",
    "RoutingClassification",
    "TaskComplexity",
    "build_loop_routing_classification",
]
