"""Tests for File Ops tools functionality.

Tests surgical file operations provided by soothe.toolkits.file_ops:
- delete: Delete files/directories with optional backup
- file_info: Get file metadata
- edit_lines: Replace specific line ranges
- insert_lines: Insert content at specific line
- delete_lines: Delete specific line ranges
- apply_diff: Apply unified diff patches

Note: This toolkit does NOT provide read_file, write_file, search_files, list_files
(those are provided by soothe_deepagents FilesystemMiddleware).
"""

import asyncio

import pytest
from langchain.tools import ToolRuntime

# ---------------------------------------------------------------------------
# Middleware Fixture (Reference Implementation)
# ---------------------------------------------------------------------------


@pytest.fixture
def middleware(tmp_path):
    """Create SootheFilesystemMiddleware for testing.

    This is the reference pattern for testing file_ops tools.
    """
    from soothe_deepagents.backends.filesystem import FilesystemBackend

    from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

    backend = FilesystemBackend(root_dir=tmp_path)
    return SootheFilesystemMiddleware(backend=backend, backup_enabled=True)


@pytest.fixture
def delete_tool(middleware):
    """Get delete tool from middleware."""
    return next(t for t in middleware.tools if t.name == "delete")


@pytest.fixture
def info_tool(middleware):
    """Get file_info tool from middleware."""
    return next(t for t in middleware.tools if t.name == "file_info")


@pytest.fixture
def edit_tool(middleware):
    """Get edit_lines tool from middleware."""
    return next(t for t in middleware.tools if t.name == "edit_lines")


@pytest.fixture
def insert_tool(middleware):
    """Get insert_lines tool from middleware."""
    return next(t for t in middleware.tools if t.name == "insert_lines")


@pytest.fixture
def delete_lines_tool(middleware):
    """Get delete_lines tool from middleware."""
    return next(t for t in middleware.tools if t.name == "delete_lines")


@pytest.fixture
def apply_diff_tool(middleware):
    """Get apply_diff tool from middleware."""
    return next(t for t in middleware.tools if t.name == "apply_diff")


def _runtime(tool_call_id: str) -> ToolRuntime:
    return ToolRuntime(
        state={"messages": [], "files": {}},
        context=None,
        tool_call_id=tool_call_id,
        store=None,
        stream_writer=lambda _: None,
        config={},
    )


def _invoke_tool(tool, args: dict[str, object], *, tool_call_id: str) -> object:
    try:
        return tool.invoke(args)
    except TypeError as exc:
        if "missing 1 required positional argument: 'runtime'" not in str(exc):
            raise
        return tool.func(runtime=_runtime(tool_call_id), **args)


def _ainvoke_tool(tool, args: dict[str, object], *, tool_call_id: str) -> object:
    try:
        return asyncio.run(tool.ainvoke(args))
    except TypeError as exc:
        if "missing 1 required positional argument: 'runtime'" not in str(exc):
            raise
        return asyncio.run(tool.coroutine(runtime=_runtime(tool_call_id), **args))


# ---------------------------------------------------------------------------
# Delete File Tool Tests
# ---------------------------------------------------------------------------


