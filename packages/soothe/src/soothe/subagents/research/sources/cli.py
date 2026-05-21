"""CLI InformationSource wrapping shell and filesystem tools.

Enhanced with filesystem tools (glob, grep, ls, read_file, file_info)
for comprehensive code exploration capabilities.
"""

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
    """Information source backed by CLI and filesystem tools.

    Translates research queries into safe operations using:
    - Shell commands for system/git/process queries
    - Filesystem tools (glob, grep, read_file, file_info) for code exploration

    Args:
        workspace_root: Working directory for operations.
        allow_outside_workdir: Allow access outside the work directory.
    """

    def __init__(
        self,
        workspace_root: str = "",
        *,
        allow_outside_workdir: bool = False,
    ) -> None:
        """Initialize the CLI source with workspace root."""
        self._workspace_root = workspace_root
        self._allow_outside = allow_outside_workdir
        self._cli_tool: Any | None = None
        self._glob_tool: Any | None = None
        self._grep_tool: Any | None = None
        self._read_tool: Any | None = None
        self._file_info_tool: Any | None = None
        self._ls_tool: Any | None = None

    def _ensure_tools(self) -> None:
        """Lazy-load all tools."""
        if self._cli_tool is not None:
            return

        # Shell tool
        try:
            from soothe.toolkits.execution import RunCommandShellTool

            self._cli_tool = RunCommandShellTool(workspace_root=self._workspace_root)
        except Exception:
            logger.debug("Shell tool not available", exc_info=True)

        # Filesystem tools from deepagents
        try:
            from deepagents.middleware.filesystem import FilesystemMiddleware

            middleware = FilesystemMiddleware()
            for tool in middleware.tools:
                name = tool.name
                if name == "glob":
                    self._glob_tool = tool
                elif name == "grep":
                    self._grep_tool = tool
                elif name == "read_file":
                    self._read_tool = tool
                elif name == "file_info":
                    self._file_info_tool = tool
                elif name == "ls":
                    self._ls_tool = tool
        except ImportError:
            logger.debug("deepagents filesystem tools not available", exc_info=True)

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
        """Execute CLI or filesystem query based on query type.

        Args:
            query: Natural-language query, command, or file pattern.
            context: Current research context.

        Returns:
            List of SourceResult with command output or file content.
        """
        _ = context
        self._ensure_tools()
        results: list[SourceResult] = []

        q_lower = query.lower().strip()

        # Check if this is a filesystem query
        if self._is_filesystem_query(q_lower):
            fs_results = await self._handle_filesystem_query(query)
            results.extend(fs_results)

        # Check if this is a shell command query
        command = self._query_to_command(query)
        if command and self._cli_tool:
            try:
                raw = await self._cli_tool._arun(command)
                if raw and not raw.startswith("Error:"):
                    results.append(
                        SourceResult(
                            content=raw[:5000],
                            source_ref=f"$ {command}",
                            source_name="cli",
                            metadata={"command": command, "type": "shell"},
                        )
                    )
            except Exception:
                logger.debug("CLI query failed for command: %s", command, exc_info=True)

        return results

    def relevance_score(self, query: str) -> float:
        """Score high for queries about system state, git, processes, files."""
        from ._scoring import _CLI_KEYWORDS, _CODE_KEYWORDS, keyword_score

        q_lower = query.lower()

        # Direct command
        if q_lower.startswith(("$ ", "run ")):
            return _DIRECT_COMMAND_SCORE

        # File path or glob pattern
        if self._is_filesystem_query(q_lower):
            return 0.8

        # CLI keywords
        cli_score = keyword_score(q_lower, _CLI_KEYWORDS, weight=0.2)
        code_score = keyword_score(q_lower, _CODE_KEYWORDS, weight=0.2)

        return min(1.0, max(_MIN_CLI_SCORE, cli_score, code_score))

    # -- Filesystem query handling -------------------------------------------

    def _is_filesystem_query(self, q: str) -> bool:
        """Check if query looks like a filesystem operation."""
        fs_indicators = [
            "find file",
            "search file",
            "list file",
            "glob ",
            "*.py",
            "*.js",
            "*.ts",
            "*.md",
            "file info",
            "file size",
            "read file",
            "show file",
            "cat ",
            "ls ",
            "dir ",
            "directory",
        ]
        return any(ind in q for ind in fs_indicators) or self._looks_like_path(q)

    @staticmethod
    def _looks_like_path(q: str) -> bool:
        """Check if query looks like a file path."""
        return bool(
            q.startswith(("./", "/", "~/"))
            or "/" in q
            or q.endswith((".py", ".js", ".ts", ".md", ".txt", ".json", ".yml", ".yaml"))
            or "*" in q
        )

    async def _handle_filesystem_query(self, query: str) -> list[SourceResult]:
        """Handle filesystem-related queries using tools."""
        results: list[SourceResult] = []
        q_lower = query.lower().strip()

        # File listing / glob patterns
        if any(kw in q_lower for kw in ["list", "find", "glob", "show", "*."]):
            pattern = self._extract_pattern(query)
            if pattern and self._glob_tool:
                try:
                    raw = await self._glob_tool._arun(pattern=pattern)
                    if raw:
                        results.append(
                            SourceResult(
                                content=raw[:5000],
                                source_ref=f"glob:{pattern}",
                                source_name="cli",
                                metadata={"type": "glob", "pattern": pattern},
                            )
                        )
                except Exception:
                    logger.debug("Glob query failed for: %s", pattern, exc_info=True)

        # File content search (grep)
        if any(kw in q_lower for kw in ["search", "grep", "find in", "contains"]):
            search_params = self._extract_search_params(query)
            if search_params and self._grep_tool:
                try:
                    raw = await self._grep_tool._arun(**search_params)
                    if raw:
                        results.append(
                            SourceResult(
                                content=raw[:5000],
                                source_ref=f"grep:{search_params.get('pattern', '')}",
                                source_name="cli",
                                metadata={"type": "grep", "params": search_params},
                            )
                        )
                except Exception:
                    logger.debug("Grep query failed for: %s", search_params, exc_info=True)

        # Read specific file
        if any(kw in q_lower for kw in ["read", "show", "cat", "content"]) or self._looks_like_path(
            query.strip().split()[0] if query.strip() else ""
        ):
            path = self._extract_path(query)
            if path and self._read_tool:
                try:
                    raw = await self._read_tool._arun(file_path=path)
                    if raw:
                        results.append(
                            SourceResult(
                                content=raw[:5000],
                                source_ref=path,
                                source_name="cli",
                                metadata={"type": "read_file", "path": path},
                            )
                        )
                except Exception:
                    logger.debug("Read file query failed for: %s", path, exc_info=True)

        # File info
        if "file info" in q_lower or "file size" in q_lower or "metadata" in q_lower:
            path = self._extract_path(query)
            if path and self._file_info_tool:
                try:
                    raw = await self._file_info_tool._arun(path=path)
                    if raw:
                        results.append(
                            SourceResult(
                                content=str(raw)[:5000],
                                source_ref=path,
                                source_name="cli",
                                metadata={"type": "file_info", "path": path},
                            )
                        )
                except Exception:
                    logger.debug("File info query failed for: %s", path, exc_info=True)

        return results

    @staticmethod
    def _extract_pattern(query: str) -> str:
        """Extract glob pattern from query."""
        # Look for patterns like *.py, **/*.md, etc.
        words = query.split()
        for word in words:
            if "*" in word or word.endswith((".py", ".js", ".ts", ".md", ".txt")):
                return word.strip("'\"")
        # Default pattern
        return "*"

    @staticmethod
    def _extract_search_params(query: str) -> dict[str, Any] | None:
        """Extract grep parameters from query."""
        q_lower = query.lower()
        params: dict[str, Any] = {"pattern": ""}

        # Try to extract pattern after keywords
        for prefix in ["search for", "grep", "find", "contains"]:
            if prefix in q_lower:
                idx = q_lower.find(prefix) + len(prefix)
                remainder = query[idx:].strip()
                # Take first word or quoted string
                if remainder.startswith('"') or remainder.startswith("'"):
                    end = remainder.find(remainder[0], 1)
                    if end > 0:
                        params["pattern"] = remainder[1:end]
                else:
                    params["pattern"] = remainder.split()[0] if remainder.split() else "."
                break

        if not params["pattern"]:
            return None

        # Extract path if present
        for word in query.split():
            if "/" in word or word.startswith("./"):
                params["path"] = word.strip("'\"")
                break

        return params

    @staticmethod
    def _extract_path(query: str) -> str | None:
        """Extract file path from query."""
        words = query.split()
        for word in words:
            clean = word.strip("'\"")
            if "/" in clean or clean.startswith("./") or clean.startswith("~/"):
                return clean
            # Check for file extensions
            if "." in clean and clean.split(".")[-1] in [
                "py",
                "js",
                "ts",
                "md",
                "txt",
                "json",
                "yml",
                "yaml",
                "rs",
                "go",
                "java",
                "cpp",
                "c",
                "h",
            ]:
                return clean
        return None

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

        return ""
