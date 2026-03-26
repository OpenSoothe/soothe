"""CLI InformationSource wrapping the persistent shell tool."""

from __future__ import annotations

import logging
from typing import Any

from soothe.subagents.research.protocol import GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_DIRECT_COMMAND_SCORE = 0.9
_MIN_CLI_SCORE = 0.05

_SAFE_INFO_COMMANDS: dict[str, str] = {
    "git log": "git log --oneline -20",
    "git history": "git log --oneline -20",
    "git blame": "git blame",
    "git status": "git status --short",
    "git diff": "git diff --stat",
    "git branch": "git branch -a",
    "process": "ps aux | head -30",
    "running": "ps aux | head -30",
    "disk usage": "df -h",
    "disk space": "df -h",
    "installed": "which",
    "version": "--version",
    "env var": "env | head -40",
    "environment": "env | head -40",
    "port": "lsof -i -P -n | head -20",
    "network": "netstat -an | head -20",
    "docker": "docker ps -a",
    "container": "docker ps -a",
    "system info": "uname -a",
}


class CLISource:
    """Information source backed by CLI command execution.

    Translates research queries into safe, read-only CLI commands and
    returns their output.  Only runs information-gathering commands;
    never executes destructive operations.

    Args:
        workspace_root: Working directory for the shell.
    """

    def __init__(self, workspace_root: str = "") -> None:
        """Initialize the CLI source with workspace root for the shell."""
        self._workspace_root = workspace_root
        self._cli_tool: Any | None = None

    def _ensure_tool(self) -> None:
        if self._cli_tool is not None:
            return
        from soothe.tools.execution import RunCommandTool

        self._cli_tool = RunCommandTool(workspace_root=self._workspace_root)

    # -- InformationSource protocol ------------------------------------------

    @property
    def name(self) -> str:
        """Source name."""
        return "cli"

    @property
    def source_type(self) -> SourceType:
        """Canonical source type."""
        return "cli"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Translate the query into a CLI command and execute it.

        Args:
            query: Natural-language query or direct command.
            context: Current research context.

        Returns:
            List of SourceResult with command output.
        """
        _ = context
        self._ensure_tool()
        results: list[SourceResult] = []

        command = self._query_to_command(query)
        if not command:
            return results

        try:
            raw = await self._cli_tool._arun(command)
            if raw and not raw.startswith("Error:"):
                results.append(
                    SourceResult(
                        content=raw[:5000],
                        source_ref=f"$ {command}",
                        source_name="cli",
                        metadata={"command": command},
                    )
                )
        except Exception:
            logger.debug("CLI query failed for command: %s", command, exc_info=True)

        return results

    def relevance_score(self, query: str) -> float:
        """Score high for queries about system state, git, processes."""
        from ._scoring import _CLI_KEYWORDS, keyword_score

        q_lower = query.lower()

        if q_lower.startswith(("$ ", "run ")):
            return _DIRECT_COMMAND_SCORE

        score = keyword_score(q_lower, _CLI_KEYWORDS, weight=0.2)
        return min(1.0, max(_MIN_CLI_SCORE, score))

    # -- Query-to-command translation ----------------------------------------

    @staticmethod
    def _query_to_command(query: str) -> str:
        """Translate a query into a safe CLI command.

        If the query starts with ``$`` or ``run``, use it as a direct command
        (after stripping the prefix).  Otherwise, match against known safe
        information-gathering patterns.

        Returns:
            A CLI command string, or empty string if no safe mapping found.
        """
        stripped = query.strip()

        if stripped.startswith("$ "):
            return stripped[2:].strip()
        if stripped.lower().startswith("run "):
            return stripped[4:].strip()

        q_lower = stripped.lower()
        for trigger, template in _SAFE_INFO_COMMANDS.items():
            if trigger in q_lower:
                extra = q_lower.replace(trigger, "").strip()
                if template.endswith("--version") and extra:
                    return f"{extra} --version"
                if template == "which" and extra:
                    return f"which {extra}"
                if template.startswith("git blame") and extra:
                    return f"git blame {extra}"
                return template

        if "find" in q_lower and ("file" in q_lower or "dir" in q_lower):
            return "find . -maxdepth 3 -type f | head -50"

        return ""
