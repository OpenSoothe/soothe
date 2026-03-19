"""File operations with backup and safety features.

Re-exports all public names so ``from soothe.tools.file_edit import X`` works.
"""

from soothe.tools._internal.file_edit.tools import (
    CreateFileTool,
    DeleteFileTool,
    GetFileInfoTool,
    ListFilesTool,
    ReadFileTool,
    SearchInFilesTool,
    create_file_edit_tools,
)
from soothe.tools._internal.file_edit.utils import _display_path, _normalize_workspace_relative_input

__all__ = [
    "CreateFileTool",
    "DeleteFileTool",
    "GetFileInfoTool",
    "ListFilesTool",
    "ReadFileTool",
    "SearchInFilesTool",
    "_display_path",
    "_normalize_workspace_relative_input",
    "create_file_edit_tools",
]
