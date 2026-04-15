"""Soothe subagents exposed as deepagents SubAgent/CompiledSubAgent."""

from soothe.subagents.browser import create_browser_subagent
from soothe.subagents.claude import create_claude_subagent

__all__ = [
    "create_browser_subagent",
    "create_claude_subagent",
]
