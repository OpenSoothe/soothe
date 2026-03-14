"""Core framework logic -- usable without CLI dependencies."""

from soothe.core.agent import create_soothe_agent
from soothe.core.runner import SootheRunner

__all__ = ["SootheRunner", "create_soothe_agent"]
