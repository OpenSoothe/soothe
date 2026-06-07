"""Layer 2 proposal tools for proactive DAG manipulation.

Tools in this package allow AgentLoop to proactively suggest goals and
record findings during execution. Proposals are queued and processed after
iteration completion.
"""

from soothe.toolkits.proposal.add_finding import AddFindingTool
from soothe.toolkits.proposal.suggest_goal import SuggestGoalTool

__all__ = ["SuggestGoalTool", "AddFindingTool"]
