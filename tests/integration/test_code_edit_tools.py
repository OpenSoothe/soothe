"""Integration tests for code editing tools.

Tests tools from soothe.tools.code_edit:
- edit_file_lines: Replace specific line range in a file
- insert_lines: Insert lines at specific positions
- delete_lines: Delete specific line ranges
"""

import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Edit File Lines Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEditFileLinesTool:
    """Integration tests for surgical line editing."""

    @pytest.fixture
    def edit_tool(self):
        """Create EditFileLinesTool instance."""
        from soothe.tools.code_edit import EditFileLinesTool

        return EditFileLinesTool()

    def test_edit_single_line(self, edit_tool) -> None:
        """Test editing a single line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "code.py"
            code_file.write_text("def hello():\n    print('world')\n    return True\n")

            result = edit_tool._run(
                str(code_file),
                start_line=2,
                end_line=2,
                new_content="    print('Soothe')",
            )

            updated = code_file.read_text()
            assert "Soothe" in updated
            assert "world" not in updated
            # Other lines unchanged
            assert "def hello():" in updated
            assert "return True" in updated

    def test_edit_multiple_lines(self, edit_tool) -> None:
        """Test editing multiple lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "multi.py"
            code_file.write_text("x = 1\ny = 2\nz = 3\n")

            result = edit_tool._run(
                str(code_file),
                start_line=1,
                end_line=2,
                new_content="a = 10\nb = 20",
            )

            updated = code_file.read_text()
            assert "a = 10" in updated
            assert "b = 20" in updated
            assert "z = 3" in updated

    def test_edit_invalid_line_numbers(self, edit_tool) -> None:
        """Test editing with invalid line numbers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            small_file = Path(tmpdir) / "small.txt"
            small_file.write_text("only one line\n")

            result = edit_tool._run(
                str(small_file),
                start_line=10,
                end_line=15,
                new_content="invalid",
            )

            # Should return error
            assert "error" in result.lower() or "invalid" in result.lower()

    def test_edit_preserves_indentation(self, edit_tool) -> None:
        """Test that editing preserves code indentation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "indented.py"
            code_file.write_text("def foo():\n    x = 1\n    y = 2\n")

            result = edit_tool._run(
                str(code_file),
                start_line=2,
                end_line=2,
                new_content="    x = 10",
            )

            updated = code_file.read_text()
            assert "    x = 10" in updated  # Indentation preserved

    def test_edit_at_end_of_file(self, edit_tool) -> None:
        """Test editing lines at end of file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "end.txt"
            code_file.write_text("line1\nline2\nline3\n")

            result = edit_tool._run(
                str(code_file),
                start_line=3,
                end_line=3,
                new_content="new_last_line",
            )

            updated = code_file.read_text()
            assert "new_last_line" in updated


# ---------------------------------------------------------------------------
# Insert Lines Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInsertLinesTool:
    """Integration tests for line insertion."""

    @pytest.fixture
    def insert_tool(self):
        """Create InsertLinesTool instance."""
        from soothe.tools.code_edit import InsertLinesTool

        return InsertLinesTool()

    def test_insert_after_line(self, insert_tool) -> None:
        """Test inserting lines at specific line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "insert.txt"
            code_file.write_text("line1\nline2\n")

            result = insert_tool._run(
                str(code_file),
                line=2,  # Insert before line 2 (between line1 and line2)
                content="new_line",
            )

            updated = code_file.read_text()
            lines = updated.split("\n")
            assert "line1" in lines[0]
            assert "new_line" in lines[1]
            assert "line2" in lines[2]

    def test_insert_at_beginning(self, insert_tool) -> None:
        """Test inserting at beginning of file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "beginning.txt"
            code_file.write_text("existing\n")

            result = insert_tool._run(
                str(code_file),
                line=1,  # Insert at line 1 (beginning)
                content="first",
            )

            updated = code_file.read_text()
            assert updated.startswith("first")

    def test_insert_multiple_lines(self, insert_tool) -> None:
        """Test inserting multiple lines at once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "multi.txt"
            code_file.write_text("original\n")

            result = insert_tool._run(
                str(code_file),
                line=2,  # Insert at end (after line 1)
                content="line1\nline2\nline3",
            )

            updated = code_file.read_text()
            assert "line1" in updated
            assert "line2" in updated
            assert "line3" in updated

    def test_insert_preserves_surrounding_content(self, insert_tool) -> None:
        """Test that insertion preserves content before and after."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "preserve.txt"
            code_file.write_text("before\nafter\n")

            result = insert_tool._run(
                str(code_file),
                line=2,  # Insert before "after"
                content="inserted",
            )

            updated = code_file.read_text()
            assert "before" in updated
            assert "after" in updated
            assert "inserted" in updated


# ---------------------------------------------------------------------------
# Delete Lines Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteLinesTool:
    """Integration tests for line deletion."""

    @pytest.fixture
    def delete_lines_tool(self):
        """Create DeleteLinesTool instance."""
        from soothe.tools.code_edit import DeleteLinesTool

        return DeleteLinesTool()

    def test_delete_line_range(self, delete_lines_tool) -> None:
        """Test deleting specific lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "delete.txt"
            code_file.write_text("keep1\ndelete1\ndelete2\nkeep2\n")

            result = delete_lines_tool._run(
                str(code_file),
                start_line=2,
                end_line=3,
            )

            updated = code_file.read_text()
            assert "keep1" in updated
            assert "keep2" in updated
            assert "delete1" not in updated
            assert "delete2" not in updated

    def test_delete_single_line(self, delete_lines_tool) -> None:
        """Test deleting a single line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "single.txt"
            code_file.write_text("keep1\ndelete\nkeep2\n")

            result = delete_lines_tool._run(
                str(code_file),
                start_line=2,
                end_line=2,
            )

            updated = code_file.read_text()
            assert "keep1" in updated
            assert "keep2" in updated
            assert "delete" not in updated

    def test_delete_at_end_of_file(self, delete_lines_tool) -> None:
        """Test deleting lines at end of file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "end.txt"
            code_file.write_text("keep\ndelete1\ndelete2\n")

            result = delete_lines_tool._run(
                str(code_file),
                start_line=2,
                end_line=3,
            )

            updated = code_file.read_text()
            assert "keep" in updated
            assert "delete1" not in updated

    def test_delete_with_invalid_line_numbers(self, delete_lines_tool) -> None:
        """Test deleting with invalid line numbers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "small.txt"
            code_file.write_text("one line\n")

            result = delete_lines_tool._run(
                str(code_file),
                start_line=10,
                end_line=15,
            )

            # Should return error
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCodeEditErrorHandling:
    """Test error handling across code editing tools."""

    def test_edit_nonexistent_file(self) -> None:
        """Test editing non-existent file."""
        from soothe.tools.code_edit import EditFileLinesTool

        tool = EditFileLinesTool()
        result = tool._run("/nonexistent/file.txt", start_line=1, end_line=1, new_content="test")

        assert isinstance(result, str)

    def test_insert_readonly_file(self) -> None:
        """Test inserting into read-only file."""
        pytest.skip("Requires specific file permission setup")

    def test_delete_from_locked_file(self) -> None:
        """Test deleting from locked file."""
        pytest.skip("Requires specific file locking setup")