class TestDeleteFileTool:
    """Test delete tool functionality."""

    def test_tool_metadata(self, delete_tool) -> None:
        """Test tool metadata."""
        assert delete_tool.name == "delete"
        assert "delete" in delete_tool.description.lower()

    def test_delete_existing_file(self, delete_tool, tmp_path) -> None:
        """Test deleting an existing file."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("Hello, World!")

        result = _invoke_tool(
            delete_tool, {"file_path": str(file_path), "backup": True}, tool_call_id="delete_1"
        )
        text = str(getattr(result, "content", result))

        assert "Deleted" in text or "deleted" in text.lower()
        assert not file_path.exists()

    def test_delete_nonexistent_file(self, delete_tool) -> None:
        """Test deleting a non-existent file."""
        result = _invoke_tool(
            delete_tool, {"file_path": "/nonexistent/file.txt"}, tool_call_id="delete_2"
        )
        text = str(getattr(result, "content", result))

        assert "Error" in text
        assert "not_found" in text.lower() or "not found" in text.lower()

    def test_delete_with_backup(self, delete_tool, tmp_path) -> None:
        """Test deleting file with backup."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("Hello, World!")

        result = _invoke_tool(
            delete_tool, {"file_path": str(file_path), "backup": True}, tool_call_id="delete_3"
        )
        text = str(getattr(result, "content", result))

        assert "backup" in text.lower()

    def test_async_delete_works(self, delete_tool, tmp_path) -> None:
        """Async invoke should work correctly."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("Hello, World!")

        result = _ainvoke_tool(delete_tool, {"file_path": str(file_path)}, tool_call_id="delete_4")
        text = str(getattr(result, "content", result))

        assert "Deleted" in text or "deleted" in text.lower()
        assert not file_path.exists()


# ---------------------------------------------------------------------------
# File Info Tool Tests
# ---------------------------------------------------------------------------


class TestFileInfoTool:
    """Test file_info tool functionality."""

    def test_tool_metadata(self, info_tool) -> None:
        """Test tool metadata."""
        assert info_tool.name == "file_info"
        assert (
            "info" in info_tool.description.lower() or "metadata" in info_tool.description.lower()
        )

    def test_get_file_info(self, info_tool, tmp_path) -> None:
        """Test getting file info."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("Hello, World!")

        result = _invoke_tool(info_tool, {"path": str(file_path)}, tool_call_id="file_info_1")
        text = str(getattr(result, "content", result))

        assert "Path:" in text
        assert "Size:" in text
        assert "Modified:" in text

    def test_get_nonexistent_file_info(self, info_tool) -> None:
        """Test getting info for non-existent file."""
        result = _invoke_tool(
            info_tool, {"path": "/nonexistent/file.txt"}, tool_call_id="file_info_2"
        )
        text = str(getattr(result, "content", result))

        assert "Error" in text
        assert "not_found" in text.lower() or "not found" in text.lower()


# ---------------------------------------------------------------------------
# Surgical Code Editing Tools
# ---------------------------------------------------------------------------


class TestEditFileLinesTool:
    """Tests for edit_lines tool."""

    def test_replace_single_line(self, edit_tool, tmp_path) -> None:
        """Test replacing a single line."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        result = _invoke_tool(
            edit_tool,
            {
                "file_path": str(test_file),
                "start_line": 2,
                "end_line": 2,
                "new_content": "modified_line2",
            },
            tool_call_id="edit_lines_1",
        )
        text = str(getattr(result, "content", result))

        assert "Updated" in text or "updated" in text.lower()
        assert "1 removed, 1 added" in text

        content = test_file.read_text()
        assert "modified_line2" in content
        assert "line1" in content
        assert "line3" in content

    def test_replace_multiple_lines(self, edit_tool, tmp_path) -> None:
        """Test replacing multiple lines."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = _invoke_tool(
            edit_tool,
            {
                "file_path": str(test_file),
                "start_line": 2,
                "end_line": 4,
                "new_content": "new2\nnew3\nnew4",
            },
            tool_call_id="edit_lines_2",
        )
        text = str(getattr(result, "content", result))

        assert "Updated" in text or "updated" in text.lower()
        assert "3 removed, 3 added" in text

        content = test_file.read_text()
        assert "line1" in content
        assert "new2" in content
        assert "new3" in content
        assert "new4" in content
        assert "line5" in content

    def test_replace_with_different_line_count(self, edit_tool, tmp_path) -> None:
        """Test replacing with different number of lines."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        result = _invoke_tool(
            edit_tool,
            {
                "file_path": str(test_file),
                "start_line": 2,
                "end_line": 3,
                "new_content": "new1\nnew2\nnew3\nnew4",
            },
            tool_call_id="edit_lines_3",
        )
        text = str(getattr(result, "content", result))

        assert "2 removed, 4 added" in text

        lines = test_file.read_text().splitlines()
        assert len(lines) == 5

    def test_invalid_line_range(self, edit_tool, tmp_path) -> None:
        """Test error handling for invalid line range."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\n")

        result = _invoke_tool(
            edit_tool,
            {"file_path": str(test_file), "start_line": 5, "end_line": 6, "new_content": "x"},
            tool_call_id="edit_lines_4",
        )
        text = str(getattr(result, "content", result))
        assert "Error" in text
        assert "exceeds file length" in text or "Invalid start_line" in text

        result = _invoke_tool(
            edit_tool,
            {"file_path": str(test_file), "start_line": 1, "end_line": 5, "new_content": "x"},
            tool_call_id="edit_lines_5",
        )
        text = str(getattr(result, "content", result))
        assert "Error" in text
        assert "exceeds file length" in text or "Invalid end_line" in text

    def test_file_not_found(self, edit_tool) -> None:
        """Test error handling for missing file."""
        result = _invoke_tool(
            edit_tool,
            {
                "file_path": "/nonexistent/file.py",
                "start_line": 1,
                "end_line": 1,
                "new_content": "x",
            },
            tool_call_id="edit_lines_6",
        )
        text = str(getattr(result, "content", result))
        assert "Error" in text
        assert "not found" in text.lower()


