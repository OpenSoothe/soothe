"""Soothe subagents exposed as deepagents SubAgent/CompiledSubAgent."""

from soothe_daemon.subagents.browser import create_browser_subagent
from soothe_daemon.subagents.claude import create_claude_subagent

__all__ = [
    "create_browser_subagent",
    "create_claude_subagent",
]
