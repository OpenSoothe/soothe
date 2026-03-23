"""MemU - File-based memory system for AI agents.

A Python framework for creating and managing AI agent memories through file-based storage.
Simplified unified memory architecture with a single Memory Agent.
"""

from __future__ import annotations

__version__ = "0.1.9"
__author__ = "MemU Team"
__email__ = "support@nevamind.ai"

from .llm_client import BaseLLMClient
from .memory import MemoryAgent, MemoryFileManager
from .memory_store import MemuMemoryStore

__all__ = [
    "BaseLLMClient",
    "MemoryAgent",
    "MemoryFileManager",
    "MemuMemoryStore",
]
