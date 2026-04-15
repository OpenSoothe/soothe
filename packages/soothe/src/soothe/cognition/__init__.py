"""Cognitive layer for goal management.

This module provides the cognitive capabilities for Soothe:
- GoalEngine: Priority-based goal lifecycle management
"""

from soothe.cognition.goal_engine import Goal, GoalEngine, Proposal, ProposalQueue

__all__ = [
    "Goal",
    "GoalEngine",
    "Proposal",
    "ProposalQueue",
]
