"""Tests for Document tools functionality."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from soothe.tools._internal.document import (
    DocumentQATool,
    ExtractTextTool,
    GetDocumentInfoTool,
    create_document_tools,
)


class TestDocumentQATool:
    """Test DocumentQATool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = DocumentQATool()

        assert tool.name == "document_qa"
        assert "document" in tool.description.lower()
        assert "question" in tool.description.lower()

    def test_parse_text_file(self) -> None:
        """Test parsing text file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test text file
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = DocumentQATool()

            result = tool._parse_document(str(file_path))

            assert "Hello, World!" in result

    def test_parse_json_file(self) -> None:
        """Test parsing JSON file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test JSON file
            import json

            file_path = Path(temp_dir) / "test.json"
            data = {"message": "Hello, World!"}
            file_path.write_text(json.dumps(data))

            tool = DocumentQATool()

            result = tool._parse_document(str(file_path))

            assert "message" in result
            assert "Hello, World!" in result

    def test_parse_markdown_file(self) -> None:
        """Test parsing markdown file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test markdown file
            file_path = Path(temp_dir) / "test.md"
            file_path.write_text("# Header\n\nContent here")

            tool = DocumentQATool()

            result = tool._parse_document(str(file_path))

            assert "# Header" in result
            assert "Content here" in result

    def test_parse_unsupported_format(self) -> None:
        """Test parsing unsupported format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file with unsupported extension
            file_path = Path(temp_dir) / "test.xyz"
            file_path.write_text("content")

            tool = DocumentQATool()

            with pytest.raises(ValueError, match="Unsupported"):
                tool._parse_document(str(file_path))

    def test_parse_pdf_without_pymupdf(self) -> None:
        """Test parsing PDF without PyMuPDF."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy PDF file
            file_path = Path(temp_dir) / "test.pdf"
            file_path.write_bytes(b"%PDF-1.4\ntest")

            tool = DocumentQATool()

            with patch.dict("sys.modules", {"fitz": None}), pytest.raises(ImportError, match="PyMuPDF"):
                tool._parse_document(str(file_path))


class TestExtractTextTool:
    """Test ExtractTextTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = ExtractTextTool()

        assert tool.name == "extract_text"
        assert "extract" in tool.description.lower()

    def test_extract_text_from_file(self) -> None:
        """Test extracting text from file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = ExtractTextTool()

            result = tool._run(str(file_path))

            assert "Hello, World!" in result

    def test_extract_text_with_size_limit(self) -> None:
        """Test extracting text with size limit."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("A" * 10000)

            tool = ExtractTextTool(text_limit=100)

            result = tool._run(str(file_path))

            assert len(result) <= 100 + len("\n\n... (document truncated)")


class TestGetDocumentInfoTool:
    """Test GetDocumentInfoTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = GetDocumentInfoTool()

        assert tool.name == "get_document_info"
        assert "info" in tool.description.lower() or "metadata" in tool.description.lower()

    def test_get_document_info(self) -> None:
        """Test getting document info."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Hello, World!")

            tool = GetDocumentInfoTool()

            result = tool._run(str(file_path))

            assert result["path"] == str(file_path)
            assert result["name"] == "test.txt"
            assert result["format"] == ".txt"
            assert "size_bytes" in result
            assert "size_kb" in result

    def test_get_nonexistent_document_info(self) -> None:
        """Test getting info for non-existent document."""
        tool = GetDocumentInfoTool()

        result = tool._run("/nonexistent/file.txt")

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_get_pdf_info(self) -> None:
        """Test getting PDF document info."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy PDF file
            file_path = Path(temp_dir) / "test.pdf"
            file_path.write_bytes(b"%PDF-1.4\ntest")

            tool = GetDocumentInfoTool()

            result = tool._run(str(file_path))

            assert result["format"] == ".pdf"
            # PDF-specific info might not be available without PyMuPDF
            if "page_count" in result:
                assert isinstance(result["page_count"], int)


class TestCreateDocumentTools:
    """Test factory function."""

    def test_create_document_tools(self) -> None:
        """Test factory function creates all tools."""
        tools = create_document_tools()

        assert len(tools) == 3

        tool_names = {tool.name for tool in tools}
        assert "document_qa" in tool_names
        assert "extract_text" in tool_names
        assert "get_document_info" in tool_names


class TestDocumentToolIntegration:
    """Integration tests for Document tools."""

    def test_document_qa_workflow(self) -> None:
        """Test complete document Q&A workflow."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test document
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("Python is a programming language. It was created by Guido van Rossum.")

            tool = DocumentQATool()

            # Mock LLM response
            with patch.object(tool, "_answer_question", return_value="Guido van Rossum"):
                result = tool._run(str(file_path), "Who created Python?")

                assert "Guido van Rossum" in result

    def test_document_summarization(self) -> None:
        """Test document summarization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test document
            file_path = Path(temp_dir) / "test.txt"
            file_path.write_text("This is a long document. It has many sentences. The content is diverse.")

            tool = DocumentQATool()

            # Mock LLM response
            with patch.object(tool, "_summarize_text", return_value="Summary of the document"):
                result = tool._run(str(file_path))

                assert "Summary" in result
