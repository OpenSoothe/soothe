"""Cognitive layer for intention classification and goal management.

This module provides the cognitive capabilities for Soothe:
- UnifiedClassifier: Two-tier LLM-based intention classification
- GoalEngine: Priority-based goal lifecycle management
"""

from soothe.cognition.goal_engine import Goal, GoalEngine
from soothe.cognition.unified_classifier import (
    EnrichmentResult,
    RoutingResult,
    UnifiedClassification,
    UnifiedClassifier,
    _looks_chinese,
)

__all__ = [
    "EnrichmentResult",
    "Goal",
    "GoalEngine",
    "RoutingResult",
    "UnifiedClassification",
    "UnifiedClassifier",
    "_looks_chinese",
]
