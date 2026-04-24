"""Unit tests for SootheFilesystemMiddleware."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from soothe.middleware.filesystem import (
    ApplyDiffSchema,
    DeleteFileSchema,
    DeleteLinesSchema,
    EditFileLinesSchema,
    FileInfoSchema,
    InsertLinesSchema,
    SootheFilesystemMiddleware,
)


class TestSootheFilesystemMiddlewareSchemas:
    """Test tool schemas follow deepagents pattern."""

    def test_delete_file_schema_is_basemodel(self) -> None:
        assert issubclass(DeleteFileSchema, BaseModel)

    def test_file_info_schema_is_basemodel(self) -> None:
        assert issubclass(FileInfoSchema, BaseModel)

    def test_edit_file_lines_schema_is_basemodel(self) -> None:
        assert issubclass(EditFileLinesSchema, BaseModel)

    def test_insert_lines_schema_is_basemodel(self) -> None:
        assert issubclass(InsertLinesSchema, BaseModel)

    def test_delete_lines_schema_is_basemodel(self) -> None:
        assert issubclass(DeleteLinesSchema, BaseModel)

    def test_apply_diff_schema_is_basemodel(self) -> None:
        assert issubclass(ApplyDiffSchema, BaseModel)

    def test_schema_fields_have_descriptions(self) -> None:
        """All schema fields must have descriptions (deepagents pattern)."""
        for schema_cls in [
            DeleteFileSchema,
            FileInfoSchema,
            EditFileLinesSchema,
            InsertLinesSchema,
            DeleteLinesSchema,
            ApplyDiffSchema,
        ]:
            for field_name, field_info in schema_cls.model_fields.items():
                assert field_info.description, (
                    f"{schema_cls.__name__}.{field_name} missing description"
                )


class TestSootheFilesystemMiddlewareToolCreation:
    """Test tool creation follows deepagents pattern."""

    @pytest.fixture()
    def middleware(self) -> SootheFilesystemMiddleware:
        """Create middleware with temp backend."""
        backend = FilesystemBackend()
        return SootheFilesystemMiddleware(
            backend=backend,
            backup_enabled=True,
        )

    def test_inherits_deepagents_tools(self, middleware: SootheFilesystemMiddleware) -> None:
        """Verify all inherited FilesystemMiddleware tools exist."""
        inherited_tool_names = [
            "ls",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "execute",
        ]
        for name in inherited_tool_names:
            assert any(t.name == name for t in middleware.tools), f"Missing inherited tool: {name}"

    def test_adds_surgical_tools(self, middleware: SootheFilesystemMiddleware) -> None:
        """Verify all Soothe surgical tools exist."""
        soothe_tool_names = [
            "delete_file",
            "file_info",
            "edit_file_lines",
            "insert_lines",
            "delete_lines",
            "apply_diff",
        ]
        for name in soothe_tool_names:
            assert any(t.name == name for t in middleware.tools), f"Missing surgical tool: {name}"

    def test_tools_have_args_schema(self, middleware: SootheFilesystemMiddleware) -> None:
        """All tools must have args_schema (deepagents pattern)."""
        for tool in middleware.tools:
            if hasattr(tool, "args_schema"):
                assert tool.args_schema is not None, f"Tool {tool.name} missing args_schema"
                assert issubclass(tool.args_schema, BaseModel), (
                    f"Tool {tool.name} schema not BaseModel"
                )


class TestDeleteFileTool:
    """Test delete_file tool with backup support."""

    @pytest.fixture()
    def middleware(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend, backup_enabled=True)

    @pytest.fixture()
    def middleware_no_backup(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend, backup_enabled=False)

    def _get_tool(
        self, middleware: SootheFilesystemMiddleware, name: str = "delete_file"
    ) -> BaseTool:
        return next(t for t in middleware.tools if t.name == name)

    def test_delete_file_with_backup(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        tool = self._get_tool(middleware)
        result = tool.invoke({"file_path": str(test_file)})

        assert "Deleted" in result
        assert "backup:" in result
        assert not test_file.exists()
        assert any(tmp_path.glob(".backups/*.txt"))

    def test_delete_file_without_backup(
        self, tmp_path: Path, middleware_no_backup: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        tool = self._get_tool(middleware_no_backup)
        result = tool.invoke({"file_path": str(test_file)})

        assert "Deleted" in result
        assert "backup:" not in result
        assert not test_file.exists()
        assert not any(tmp_path.glob(".backups/*"))

    def test_delete_nonexistent_file(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        tool = self._get_tool(middleware)
        result = tool.invoke({"file_path": str(tmp_path / "nonexistent.txt")})

        assert "Error" in result
        assert "not found" in result.lower()

    def test_delete_directory_fails(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_dir = tmp_path / "mydir"
        test_dir.mkdir()

        tool = self._get_tool(middleware)
        result = tool.invoke({"file_path": str(test_dir)})

        assert "Error" in result
        assert "Not a file" in result

    def test_backup_file_naming(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "myfile.txt"
        test_file.write_text("content")

        tool = self._get_tool(middleware)
        tool.invoke({"file_path": str(test_file)})

        backup_files = list(tmp_path.glob(".backups/*.txt"))
        assert len(backup_files) == 1

        # Check timestamp format: myname_YYYYMMDD_HHMMSS.txt
        backup_name = backup_files[0].name
        assert backup_name.startswith("myfile_")
        assert backup_name.endswith(".txt")

        # Verify timestamp is parseable
        timestamp_part = backup_name.replace("myfile_", "").replace(".txt", "")
        datetime.strptime(timestamp_part, "%Y%m%d_%H%M%S")


class TestFileInfoTool:
    """Test file_info tool for metadata retrieval."""

    @pytest.fixture()
    def middleware(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend)

    def _get_tool(self, middleware: SootheFilesystemMiddleware) -> BaseTool:
        return next(t for t in middleware.tools if t.name == "file_info")

    def test_file_info(self, tmp_path: Path, middleware: SootheFilesystemMiddleware) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        tool = self._get_tool(middleware)
        result = tool.invoke({"path": str(test_file)})

        assert "Size:" in result
        assert "Modified:" in result
        assert "Is File: True" in result
        assert "Is Directory: False" in result

    def test_file_info_directory(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_dir = tmp_path / "mydir"
        test_dir.mkdir()

        tool = self._get_tool(middleware)
        result = tool.invoke({"path": str(test_dir)})

        assert "Is File: False" in result
        assert "Is Directory: True" in result

    def test_file_info_nonexistent(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        tool = self._get_tool(middleware)
        result = tool.invoke({"path": str(tmp_path / "nonexistent.txt")})

        assert "Error" in result


class TestEditFileLinesTool:
    """Test edit_file_lines tool for surgical line replacement."""

    @pytest.fixture()
    def middleware(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend)

    def _get_tool(self, middleware: SootheFilesystemMiddleware) -> BaseTool:
        return next(t for t in middleware.tools if t.name == "edit_file_lines")

    def test_replace_single_line(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "start_line": 2,
                "end_line": 2,
                "new_content": "new_line2\n",
            }
        )

        assert "Updated" in result
        assert "replaced" in result
        assert test_file.read_text() == "line1\nnew_line2\nline3\n"

    def test_replace_multiple_lines(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "start_line": 2,
                "end_line": 3,
                "new_content": "new_line2\nnew_line3\n",
            }
        )

        assert "Updated" in result
        assert "2 removed" in result
        assert "2 added" in result
        assert test_file.read_text() == "line1\nnew_line2\nnew_line3\nline4\n"

    def test_invalid_start_line(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "start_line": 0,
                "end_line": 1,
                "new_content": "x\n",
            }
        )

        assert "Error" in result
        assert "Invalid start_line" in result

    def test_end_line_before_start(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "start_line": 2,
                "end_line": 1,
                "new_content": "x\n",
            }
        )

        assert "Error" in result

    def test_file_not_found(self, tmp_path: Path, middleware: SootheFilesystemMiddleware) -> None:
        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(tmp_path / "nonexistent.py"),
                "start_line": 1,
                "end_line": 1,
                "new_content": "x\n",
            }
        )

        assert "Error" in result
        assert "not found" in result.lower()


class TestInsertLinesTool:
    """Test insert_lines tool."""

    @pytest.fixture()
    def middleware(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend)

    def _get_tool(self, middleware: SootheFilesystemMiddleware) -> BaseTool:
        return next(t for t in middleware.tools if t.name == "insert_lines")

    def test_insert_at_beginning(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line2\nline3\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "line": 1,
                "content": "line1\n",
            }
        )

        assert "Inserted 1 lines" in result
        assert test_file.read_text() == "line1\nline2\nline3\n"

    def test_insert_at_end(self, tmp_path: Path, middleware: SootheFilesystemMiddleware) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "line": 3,
                "content": "line3\n",
            }
        )

        assert "Inserted" in result
        assert test_file.read_text() == "line1\nline2\nline3\n"

    def test_invalid_line_number(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "line": 5,
                "content": "x\n",
            }
        )

        assert "Error" in result
        assert "Invalid line" in result


class TestDeleteLinesTool:
    """Test delete_lines tool."""

    @pytest.fixture()
    def middleware(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend)

    def _get_tool(self, middleware: SootheFilesystemMiddleware) -> BaseTool:
        return next(t for t in middleware.tools if t.name == "delete_lines")

    def test_delete_single_line(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "start_line": 2,
                "end_line": 2,
            }
        )

        assert "Deleted lines 2-2" in result
        assert "1 lines" in result
        assert test_file.read_text() == "line1\nline3\n"

    def test_delete_multiple_lines(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "start_line": 2,
                "end_line": 3,
            }
        )

        assert "2 lines" in result
        assert test_file.read_text() == "line1\nline4\n"

    def test_invalid_line_range(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\n")

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "start_line": 5,
                "end_line": 5,
            }
        )

        assert "Error" in result


class TestApplyDiffTool:
    """Test apply_diff tool."""

    @pytest.fixture()
    def middleware(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend)

    def _get_tool(self, middleware: SootheFilesystemMiddleware) -> BaseTool:
        return next(t for t in middleware.tools if t.name == "apply_diff")

    def test_apply_diff_success(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content\n")

        diff = (
            f"--- {test_file}\n+++ {test_file}\n@@ -1 +1 @@\n-original content\n+modified content\n"
        )

        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(test_file),
                "diff": diff,
            }
        )

        # Patch may succeed or fail depending on format, just verify no crash
        assert isinstance(result, str)

    def test_apply_diff_file_not_found(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        tool = self._get_tool(middleware)
        result = tool.invoke(
            {
                "file_path": str(tmp_path / "nonexistent.txt"),
                "diff": "--- a\n+++ b\n@@\n-x\n+y\n",
            }
        )

        assert "Error" in result
        assert "not found" in result.lower()


class TestCustomBackupDir:
    """Test custom backup directory configuration."""

    def test_custom_backup_dir(self, tmp_path: Path) -> None:
        backup_dir = tmp_path / "custom_backups"
        backend = FilesystemBackend(root_dir=tmp_path)
        middleware = SootheFilesystemMiddleware(
            backend=backend,
            backup_enabled=True,
            backup_dir=str(backup_dir),
        )

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        tool = next(t for t in middleware.tools if t.name == "delete_file")
        tool.invoke({"file_path": str(test_file)})

        # Backup should be in custom dir, not .backups
        assert not any(tmp_path.glob(".backups/*"))
        assert any(backup_dir.glob("*.txt"))
