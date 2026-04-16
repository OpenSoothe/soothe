"""Tests for surgical code editing tools (RFC-0016 Phase 2)."""

import tempfile
from pathlib import Path

from soothe.tools.code_edit import (
    ApplyDiffTool,
    DeleteLinesTool,
    EditFileLinesTool,
    InsertLinesTool,
)


class TestEditFileLinesTool:
    """Tests for edit_file_lines tool."""

    def test_replace_single_line(self):
        """Test replacing a single line."""
        tool = EditFileLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\n")
            f.flush()

            result = tool._run(path=f.name, start_line=2, end_line=2, new_content="modified_line2")

            assert "Updated" in result
            assert "1 removed, 1 added" in result

            # Verify change
            with open(f.name) as rf:
                content = rf.read()
                assert "modified_line2" in content
                assert "line1" in content
                assert "line3" in content

            Path(f.name).unlink()

    def test_replace_multiple_lines(self):
        """Test replacing multiple lines."""
        tool = EditFileLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")
            f.flush()

            result = tool._run(
                path=f.name, start_line=2, end_line=4, new_content="new2\nnew3\nnew4"
            )

            assert "Updated" in result
            assert "3 removed, 3 added" in result

            # Verify change
            with open(f.name) as rf:
                content = rf.read()
                assert "line1" in content
                assert "new2" in content
                assert "new3" in content
                assert "new4" in content
                assert "line5" in content

            Path(f.name).unlink()

    def test_replace_with_different_line_count(self):
        """Test replacing with different number of lines."""
        tool = EditFileLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\n")
            f.flush()

            # Replace 2 lines with 4 lines
            result = tool._run(
                path=f.name, start_line=2, end_line=3, new_content="new1\nnew2\nnew3\nnew4"
            )

            assert "2 removed, 4 added" in result

            with open(f.name) as rf:
                lines = rf.readlines()
                assert len(lines) == 5  # 1 original + 4 new

            Path(f.name).unlink()

    def test_invalid_line_range(self):
        """Test error handling for invalid line range."""
        tool = EditFileLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\n")
            f.flush()

            result = tool._run(path=f.name, start_line=5, end_line=6, new_content="x")
            assert "Error" in result
            assert "Invalid start_line" in result

            result = tool._run(path=f.name, start_line=1, end_line=5, new_content="x")
            assert "Error" in result
            assert "Invalid end_line" in result

            Path(f.name).unlink()

    def test_file_not_found(self):
        """Test error handling for missing file."""
        tool = EditFileLinesTool()

        result = tool._run(path="/nonexistent/file.py", start_line=1, end_line=1, new_content="x")
        assert "Error" in result
        assert "File not found" in result


class TestInsertLinesTool:
    """Tests for insert_lines tool."""

    def test_insert_at_beginning(self):
        """Test inserting at beginning of file."""
        tool = InsertLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\n")
            f.flush()

            tool._run(path=f.name, line=1, content="new_first")

            with open(f.name) as rf:
                lines = rf.readlines()
                assert lines[0] == "new_first\n"
                assert lines[1] == "line1\n"

            Path(f.name).unlink()

    def test_insert_in_middle(self):
        """Test inserting in middle of file."""
        tool = InsertLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\n")
            f.flush()

            tool._run(path=f.name, line=2, content="inserted")

            with open(f.name) as rf:
                content = rf.read()
                assert content == "line1\ninserted\nline2\nline3\n"

            Path(f.name).unlink()

    def test_insert_at_end(self):
        """Test appending at end of file."""
        tool = InsertLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\n")
            f.flush()

            tool._run(path=f.name, line=3, content="new_last")

            with open(f.name) as rf:
                content = rf.read()
                assert content == "line1\nline2\nnew_last\n"

            Path(f.name).unlink()


class TestDeleteLinesTool:
    """Tests for delete_lines tool."""

    def test_delete_single_line(self):
        """Test deleting a single line."""
        tool = DeleteLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\n")
            f.flush()

            tool._run(path=f.name, start_line=2, end_line=2)

            with open(f.name) as rf:
                content = rf.read()
                assert content == "line1\nline3\n"

            Path(f.name).unlink()

    def test_delete_multiple_lines(self):
        """Test deleting multiple lines."""
        tool = DeleteLinesTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")
            f.flush()

            tool._run(path=f.name, start_line=2, end_line=4)

            with open(f.name) as rf:
                content = rf.read()
                assert content == "line1\nline5\n"

            Path(f.name).unlink()


class TestApplyDiffTool:
    """Tests for apply_diff tool."""

    def test_apply_simple_diff(self):
        """Test applying a simple diff."""
        tool = ApplyDiffTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("def hello():\n    print('world')\n")
            f.flush()

            diff = f"""--- {f.name}
+++ {f.name}
@@ -1,2 +1,2 @@
 def hello():
-    print('world')
+    print('hello')
"""

            tool._run(path=f.name, diff=diff)

            with open(f.name) as rf:
                content = rf.read()
                assert "print('hello')" in content
                assert "print('world')" not in content

            Path(f.name).unlink()

    def test_apply_diff_file_not_found(self):
        """Test applying diff to non-existent file."""
        tool = ApplyDiffTool()

        diff = "--- /nonexistent/file.py\n+++ /nonexistent/file.py\n@@ -1 +1 @@\n-old\n+new\n"
        result = tool._run(path="/nonexistent/file.py", diff=diff)

        assert "Error" in result
        assert "File not found" in result
