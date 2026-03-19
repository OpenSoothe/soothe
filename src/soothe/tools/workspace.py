"""Unified workspace tool for file operations (RFC-0014).

Consolidates file_edit tools (create, read, delete, list, search, info)
into a single action-dispatched tool.  The LLM picks the action; the
tool routes to the appropriate implementation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.utils import expand_path

logger = logging.getLogger(__name__)


class WorkspaceTool(BaseTool):
    """Unified file and codebase operations.

    Supports actions: read, write, delete, search, list, info.
    """

    name: str = "workspace"
    description: str = (
        "File and codebase operations. "
        "Provide `action` and relevant parameters.\n"
        "Actions:\n"
        "- 'read': Read file contents. Params: `path`, optional `start_line`, `end_line`.\n"
        "- 'write': Create or update a file. Params: `path`, `content`, optional `overwrite` (default false).\n"
        "- 'delete': Delete a file (backup created). Params: `path`.\n"
        "- 'search': Search for a regex pattern in files (like grep). "
        "Params: `pattern`, optional `path` (directory), `file_pattern` (e.g. '*.py').\n"
        "- 'list': List files in a directory. Params: optional `path`, `pattern`, `recursive`.\n"
        "- 'info': Get file metadata (size, timestamps). Params: `path`."
    )

    work_dir: str = Field(default="")
    allow_outside_workdir: bool = Field(default=False)

    def _get_resolved_cwd(self) -> str:
        """Return the resolved workspace directory."""
        return str(expand_path(self.work_dir)) if self.work_dir else str(Path.cwd())

    def _run(
        self,
        action: str,
        path: str = ".",
        content: str = "",
        pattern: str = "",
        file_pattern: str = "*",
        start_line: int | None = None,
        end_line: int | None = None,
        *,
        overwrite: bool = False,
        recursive: bool = False,
        **_kwargs: Any,
    ) -> str:
        """Dispatch to the appropriate file operation.

        Args:
            action: One of 'read', 'write', 'delete', 'search', 'list', 'info'.
            path: File or directory path (relative to workspace).
            content: File content (for 'write').
            pattern: Regex pattern (for 'search').
            file_pattern: Glob filter (for 'search' and 'list').
            start_line: Start line for 'read' (1-indexed).
            end_line: End line for 'read' (inclusive).
            overwrite: Allow overwriting existing files (for 'write').
            recursive: Recursive listing (for 'list').

        Returns:
            Operation result or error message.
        """
        action = action.strip().lower()

        if action == "read":
            return self._do_read(path, start_line, end_line)
        if action == "write":
            return self._do_write(path, content, overwrite=overwrite)
        if action == "delete":
            return self._do_delete(path)
        if action == "search":
            return self._do_search(pattern, path, file_pattern)
        if action == "list":
            return self._do_list(path, file_pattern, recursive=recursive)
        if action == "info":
            return self._do_info(path)

        return f"Error: Unknown action '{action}'. Use: read, write, delete, search, list, info."

    async def _arun(self, action: str, **kwargs: Any) -> str:
        """Async dispatch (delegates to sync)."""
        return self._run(action, **kwargs)

    # ------------------------------------------------------------------
    # Internal dispatch methods
    # ------------------------------------------------------------------

    def _do_read(self, path: str, start_line: int | None, end_line: int | None) -> str:
        from soothe.tools._internal.file_edit.tools import ReadFileTool

        tool = ReadFileTool(work_dir=self.work_dir, allow_outside_workdir=self.allow_outside_workdir)
        return tool._run(path, start_line=start_line, end_line=end_line)

    def _do_write(self, path: str, content: str, *, overwrite: bool) -> str:
        from soothe.tools._internal.file_edit.tools import CreateFileTool

        tool = CreateFileTool(work_dir=self.work_dir, allow_outside_workdir=self.allow_outside_workdir)
        return tool._run(path, content, overwrite=overwrite)

    def _do_delete(self, path: str) -> str:
        from soothe.tools._internal.file_edit.tools import DeleteFileTool

        tool = DeleteFileTool(work_dir=self.work_dir, allow_outside_workdir=self.allow_outside_workdir)
        return tool._run(path)

    def _do_search(self, pattern: str, path: str, file_pattern: str) -> str:
        if not pattern:
            return "Error: 'pattern' is required for search action."
        from soothe.tools._internal.file_edit.tools import SearchInFilesTool

        tool = SearchInFilesTool(work_dir=self.work_dir)
        return tool._run(pattern, path, file_pattern)

    def _do_list(self, path: str, pattern: str, *, recursive: bool) -> str:
        from soothe.tools._internal.file_edit.tools import ListFilesTool

        tool = ListFilesTool(work_dir=self.work_dir)
        return tool._run(path, pattern, recursive=recursive)

    def _do_info(self, path: str) -> str:
        from soothe.tools._internal.file_edit.tools import GetFileInfoTool

        tool = GetFileInfoTool(work_dir=self.work_dir, allow_outside_workdir=self.allow_outside_workdir)
        return tool._run(path)


def create_workspace_tools(
    *,
    work_dir: str = "",
    allow_outside_workdir: bool = False,
) -> list[BaseTool]:
    """Create the unified workspace tool.

    Args:
        work_dir: Working directory for relative paths.
        allow_outside_workdir: Allow access outside workspace.

    Returns:
        List containing a single WorkspaceTool.
    """
    return [WorkspaceTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir)]
