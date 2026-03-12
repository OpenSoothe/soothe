"""Soothe subagents migrated from noesium, exposed as deepagents SubAgent/CompiledSubAgent."""

from soothe.subagents.browser import create_browser_subagent
from soothe.subagents.claude import create_claude_subagent
from soothe.subagents.planner import create_planner_subagent
from soothe.subagents.research import create_research_subagent
from soothe.subagents.scout import create_scout_subagent

__all__ = [
    "create_browser_subagent",
    "create_claude_subagent",
    "create_planner_subagent",
    "create_research_subagent",
    "create_scout_subagent",
]
