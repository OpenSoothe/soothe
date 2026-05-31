"""Example usage of LangChainAdapter.

This example demonstrates how to use the LangChainAdapter to wrap
a UnifiedFilesystem for LangChain compatibility.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from soothe.core.filesystem import (
    LangChainAdapter,
    LocalFilesystem,
    create_filesystem,
)


def basic_usage():
    """Demonstrate basic LangChainAdapter usage."""
    print("=== Basic Usage ===\n")

    # Create a temporary workspace
    with tempfile.TemporaryDirectory() as workspace:
        # Create underlying filesystem
        underlying = LocalFilesystem(workspace, virtual_mode=True)

        # Wrap with LangChain adapter
        fs = LangChainAdapter(underlying)

        print(f"Workspace: {fs.workspace}")
        print(f"Root dir (LangChain alias): {fs.root_dir}")
        print(f"Virtual mode: {fs.virtual_mode}")
        print(f"Has LangChain tools: {fs.has_langchain_tools}\n")

        # Write a file
        result = fs.write("hello.txt", "Hello, World!")
        print(f"Wrote {result.bytes_written} bytes to {result.path}")

        # Read the file
        read_result = fs.read("hello.txt")
        print(f"Read content: {read_result.content}")

        # List directory
        entries = fs.ls(".")
        print(f"Directory contents: {entries}")

        # Get file info
        info = fs.info("hello.txt")
        print(f"File size: {info.size} bytes")
        print(f"Is directory: {info.is_dir}")


def using_factory():
    """Demonstrate using the factory function with LangChainAdapter."""
    print("\n=== Using Factory ===\n")

    with tempfile.TemporaryDirectory() as workspace:
        # Create filesystem using factory
        underlying = create_filesystem(workspace, virtual_mode=True)

        # Wrap with adapter
        fs = LangChainAdapter(underlying)

        # Create some files
        fs.write("config.json", '{"name": "example", "version": "1.0"}')
        fs.write("readme.md", "# Example\n\nThis is an example.")

        # Search for files
        glob_result = fs.glob("*.json")
        print(f"JSON files: {glob_result.matches}")

        # Search content
        grep_result = fs.grep("example")
        print(f"Files containing 'example': {grep_result}")


def edit_operations():
    """Demonstrate edit operations."""
    print("\n=== Edit Operations ===\n")

    with tempfile.TemporaryDirectory() as workspace:
        underlying = LocalFilesystem(workspace, virtual_mode=True)
        fs = LangChainAdapter(underlying)

        # Create initial file
        fs.write("config.txt", "database = localhost\nport = 5432")
        print("Initial content:")
        print(fs.read("config.txt").content)

        # Edit file
        fs.edit("config.txt", "localhost", "db.example.com")
        print("\nAfter edit:")
        print(fs.read("config.txt").content)

        # Edit specific lines
        fs.edit_lines("config.txt", 1, 2, "host = db.example.com\nport = 5432")
        print("\nAfter line edit:")
        print(fs.read("config.txt").content)


def directory_operations():
    """Demonstrate directory operations."""
    print("\n=== Directory Operations ===\n")

    with tempfile.TemporaryDirectory() as workspace:
        underlying = LocalFilesystem(workspace, virtual_mode=True)
        fs = LangChainAdapter(underlying)

        # Create nested directories
        fs.mkdir("src/components", recursive=True)
        fs.mkdir("src/utils", recursive=True)

        # Create files in directories
        fs.write("src/components/Button.tsx", "export const Button = () => {}")
        fs.write("src/utils/helpers.ts", "export const helper = () => {}")

        # List with info
        entries = fs.ls("src", include_info=True)
        print("Source directory contents:")
        for entry in entries:
            print(f"  {entry.path} (dir: {entry.is_dir})")

        # Copy directory
        fs.copy("src/components/Button.tsx", "src/components/Input.tsx")
        print("\nAfter copying Button.tsx to Input.tsx:")
        entries = fs.ls("src/components")
        print(f"  Components: {entries}")


def advanced_search():
    """Demonstrate advanced search capabilities."""
    print("\n=== Advanced Search ===\n")

    with tempfile.TemporaryDirectory() as workspace:
        underlying = LocalFilesystem(workspace, virtual_mode=True)
        fs = LangChainAdapter(underlying)

        # Create various files
        fs.write("app.py", "import flask\napp = Flask(__name__)")
        fs.write("utils.py", "def helper():\n    return True")
        fs.write("test_app.py", "import pytest\ndef test_app(): pass")
        fs.write("README.md", "# Project\n\nA Python project.")

        # Glob patterns
        py_files = fs.glob("**/*.py")
        print(f"Python files: {py_files.matches}")

        # Grep for patterns
        import_files = fs.grep("^import", output_mode="content")
        print(f"\nImport statements found in:")
        if isinstance(import_files, list):
            for file in import_files:
                print(f"  - {file}")


def context_manager():
    """Demonstrate context manager usage."""
    print("\n=== Context Manager ===\n")

    with tempfile.TemporaryDirectory() as workspace:
        underlying = LocalFilesystem(workspace, virtual_mode=True)

        # Use as context manager
        with LangChainAdapter(underlying) as fs:
            fs.write("temp.txt", "temporary content")
            print(f"File exists in context: {fs.exists('temp.txt')}")
            print(f"File content: {fs.read('temp.txt').content}")

        # File still exists after context (adapter doesn't delete)
        print(f"File exists after context: {underlying.exists('temp.txt')}")


def show_representation():
    """Demonstrate string representation."""
    print("\n=== Representation ===\n")

    with tempfile.TemporaryDirectory() as workspace:
        underlying = LocalFilesystem(workspace, virtual_mode=True)
        fs = LangChainAdapter(underlying)

        print(f"Adapter repr: {repr(fs)}")
        print(f"Adapter str: {str(fs)}")


def main():
    """Run all examples."""
    basic_usage()
    using_factory()
    edit_operations()
    directory_operations()
    advanced_search()
    context_manager()
    show_representation()

    print("\n=== All examples completed! ===")


if __name__ == "__main__":
    main()
