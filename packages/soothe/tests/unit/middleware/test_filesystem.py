"""Unit tests for SootheFilesystemMiddleware."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel
from soothe_deepagents.backends.filesystem import FilesystemBackend

from soothe.middleware.filesystem import (
    ApplyDiffSchema,
    SootheFilesystemMiddleware,
    coerce_provider_safe_tool_message,
)


class TestCoerceProviderSafeToolMessage:
    """read_file PDF/audio blocks must not reach OpenAI-compatible chat APIs."""

    def test_leaves_text_tool_message_unchanged(self) -> None:
        msg = ToolMessage(content="hello", tool_call_id="t1", name="read_file")
        assert coerce_provider_safe_tool_message(msg) is msg

    def test_converts_file_block_to_text(self) -> None:
        msg = ToolMessage(
            content=[{"type": "file", "base64": "abc", "mime_type": "application/pdf"}],
            tool_call_id="t1",
            name="read_file",
            additional_kwargs={"read_file_path": "/docs/paper.pdf"},
        )
        out = coerce_provider_safe_tool_message(msg)
        assert out is not msg
        assert out.content == [
            {
                "type": "text",
                "text": (
                    "System reminder: read_file returned a document or media file"
                    " at /docs/paper.pdf (block type='file', mime_type=application/pdf)"
                    " that cannot be sent inline to this chat model. Use goal attachment"
                    " text, run_command (e.g. pdftotext or a PDF parser), or paginated"
                    " text reads on extracted files instead of read_file on this path."
                ),
            }
        ]

    def test_preserves_image_block(self) -> None:
        block = {
            "type": "image",
            "base64": "abc",
            "mime_type": "image/png",
        }
        msg = ToolMessage(
            content=[block],
            tool_call_id="t1",
            name="read_file",
        )
        assert coerce_provider_safe_tool_message(msg) is msg


class TestSootheFilesystemMiddlewareSchemas:
    """Test soothe-specific tool schemas."""

    def test_apply_diff_schema_is_basemodel(self) -> None:
        assert issubclass(ApplyDiffSchema, BaseModel)

    def test_schema_fields_have_descriptions(self) -> None:
        """All schema fields must have descriptions (soothe_deepagents pattern)."""
        for schema_cls in [
            ApplyDiffSchema,
        ]:
            for field_name, field_info in schema_cls.model_fields.items():
                assert field_info.description, (
                    f"{schema_cls.__name__}.{field_name} missing description"
                )


def _tool_output_text(result: object) -> str:
    if isinstance(result, ToolMessage):
        return str(result.content)
    return str(result)


def _runtime(tool_call_id: str = "tc") -> ToolRuntime:
    return ToolRuntime(
        state={"messages": [], "files": {}},
        context=None,
        tool_call_id=tool_call_id,
        store=None,
        stream_writer=lambda _: None,
        config={},
    )


def _invoke_tool(tool: BaseTool, args: dict[str, object], *, tool_call_id: str = "tc") -> object:
    try:
        return tool.invoke(args)
    except TypeError as exc:
        if "missing 1 required positional argument: 'runtime'" not in str(exc):
            raise
        return tool.func(runtime=_runtime(tool_call_id), **args)


class TestSootheFilesystemMiddlewareToolCreation:
    """Test tool creation follows soothe_deepagents pattern."""

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
        ]
        for name in inherited_tool_names:
            assert any(t.name == name for t in middleware.tools), f"Missing inherited tool: {name}"

    def test_adds_surgical_tools(self, middleware: SootheFilesystemMiddleware) -> None:
        """Verify all Soothe surgical tools exist."""
        soothe_tool_names = [
            "delete",
            "file_info",
            "edit_lines",
            "insert_lines",
            "delete_lines",
            "apply_diff",
        ]
        for name in soothe_tool_names:
            assert any(t.name == name for t in middleware.tools), f"Missing surgical tool: {name}"

    def test_tools_have_args_schema(self, middleware: SootheFilesystemMiddleware) -> None:
        """All tools must have args_schema (soothe_deepagents pattern)."""
        for tool in middleware.tools:
            if hasattr(tool, "args_schema"):
                assert tool.args_schema is not None, f"Tool {tool.name} missing args_schema"
                assert issubclass(tool.args_schema, BaseModel), (
                    f"Tool {tool.name} schema not BaseModel"
                )


class TestDeleteTool:
    """Test delete tool with backup support."""

    @pytest.fixture()
    def middleware(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend, backup_enabled=True)

    @pytest.fixture()
    def middleware_no_backup(self, tmp_path: Path) -> SootheFilesystemMiddleware:
        backend = FilesystemBackend(root_dir=tmp_path)
        return SootheFilesystemMiddleware(backend=backend, backup_enabled=False)

    def _get_tool(self, middleware: SootheFilesystemMiddleware, name: str = "delete") -> BaseTool:
        return next(t for t in middleware.tools if t.name == name)

    def test_delete_with_backup(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        tool = self._get_tool(middleware)
        result = _invoke_tool(tool, {"file_path": str(test_file), "backup": True})
        text = _tool_output_text(result)

        assert "Deleted" in text
        assert "backup:" in text
        assert not test_file.exists()
        assert any(tmp_path.glob(".backups/*"))

    def test_delete_without_backup(
        self, tmp_path: Path, middleware_no_backup: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        tool = self._get_tool(middleware_no_backup)
        result = _invoke_tool(tool, {"file_path": str(test_file)})
        text = _tool_output_text(result)

        assert "Deleted" in text
        assert "backup:" not in text
        assert not test_file.exists()
        assert not any(tmp_path.glob(".backups/*"))

    def test_delete_nonexistent_file(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        tool = self._get_tool(middleware)
        result = _invoke_tool(tool, {"file_path": str(tmp_path / "nonexistent.txt")})
        text = _tool_output_text(result)

        assert "Error" in text
        assert "not found" in text.lower()

    def test_delete_directory_recursively(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_dir = tmp_path / "mydir"
        test_dir.mkdir()
        (test_dir / "nested.txt").write_text("x")

        tool = self._get_tool(middleware)
        result = _invoke_tool(tool, {"file_path": str(test_dir)})
        text = _tool_output_text(result)

        assert "Deleted" in text
        assert not test_dir.exists()

    def test_backup_file_naming(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        test_file = tmp_path / "myfile.txt"
        test_file.write_text("content")

        tool = self._get_tool(middleware)
        _invoke_tool(tool, {"file_path": str(test_file), "backup": True})

        backup_files = list(tmp_path.glob(".backups/*"))
        assert len(backup_files) == 1

        # Check backup naming format: original_name.YYYYMMDD_HHMMSS.bak
        backup_name = backup_files[0].name
        assert backup_name.startswith("myfile.txt.")
        assert backup_name.endswith(".bak")

        # Verify timestamp is parseable
        timestamp_part = backup_name.replace("myfile.txt.", "").replace(".bak", "")
        datetime.strptime(timestamp_part, "%Y%m%d_%H%M%S")


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
        result = _invoke_tool(
            tool,
            {
                "file_path": str(test_file),
                "diff": diff,
            },
            tool_call_id="ad_ok",
        )
        text = _tool_output_text(result)

        assert "Applied diff" in text
        assert test_file.read_text() == "modified content\n"

    def test_apply_diff_basic_unified_diff_format(
        self,
        tmp_path: Path,
        middleware: SootheFilesystemMiddleware,
    ) -> None:
        test_file = tmp_path / "fallback.txt"
        test_file.write_text("old line\n")
        diff = (
            "--- fallback.txt\n"
            "+++ fallback.txt\n"
            "@@ -1 +1 @@\n"
            "-old line\n"
            "+new line\n"
        )

        tool = self._get_tool(middleware)
        result = _invoke_tool(
            tool,
            {"file_path": str(test_file), "diff": diff},
            tool_call_id="ad_basic",
        )
        text = _tool_output_text(result)

        assert "Applied diff" in text
        assert test_file.read_text() == "new line\n"

    def test_apply_diff_file_not_found(
        self, tmp_path: Path, middleware: SootheFilesystemMiddleware
    ) -> None:
        tool = self._get_tool(middleware)
        result = _invoke_tool(
            tool,
            {
                "file_path": str(tmp_path / "nonexistent.txt"),
                "diff": "--- a\n+++ b\n@@\n-x\n+y\n",
            },
            tool_call_id="ad_missing",
        )
        text = _tool_output_text(result)

        assert "Error" in text
        assert "not found" in text.lower()

    def test_apply_diff_invalid_unified_diff_returns_error(
        self,
        tmp_path: Path,
        middleware: SootheFilesystemMiddleware,
    ) -> None:
        test_file = tmp_path / "bad_diff.txt"
        test_file.write_text("line\n")

        tool = self._get_tool(middleware)
        result = _invoke_tool(
            tool,
            {"file_path": str(test_file), "diff": "invalid diff"},
            tool_call_id="ad_bad",
        )
        text = _tool_output_text(result)

        assert "Failed to apply diff with Python fallback" in text


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

        tool = next(t for t in middleware.tools if t.name == "delete")
        _invoke_tool(
            tool,
            {
                "file_path": str(test_file),
                "backup": True,
                "backup_dir": str(backup_dir),
            },
        )

        # Backup should be in custom dir, not .backups
        assert not any(tmp_path.glob(".backups/*"))
        assert any(backup_dir.glob("*"))
