"""Semantic context loader for the Context Engine (RFC-624)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_INSTRUCTION_FILES: dict[str, str] = {
    "project": "CLAUDE.md",
    "agent": "AGENTS.md",
    "memory": "MEMORY.md",
}


class SemanticLoader:
    """Loads static project instruction files for semantic context.

    Gracefully returns empty strings when files are missing.
    """

    def __init__(self, soothe_home: Path | None = None, workspace: Path | None = None) -> None:
        self._soothe_home = soothe_home
        self._workspace = workspace

    def load_project_instructions(self) -> str:
        """Load CLAUDE.md content."""
        return self._load_file("CLAUDE.md")

    def load_agent_instructions(self) -> str:
        """Load AGENTS.md content."""
        return self._load_file("AGENTS.md")

    def load_memory(self) -> str:
        """Load MEMORY.md content."""
        return self._load_file("MEMORY.md")

    def _load_file(self, name: str) -> str:
        """Try loading a file from workspace then SOOTHE_HOME, return empty on failure."""
        for base in self._search_paths():
            path = base / name
            if path.is_file():
                try:
                    return path.read_text(encoding="utf-8")
                except OSError:
                    logger.debug("Failed to read %s", path, exc_info=True)
        return ""

    def _search_paths(self) -> list[Path]:
        paths: list[Path] = []
        if self._workspace:
            paths.append(self._workspace)
        if self._soothe_home:
            paths.append(self._soothe_home)
        return paths
