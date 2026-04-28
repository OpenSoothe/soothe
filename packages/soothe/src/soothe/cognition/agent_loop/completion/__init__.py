"""Goal completion module for AgentLoop (RFC-615, IG-297).

This module encapsulates all logic for producing user-visible goal completion responses,
extracting the complex decision tree from AgentLoop orchestration into a modular, testable design.

Separation of concerns:
- GoalCompletionModule: Orchestration (strategy selection, flow control)
- ResponseCategorizer: Classification (length, goal type)
- SynthesisExecutor: Execution (LLM synthesis, streaming)
- CompletionStrategies: Strategy implementations (planner_skip, direct, synthesis, summary)
"""

from .goal_completion import GoalCompletionModule

__all__ = ["GoalCompletionModule"]