class TestInsertLinesTool:
    """Tests for insert_lines tool."""

    def test_insert_at_beginning(self, insert_tool, tmp_path) -> None:
        """Test inserting at beginning of file."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\n")

        _invoke_tool(
            insert_tool,
            {"file_path": str(test_file), "line": 1, "content": "new_first"},
            tool_call_id="insert_lines_1",
        )

        lines = test_file.read_text().splitlines()
        assert lines[0] == "new_first"
        assert lines[1] == "line1"

    def test_insert_in_middle(self, insert_tool, tmp_path) -> None:
        """Test inserting in middle of file."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        _invoke_tool(
            insert_tool,
            {"file_path": str(test_file), "line": 2, "content": "inserted"},
            tool_call_id="insert_lines_2",
        )

        content = test_file.read_text()
        assert content == "line1\ninserted\nline2\nline3\n"

    def test_insert_at_end(self, insert_tool, tmp_path) -> None:
        """Test appending at end of file."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\n")

        _invoke_tool(
            insert_tool,
            {"file_path": str(test_file), "line": 3, "content": "new_last"},
            tool_call_id="insert_lines_3",
        )

        content = test_file.read_text()
        assert content == "line1\nline2\nnew_last\n"


class TestDeleteLinesTool:
    """Tests for delete_lines tool."""

    def test_delete_single_line(self, delete_lines_tool, tmp_path) -> None:
        """Test deleting a single line."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        _invoke_tool(
            delete_lines_tool,
            {"file_path": str(test_file), "start_line": 2, "end_line": 2},
            tool_call_id="delete_lines_1",
        )

        content = test_file.read_text()
        assert content == "line1\nline3\n"

    def test_delete_multiple_lines(self, delete_lines_tool, tmp_path) -> None:
        """Test deleting multiple lines."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        _invoke_tool(
            delete_lines_tool,
            {"file_path": str(test_file), "start_line": 2, "end_line": 4},
            tool_call_id="delete_lines_2",
        )

        content = test_file.read_text()
        assert content == "line1\nline5\n"


class TestApplyDiffTool:
    """Tests for apply_diff tool."""

    def test_apply_simple_diff(self, apply_diff_tool, tmp_path) -> None:
        """Test applying a simple diff."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    print('world')\n")

        diff = f"""--- {test_file.name}
+++ {test_file.name}
@@ -1,2 +1,2 @@
 def hello():
-    print('world')
+    print('hello')
"""

        _invoke_tool(
            apply_diff_tool,
            {"file_path": str(test_file), "diff": diff},
            tool_call_id="apply_diff_1",
        )

        content = test_file.read_text()
        assert "print('hello')" in content
        assert "print('world')" not in content

    def test_apply_diff_file_not_found(self, apply_diff_tool) -> None:
        """Test applying diff to non-existent file."""
        diff = "--- nonexistent.py\n+++ nonexistent.py\n@@ -1 +1 @@\n-old\n+new\n"
        result = _invoke_tool(
            apply_diff_tool,
            {"file_path": "/nonexistent/file.py", "diff": diff},
            tool_call_id="apply_diff_2",
        )
        text = str(getattr(result, "content", result))

        assert "Error" in text
        assert "not found" in text.lower()
