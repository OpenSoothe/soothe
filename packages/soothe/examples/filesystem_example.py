"""
UnifiedFilesystem Usage Examples

This example demonstrates the UnifiedFilesystem interface with
various operations and security features.
"""

from __future__ import annotations

import tempfile

from soothe.core.filesystem import (
    DirectoryNotEmptyError,
    LocalFilesystem,
    PathNotFoundError,
    PathTraversalError,
)


def example_basic_operations():
    """Demonstrate basic file operations."""
    print("=== Basic File Operations ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create filesystem instance
        fs = LocalFilesystem(workspace=tmpdir, virtual_mode=True)

        # Write a file
        result = fs.write("hello.txt", "Hello, World!")
        print(f"Created: {result.path}")
        print(f"Bytes written: {result.bytes_written}")

        # Read the file
        read_result = fs.read("hello.txt")
        print(f"Content: {read_result.content}")
        print(f"Is binary: {read_result.is_binary}")

        # Check file info
        info = fs.info("hello.txt")
        print(f"Size: {info.size} bytes")
        print(f"Modified: {info.modified_at}")

        # List directory
        entries = fs.ls(".")
        print(f"Directory entries: {entries}")


def example_editing():
    """Demonstrate file editing operations."""
    print("\n=== File Editing ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        fs = LocalFilesystem(workspace=tmpdir)

        # Create a file with multiple lines
        content = """Line 1
Line 2
Line 3
Line 4
Line 5"""
        fs.write("example.txt", content)

        # Edit by string replacement
        edit_result = fs.edit("example.txt", "Line 3", "Modified Line 3")
        print(f"Edited {edit_result.lines_changed} lines")
        print(f"Old hash: {edit_result.old_hash}")
        print(f"New hash: {edit_result.new_hash}")

        # Edit specific lines
        fs.edit_lines("example.txt", 4, 5, "New Line 4\nNew Line 5")

        # Insert at specific line
        fs.insert_lines("example.txt", 2, "Inserted Line")

        # Delete lines
        fs.delete_lines("example.txt", 3, 3)

        # Show final content
        final = fs.read("example.txt")
        print("Final content:")
        print(final.content)


def example_directories():
    """Demonstrate directory operations."""
    print("\n=== Directory Operations ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        fs = LocalFilesystem(workspace=tmpdir)

        # Create nested directories
        fs.mkdir("project/src", recursive=True)
        fs.mkdir("project/tests")

        # Create files in directories
        fs.write("project/src/main.py", "print('Hello')")
        fs.write("project/src/utils.py", "# Utils")
        fs.write("project/tests/test_main.py", "# Tests")

        # List with info
        entries = fs.ls("project", include_info=True)
        print("Project structure:")
        for entry in entries:
            type_str = "DIR" if entry.is_dir else "FILE"
            print(f"  [{type_str}] {entry.path}")

        # Copy directory
        fs.copy("project/src", "project/src_backup", recursive=True)
        print("Copied src to src_backup")

        # Move directory
        fs.move("project/tests", "project/test_suite")
        print("Moved tests to test_suite")

        # Remove directory recursively
        fs.rmdir("project/src_backup", recursive=True)
        print("Removed src_backup")


def example_security():
    """Demonstrate security features."""
    print("\n=== Security Features ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        fs = LocalFilesystem(workspace=tmpdir, virtual_mode=True)

        # Create a file
        fs.write("safe.txt", "Safe content")

        # Try path traversal
        print("Attempting path traversal...")
        try:
            fs.read("../etc/passwd")
        except PathTraversalError as e:
            print(f"Blocked: {e}")
            print(f"Attempted path: {e.attempted_path}")

        # Try null bytes
        print("\nAttempting null byte injection...")
        try:
            fs.read("file\x00.txt")
        except Exception as e:
            print(f"Blocked: {e}")

        # Try home directory
        print("\nAttempting home directory access...")
        try:
            fs.read("~/.bashrc")
        except Exception as e:
            print(f"Blocked: {e}")

        # Virtual mode: absolute paths become workspace-relative
        print("\nVirtual mode path resolution:")
        result = fs.read("/safe.txt")  # Resolves to workspace/safe.txt
        print(f"Read via virtual absolute path: {result.content}")


def example_backup():
    """Demonstrate backup functionality."""
    print("\n=== Backup Functionality ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        fs = LocalFilesystem(workspace=tmpdir)

        # Create and modify file with backup
        fs.write("important.txt", "Version 1")
        print("Created important.txt with 'Version 1'")

        # Update with backup
        result = fs.write("important.txt", "Version 2", backup=True)
        print("Updated to 'Version 2'")
        print(f"Backup created at: {result.backup_path}")

        # Update again
        result = fs.write("important.txt", "Version 3", backup=True)
        print("Updated to 'Version 3'")
        print(f"Backup created at: {result.backup_path}")

        # Delete with backup
        result = fs.delete("important.txt", backup=True)
        print("Deleted file")
        print(f"Final backup at: {result.backup_path}")

        # List backups
        backups = fs.ls(".backups")
        print(f"\nBackup files: {backups}")


def example_search():
    """Demonstrate search operations."""
    print("\n=== Search Operations ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        fs = LocalFilesystem(workspace=tmpdir)

        # Create test files
        fs.write("src/main.py", "def hello():\n    print('Hello')")
        fs.write("src/utils.py", "def helper():\n    pass")
        fs.write("tests/test_main.py", "def test_hello():\n    assert True")
        fs.write("README.md", "# Project\nThis is a test.")

        # Glob search
        print("Python files:")
        glob_result = fs.glob("**/*.py")
        for match in glob_result.matches:
            print(f"  - {match}")

        # Grep search
        print("\nFiles containing 'def':")
        grep_result = fs.grep("^def", output_mode="files_with_matches")
        for file in grep_result:
            print(f"  - {file}")

        # Grep with content
        print("\nDetailed grep results:")
        detailed = fs.grep("def ", output_mode="content")
        for match in detailed.matches:
            print(f"  {match.path}:{match.line_number}: {match.line_content.strip()}")


def example_error_handling():
    """Demonstrate error handling."""
    print("\n=== Error Handling ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        fs = LocalFilesystem(workspace=tmpdir)

        # File not found
        print("File not found:")
        try:
            fs.read("nonexistent.txt")
        except PathNotFoundError as e:
            print(f"  Caught: {e}")

        # Directory not empty
        print("\nDirectory not empty:")
        fs.mkdir("nonempty")
        fs.write("nonempty/file.txt", "content")
        try:
            fs.rmdir("nonempty", recursive=False)
        except DirectoryNotEmptyError as e:
            print(f"  Caught: {e}")

        # Invalid line range
        print("\nInvalid line range:")
        fs.write("short.txt", "Line 1\nLine 2")
        try:
            fs.edit_lines("short.txt", 5, 10, "New content")
        except Exception as e:
            print(f"  Caught: {e}")


def example_async():
    """Demonstrate async operations."""
    print("\n=== Async Operations ===")

    import asyncio

    async def async_demo():
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = LocalFilesystem(workspace=tmpdir)

            # Async write
            await fs.awrite("async.txt", "Async content")
            print("Created file asynchronously")

            # Async read
            result = await fs.aread("async.txt")
            print(f"Read asynchronously: {result.content}")

            # Async list
            entries = await fs.als(".")
            print(f"Listed asynchronously: {entries}")

    asyncio.run(async_demo())


def main():
    """Run all examples."""
    example_basic_operations()
    example_editing()
    example_directories()
    example_security()
    example_backup()
    example_search()
    example_error_handling()
    example_async()

    print("\n=== All Examples Complete ===")


if __name__ == "__main__":
    main()
