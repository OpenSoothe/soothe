"""Soothe: Multi-agent harness built on deepagents and langchain/langgraph."""

from soothe.agent import create_soothe_agent
from soothe.config import SootheConfig

__all__ = ["SootheConfig", "create_soothe_agent"]
