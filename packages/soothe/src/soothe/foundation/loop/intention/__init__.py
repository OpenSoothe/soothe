"""Intent classification module (RFC-225).

The LLM decides ``quiz`` vs ``agentic``. Loop continuation is derived
structurally inside ``StrangeLoop`` from the loaded checkpoint and is
not a classifier concern.

This module provides:
- IntentClassification: two-value intent classification model
- IntentClassifier: LLM-driven quiz detector
- RoutingClassification: routing complexity classification for execution path selection
- IntentHint: enum for suggested intent to bypass LLM classification (``QUIZ`` only)
- build_quiz_system_message: system prompt for quiz fast-path LLM calls

Related RFCs: RFC-201, RFC-217, RFC-225
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
from .quiz_messages import build_quiz_system_message

__all__ = [
    "IntentClassifier",
    "IntentClassification",
    "IntentHint",
    "RoutingClassification",
    "TaskComplexity",
    "build_loop_routing_classification",
    "build_quiz_system_message",
]
