"""Cognitive layer for intention classification and goal management.

This module provides the cognitive capabilities for Soothe:
- UnifiedClassifier: Two-tier LLM-based intention classification
- GoalEngine: Priority-based goal lifecycle management
"""

from soothe.cognition.goal_engine import Goal, GoalEngine
from soothe.cognition.unified_classifier import (
    RoutingResult,
    UnifiedClassification,
    UnifiedClassifier,
    _looks_chinese,
)

__all__ = [
    "Goal",
    "GoalEngine",
    "RoutingResult",
    "UnifiedClassification",
    "UnifiedClassifier",
    "_looks_chinese",
]
