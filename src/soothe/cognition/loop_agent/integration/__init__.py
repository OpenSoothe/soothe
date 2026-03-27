"""Integration layer for cross-layer communication.

This module handles Layer 2's communication with other layers:
- tool_loop_adapter: DeepAgents (Layer 1) integration
- goal_adapter: GoalManager (Layer 3) delegation
- context_borrower: Summary injection for Layer 1
"""

__all__ = [
    "ContextBorrower",
    "GoalAdapter",
    "ToolLoopAdapter",
]
