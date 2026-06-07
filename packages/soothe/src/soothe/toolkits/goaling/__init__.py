"""Layer 2 goaling tools for proactive DAG manipulation.

Tools in this package allow AgentLoop to proactively suggest goals and
record findings during execution. Proposals are queued and processed after
iteration completion.
"""

from soothe.toolkits.goaling.add_finding import AddFindingTool
from soothe.toolkits.goaling.suggest_goal import SuggestGoalTool

__all__ = ["SuggestGoalTool", "AddFindingTool"]
