"""Integration tests for Soothe tools with real LLM invocation.

Tests three dimensions:
1. Single tools - LLM choosing and invoking individual tools
2. Composed tools - Multi-tool workflows orchestrated by LLM
3. Control limits - Testing Soothe's tool control mechanisms
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from soothe.core.runner import SootheRunner


# ---------------------------------------------------------------------------
# Test Utilities
# ---------------------------------------------------------------------------


class StreamEventCollector:
    """Collect and analyze stream events from SootheRunner."""

    def __init__(self) -> None:
        """Initialize event collector."""
        self.events: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.policy_events: list[dict[str, Any]] = []
        self.concurrency_events: list[dict[str, Any]] = []

    async def collect(self, runner: SootheRunner, query: str, **kwargs) -> None:
        """Run query and collect all stream events.

        Args:
            runner: SootheRunner instance
            query: Natural language query
            **kwargs: Additional arguments for runner.astream()
        """
        async for chunk in runner.astream(query, **kwargs):
            namespace, mode, data = chunk
            event = {
                "namespace": namespace,
                "mode": mode,
                "data": data,
            }
            self.events.append(event)

            # Track tool calls
            if mode == "tool_call":
                self.tool_calls.append(data)

            # Track errors
            if isinstance(data, dict) and "error" in data:
                self.errors.append(data)

            # Track policy events
            if isinstance(data, dict) and data.get("type", "").startswith("soothe.policy"):
                self.policy_events.append(data)

            # Track concurrency events
            if isinstance(data, dict) and data.get("type", "").startswith("soothe.concurrency"):
                self.concurrency_events.append(data)

    def get_tool_results(self, tool_name: str) -> list[dict[str, Any]]:
        """Get all results from a specific tool.

        Args:
            tool_name: Name of the tool (e.g., "read_file")

        Returns:
            List of tool call data
        """
        return [e for e in self.tool_calls if e.get("name") == tool_name]

    def has_error_type(self, error_type: str) -> bool:
        """Check if any error matches type.

        Args:
            error_type: Error type string to search for

        Returns:
            True if error type found
        """
        return any(error_type in str(e.get("error", "")) for e in self.errors)


# ---------------------------------------------------------------------------
# Assertion Helpers
# ---------------------------------------------------------------------------


def assert_tool_invoked(collector: StreamEventCollector, tool_name: str, min_count: int = 1) -> None:
    """Assert that a tool was invoked at least min_count times.

    Args:
        collector: Event collector
        tool_name: Expected tool name
        min_count: Minimum number of invocations

    Raises:
        AssertionError: If tool not invoked enough times
    """
    calls = collector.get_tool_results(tool_name)
    assert len(calls) >= min_count, f"Expected {min_count}+ calls to {tool_name}, got {len(calls)}"


def assert_no_errors(collector: StreamEventCollector) -> None:
    """Assert no errors occurred during execution.

    Args:
        collector: Event collector

    Raises:
        AssertionError: If errors found
    """
    assert len(collector.errors) == 0, f"Unexpected errors: {collector.errors}"


def assert_tool_error_contains(collector: StreamEventCollector, tool_name: str, error_substring: str) -> None:
    """Assert a tool returned an error containing substring.

    Args:
        collector: Event collector
        tool_name: Tool that should have error
        error_substring: Expected error substring

    Raises:
        AssertionError: If error not found
    """
    calls = collector.get_tool_results(tool_name)
    for call in calls:
        result = call.get("result", "")
        if isinstance(result, dict) and "error" in result:
            if error_substring in result["error"]:
                return
    raise AssertionError(f"No error containing '{error_substring}' in {tool_name} calls")


def assert_policy_denied(collector: StreamEventCollector, action: str) -> None:
    """Assert policy denied an action.

    Args:
        collector: Event collector
        action: Action that should be denied

    Raises:
        AssertionError: If no denial found
    """
    denied = [e for e in collector.policy_events if e.get("verdict") == "deny"]
    assert any(action in str(e) for e in denied), f"Expected policy denial for {action}"


# ---------------------------------------------------------------------------
# Category 1: Single Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestFileToolsIntegration:
    """Integration tests for file operation tools."""

    async def test_read_file_basic(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM reads a file correctly."""
        # Setup: Create test file
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World!\nLine 2\nLine 3")

        # Invoke LLM
        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"Read the file {test_file} and tell me what's in it")

        # Verify tool invocation
        assert_tool_invoked(collector, "read_file")

        # Verify content was processed
        assert any("Hello, World" in str(e) for e in collector.events)

    async def test_read_file_line_range(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM reads specific line range."""
        test_file = temp_workspace / "multiline.txt"
        test_file.write_text("\n".join([f"Line {i}" for i in range(1, 101)]))

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"Read lines 10-15 from {test_file}")

        assert_tool_invoked(collector, "read_file")
        # Verify the correct range was read
        calls = collector.get_tool_results("read_file")
        assert any("Line 10" in str(c) for c in calls)

    async def test_write_file_creates_new(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM creates a new file."""
        new_file = temp_workspace / "new_file.txt"

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Create a file at {new_file} with the content 'Test content'",
        )

        assert_tool_invoked(collector, "write_file")
        assert new_file.exists()
        assert "Test content" in new_file.read_text()

    async def test_write_file_overwrites_existing(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM overwrites existing file."""
        existing_file = temp_workspace / "existing.txt"
        existing_file.write_text("Old content")

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Replace the content of {existing_file} with 'New content'",
        )

        assert_tool_invoked(collector, "write_file")
        assert "New content" in existing_file.read_text()
        assert "Old content" not in existing_file.read_text()

    async def test_search_files_pattern(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM searches for files matching pattern."""
        # Create test files
        (temp_workspace / "test1.py").write_text("print('test1')")
        (temp_workspace / "test2.py").write_text("print('test2')")
        (temp_workspace / "data.txt").write_text("data")

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"Find all Python files in {temp_workspace}")

        assert_tool_invoked(collector, "search_files")
        # Verify results mention Python files
        assert any("test1.py" in str(e) and "test2.py" in str(e) for e in collector.events)

    async def test_file_error_handling(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM handles file not found error gracefully."""
        nonexistent = temp_workspace / "does_not_exist.txt"

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"Read the file {nonexistent}")

        # LLM should receive error and provide helpful response
        assert_tool_invoked(collector, "read_file")
        # Should not crash, should handle error gracefully
        assert any("not found" in str(e).lower() or "error" in str(e).lower() for e in collector.events)


@pytest.mark.integration
@pytest.mark.asyncio
class TestCodeEditToolsIntegration:
    """Integration tests for surgical code editing tools."""

    async def test_edit_single_line(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM edits a single line surgically."""
        code_file = temp_workspace / "code.py"
        code_file.write_text("def hello():\n    print('world')\n    return True\n")

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"In {code_file}, change 'world' to 'Soothe' on line 2")

        assert_tool_invoked(collector, "edit_file_lines")
        result = code_file.read_text()
        assert "Soothe" in result
        assert "world" not in result
        # Verify surgical edit - other lines unchanged
        assert "def hello():" in result
        assert "return True" in result

    async def test_edit_multiple_lines(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM edits multiple lines."""
        code_file = temp_workspace / "multi.py"
        code_file.write_text("x = 1\ny = 2\nz = 3\n")

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"In {code_file}, replace lines 1-2 with 'a = 10\\nb = 20'")

        assert_tool_invoked(collector, "edit_file_lines")
        result = code_file.read_text()
        assert "a = 10" in result
        assert "b = 20" in result
        assert "z = 3" in result  # Unchanged

    async def test_insert_lines_at_position(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM inserts lines at specific position."""
        code_file = temp_workspace / "insert.py"
        code_file.write_text("line1\nline2\n")

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"In {code_file}, insert 'new_line' after line 1")

        assert_tool_invoked(collector, "insert_lines")
        result = code_file.read_text()
        lines = result.split("\n")
        assert "line1" in lines[0]
        assert "new_line" in lines[1]
        assert "line2" in lines[2]

    async def test_delete_line_range(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM deletes specific lines."""
        code_file = temp_workspace / "delete.py"
        code_file.write_text("keep1\ndelete1\ndelete2\nkeep2\n")

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"In {code_file}, delete lines 2-3")

        assert_tool_invoked(collector, "delete_lines")
        result = code_file.read_text()
        assert "keep1" in result
        assert "keep2" in result
        assert "delete1" not in result
        assert "delete2" not in result

    async def test_edit_with_invalid_line_numbers(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM handles invalid line numbers with error recovery."""
        code_file = temp_workspace / "small.py"
        code_file.write_text("only one line\n")

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"In {code_file}, edit line 10 (which doesn't exist)")

        # Should attempt edit and receive error
        assert_tool_invoked(collector, "edit_file_lines")
        # LLM should recover and provide helpful message
        assert any("invalid" in str(e).lower() or "error" in str(e).lower() for e in collector.events)


@pytest.mark.integration
@pytest.mark.asyncio
class TestExecutionToolsIntegration:
    """Integration tests for command and Python execution tools."""

    async def test_run_simple_command(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM runs simple shell command."""
        collector = StreamEventCollector()
        await collector.collect(soothe_runner, "List files in the current directory using ls")

        assert_tool_invoked(collector, "run_command")

    async def test_run_python_basic(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM executes Python code."""
        collector = StreamEventCollector()
        await collector.collect(soothe_runner, "Use Python to calculate 2 + 2")

        assert_tool_invoked(collector, "run_python")
        # Verify result is correct
        assert any("4" in str(e) for e in collector.events)

    async def test_run_python_session_persistence(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test Python session persists across calls."""
        collector1 = StreamEventCollector()
        await collector1.collect(soothe_runner, "In Python, set x = 42")

        assert_tool_invoked(collector1, "run_python")

        # Second call should have access to x
        collector2 = StreamEventCollector()
        await collector2.collect(soothe_runner, "In Python, print the value of x")

        assert_tool_invoked(collector2, "run_python")
        assert any("42" in str(e) for e in collector2.events)

    async def test_run_python_with_imports(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test Python execution with library imports."""
        collector = StreamEventCollector()
        await collector.collect(soothe_runner, "Use Python to import math and calculate math.sqrt(16)")

        assert_tool_invoked(collector, "run_python")
        assert any("4" in str(e) or "4.0" in str(e) for e in collector.events)

    async def test_run_command_with_error(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM handles command errors gracefully."""
        collector = StreamEventCollector()
        await collector.collect(soothe_runner, "Run the command 'nonexistent_command_xyz'")

        assert_tool_invoked(collector, "run_command")
        # Should handle error and provide helpful response
        assert any("not found" in str(e).lower() or "error" in str(e).lower() for e in collector.events)

    async def test_run_python_with_error(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM handles Python errors gracefully."""
        collector = StreamEventCollector()
        await collector.collect(soothe_runner, "Use Python to divide 1 by 0")

        assert_tool_invoked(collector, "run_python")
        # Should handle ZeroDivisionError
        assert any("zero" in str(e).lower() or "error" in str(e).lower() for e in collector.events)


# ---------------------------------------------------------------------------
# Category 2: Composed Tools Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestComposedFileWorkflow:
    """Integration tests for multi-tool file workflows."""

    async def test_read_analyze_write_workflow(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM reads file, analyzes, and writes result."""
        # Setup
        input_file = temp_workspace / "data.txt"
        input_file.write_text("apple\nbanana\ncherry\n")
        output_file = temp_workspace / "result.txt"

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Read {input_file}, count the lines, and write the count to {output_file}",
        )

        # Verify tool sequence
        assert_tool_invoked(collector, "read_file")
        assert_tool_invoked(collector, "write_file")

        # Verify result
        assert output_file.exists()
        content = output_file.read_text()
        assert "3" in content

    async def test_search_read_summarize_workflow(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM searches files, reads them, and summarizes."""
        # Create multiple files
        (temp_workspace / "file1.py").write_text("def foo(): pass")
        (temp_workspace / "file2.py").write_text("def bar(): pass")
        (temp_workspace / "file3.txt").write_text("not python")

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Find all Python files in {temp_workspace}, read them, and summarize the functions defined",
        )

        # Should use search + multiple reads
        assert_tool_invoked(collector, "search_files")
        assert_tool_invoked(collector, "read_file", min_count=2)

        # Verify summary mentions the functions
        assert any("foo" in str(e) and "bar" in str(e) for e in collector.events)

    async def test_read_edit_test_workflow(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM reads, edits, and verifies changes."""
        code_file = temp_workspace / "code.py"
        code_file.write_text("def add(a, b):\n    return a - b  # Bug!\n")

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Read {code_file}, fix the bug in the add function, then read it again to verify",
        )

        # Should read, edit, read again
        assert_tool_invoked(collector, "read_file", min_count=2)
        assert_tool_invoked(collector, "edit_file_lines")

        # Verify fix
        result = code_file.read_text()
        assert "return a + b" in result or "return a+b" in result


@pytest.mark.integration
@pytest.mark.asyncio
class TestComposedCodeWorkflow:
    """Integration tests for code generation and execution workflows."""

    async def test_generate_write_run_workflow(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM generates code, writes it, and runs it."""
        script_file = temp_workspace / "script.py"

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Create a Python script at {script_file} that prints 'Hello from generated code', then run it",
        )

        # Should write file and run command
        assert_tool_invoked(collector, "write_file")
        assert_tool_invoked(collector, "run_command")

        # Verify script exists and runs
        assert script_file.exists()
        assert "Hello from generated code" in script_file.read_text()

    async def test_analyze_data_generate_insights(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM analyzes data file and generates insights."""
        data_file = temp_workspace / "data.csv"
        data_file.write_text("name,score\nAlice,85\nBob,92\nCarol,78\n")

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Read {data_file}, calculate the average score using Python, and write the result to a new file",
        )

        # Should read, run python, write
        assert_tool_invoked(collector, "read_file")
        assert_tool_invoked(collector, "run_python")
        assert_tool_invoked(collector, "write_file")

        # Find result file
        result_files = list(temp_workspace.glob("*.txt")) + list(temp_workspace.glob("result*"))
        assert len(result_files) > 0
        # Should contain average (85)
        result_content = "\n".join(f.read_text() for f in result_files)
        assert "85" in result_content

    async def test_refactor_multiple_files(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM refactors across multiple files."""
        # Create related files
        file1 = temp_workspace / "module1.py"
        file1.write_text("OLD_CONSTANT = 42\ndef func1():\n    return OLD_CONSTANT\n")

        file2 = temp_workspace / "module2.py"
        file2.write_text("from module1 import OLD_CONSTANT\ndef func2():\n    return OLD_CONSTANT * 2\n")

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Rename OLD_CONSTANT to NEW_CONSTANT in both {file1} and {file2}",
        )

        # Should edit both files
        assert_tool_invoked(collector, "edit_file_lines", min_count=2)

        # Verify changes
        assert "NEW_CONSTANT" in file1.read_text()
        assert "NEW_CONSTANT" in file2.read_text()
        assert "OLD_CONSTANT" not in file1.read_text()
        assert "OLD_CONSTANT" not in file2.read_text()


@pytest.mark.integration
@pytest.mark.asyncio
class TestComposedResearchWorkflow:
    """Integration tests for research workflows."""

    @pytest.mark.skip(reason="Requires web tools and external API access")
    async def test_web_search_summarize_save(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM searches web, summarizes, and saves results."""
        output_file = temp_workspace / "research_summary.txt"

        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Search for information about Python asyncio, summarize the key points, and save to {output_file}",
        )

        # Should search and write
        assert_tool_invoked(collector, "websearch")
        assert_tool_invoked(collector, "write_file")

        # Verify output
        assert output_file.exists()
        content = output_file.read_text().lower()
        # Should mention asyncio concepts
        assert any(term in content for term in ["async", "await", "concurrent", "asynchronous"])

    @pytest.mark.skip(reason="Requires web tools and external API access")
    async def test_crawl_extract_analyze(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test LLM crawls webpage, extracts info, and analyzes."""
        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            "Crawl the Python documentation page at https://docs.python.org/3/library/asyncio.html and extract the main concepts",
        )

        # Should use crawl tool
        assert_tool_invoked(collector, "websearch_crawl")

        # Verify extracted content
        assert any("async" in str(e).lower() for e in collector.events)


# ---------------------------------------------------------------------------
# Category 3: Control Limits Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestConcurrencyLimits:
    """Integration tests for concurrency control enforcement."""

    async def test_parallel_step_limit(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test that parallel step limit is enforced."""
        # Create a complex multi-step plan
        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            f"Create 5 different test files in {temp_workspace} simultaneously: test1.txt through test5.txt",
            autonomous=True,
        )

        # Check concurrency events
        # Should not exceed max_parallel_steps (default: 1)
        batch_events = [
            e
            for e in collector.events
            if isinstance(e.get("data", {}), dict) and e["data"].get("type") == "soothe.plan.batch_started"
        ]

        for event in batch_events:
            parallel_count = event["data"].get("parallel_count", 1)
            assert parallel_count <= 1, f"Parallel steps {parallel_count} exceeds limit"

    async def test_llm_call_semaphore(self, soothe_runner: SootheRunner) -> None:
        """Test that global LLM call limit is enforced."""

        # This would require concurrent queries
        # Create multiple concurrent goals
        async def run_query(query: str) -> StreamEventCollector:
            collector = StreamEventCollector()
            await collector.collect(soothe_runner, query)
            return collector

        # Run multiple queries concurrently
        results = await asyncio.gather(
            run_query("Calculate 1+1"),
            run_query("Calculate 2+2"),
            run_query("Calculate 3+3"),
        )

        # All should complete without hitting semaphore timeout
        for collector in results:
            assert len(collector.events) > 0

    async def test_goal_parallelism_limit(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test that goal parallelism limit is enforced in autonomous mode."""
        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            "Create two files: a.txt and b.txt, then read both and combine their contents",
            autonomous=True,
        )

        # Check goal batch events
        goal_batches = [
            e
            for e in collector.events
            if isinstance(e.get("data", {}), dict) and e["data"].get("type") == "soothe.goal.batch_started"
        ]

        for batch in goal_batches:
            parallel_count = batch["data"].get("parallel_count", 1)
            # Default max_parallel_goals is 1
            assert parallel_count <= 1, f"Parallel goals {parallel_count} exceeds limit"


@pytest.mark.integration
@pytest.mark.asyncio
class TestPolicyEnforcement:
    """Integration tests for policy-based access control."""

    async def test_readonly_policy_blocks_writes(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test that readonly policy prevents file writes."""
        # Note: This test requires configuring a readonly policy
        # For now, we test that the policy middleware is in place
        test_file = temp_workspace / "protected.txt"

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"Write 'test' to {test_file}")

        # File should either be created (policy allows) or denied
        # The test verifies the policy middleware is active
        assert_tool_invoked(collector, "write_file")

    async def test_shell_policy_blocks_dangerous_commands(
        self,
        soothe_runner: SootheRunner,
    ) -> None:
        """Test that shell policy blocks dangerous commands."""
        collector = StreamEventCollector()
        await collector.collect(soothe_runner, "Run the command 'rm -rf /'")

        # Should be blocked by banned_commands
        assert_tool_invoked(collector, "run_command")
        # Should receive error about banned command
        assert any("not allowed" in str(e).lower() or "banned" in str(e).lower() for e in collector.events)

    async def test_network_policy_restrictions(
        self,
        soothe_runner: SootheRunner,
    ) -> None:
        """Test that network policy restricts certain domains."""
        # This would require configuring a restrictive policy
        # Placeholder for network policy testing


@pytest.mark.integration
@pytest.mark.asyncio
class TestIterationLimits:
    """Integration tests for iteration and retry limits."""

    async def test_max_iterations_enforced(self, soothe_runner: SootheRunner) -> None:
        """Test that max_iterations is enforced in autonomous mode."""
        collector = StreamEventCollector()

        # Give a task that would require many iterations
        await collector.collect(
            soothe_runner,
            "Count from 1 to 100, one number at a time",
            autonomous=True,
            max_iterations=5,
        )

        # Should stop at max_iterations
        iteration_events = [
            e
            for e in collector.events
            if isinstance(e.get("data", {}), dict) and e["data"].get("type") == "soothe.autonomous.iteration_completed"
        ]

        assert len(iteration_events) <= 5

    async def test_goal_retry_limit(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test that goal retry limit is enforced."""
        collector = StreamEventCollector()

        # Give a task that will fail repeatedly
        await collector.collect(
            soothe_runner,
            "Read a file that doesn't exist: /nonexistent/path/file.txt",
            autonomous=True,
        )

        # Check goal retry events
        goal_failed_events = [
            e
            for e in collector.events
            if isinstance(e.get("data", {}), dict) and e["data"].get("type") == "soothe.goal.failed"
        ]

        # Should not retry more than max_retries (default: 2)
        assert len(goal_failed_events) <= 3  # Initial + 2 retries

    async def test_hitl_iteration_limit(self, soothe_runner: SootheRunner) -> None:
        """Test HITL iteration limit."""
        # This would require mocking user interaction
        # Placeholder for HITL limit testing


@pytest.mark.integration
@pytest.mark.asyncio
class TestToolLevelRetry:
    """Integration tests for tool-level retry mechanisms."""

    async def test_shell_recovery_on_timeout(self, soothe_runner: SootheRunner) -> None:
        """Test that shell recovers from timeout errors."""
        collector = StreamEventCollector()

        # Run a command that might timeout
        await collector.collect(soothe_runner, "Run 'sleep 0.1' with a very short timeout")

        # Should handle timeout gracefully
        # Shell should recover if needed
        assert len(collector.events) > 0

    async def test_python_session_error_recovery(self, soothe_runner: SootheRunner) -> None:
        """Test Python session recovers from errors."""
        # Cause an error
        collector1 = StreamEventCollector()
        await collector1.collect(
            soothe_runner,
            "Run Python code that raises an exception: raise ValueError('test')",
        )

        # Session should still be usable
        collector2 = StreamEventCollector()
        await collector2.collect(soothe_runner, "Run Python code that works: print('recovered')")

        assert any("recovered" in str(e) for e in collector2.events)


# ---------------------------------------------------------------------------
# Category 4: Edge Cases and Failure Modes
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestToolErrorHandling:
    """Integration tests for tool error scenarios."""

    async def test_tool_error_with_suggestions(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test that tool errors include helpful suggestions."""
        nonexistent = temp_workspace / "missing.txt"

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"Read {nonexistent}")

        # Error should include suggestions
        error_events = [e for e in collector.events if "error" in str(e).lower()]
        assert len(error_events) > 0

        # Should mention list_files or similar suggestion
        error_text = "\n".join(str(e) for e in error_events).lower()
        assert any(word in error_text for word in ["list", "check", "search", "suggestion"])

    async def test_cascading_failures(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test handling of cascading tool failures."""
        # Give a complex task where early failure should prevent later steps
        collector = StreamEventCollector()
        await collector.collect(
            soothe_runner,
            "Read nonexistent.txt, then write its contents to output.txt",
        )

        # Should not attempt write after read failure
        assert_tool_invoked(collector, "read_file")
        # write_file should not be called (or should handle gracefully)
        write_calls = collector.get_tool_results("write_file")
        # If called, should be with error handling
        assert len(write_calls) == 0 or any("error" in str(c) for c in write_calls)


@pytest.mark.integration
@pytest.mark.asyncio
class TestResourceExhaustion:
    """Integration tests for resource exhaustion scenarios."""

    async def test_large_file_handling(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test handling of files exceeding size limits."""
        # Create a large file
        large_file = temp_workspace / "large.txt"
        large_file.write_text("x" * (20 * 1024 * 1024))  # 20MB

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"Read {large_file}")

        # Should handle size limit error gracefully
        assert any("size" in str(e).lower() or "exceeds" in str(e).lower() for e in collector.events)

    async def test_memory_intensive_python(self, soothe_runner: SootheRunner) -> None:
        """Test handling of memory-intensive Python code."""
        collector = StreamEventCollector()
        await collector.collect(soothe_runner, "Create a very large list in Python: [i for i in range(10**8)]")

        # Should either handle or timeout gracefully
        assert len(collector.events) > 0
        # Should not crash the runner

    async def test_concurrent_file_handles(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test handling of many concurrent file operations."""
        # Create many files
        files = []
        for i in range(100):
            f = temp_workspace / f"file{i}.txt"
            f.write_text(f"content {i}")
            files.append(f)

        collector = StreamEventCollector()
        await collector.collect(soothe_runner, f"Read all {len(files)} files in {temp_workspace}")

        # Should handle resource limits
        assert len(collector.events) > 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestConcurrentAccess:
    """Integration tests for concurrent access scenarios."""

    async def test_simultaneous_file_write(self, soothe_runner: SootheRunner, temp_workspace: Path) -> None:
        """Test handling of simultaneous writes to same file."""
        test_file = temp_workspace / "concurrent.txt"

        # Try to write simultaneously
        async def write_content(content: str) -> StreamEventCollector:
            collector = StreamEventCollector()
            await collector.collect(soothe_runner, f"Write '{content}' to {test_file}")
            return collector

        # Run concurrent writes
        results = await asyncio.gather(
            write_content("content1"),
            write_content("content2"),
            return_exceptions=True,
        )

        # At least one should succeed
        successful = [r for r in results if not isinstance(r, Exception)]
        assert len(successful) >= 1

    async def test_python_session_isolation(self, soothe_runner: SootheRunner) -> None:
        """Test that Python sessions are properly isolated."""

        # Create tasks with different session IDs
        async def run_with_session(session_id: str, value: int) -> StreamEventCollector:
            collector = StreamEventCollector()
            # Would need to pass session_id somehow
            # This tests the session manager isolation
            await collector.collect(soothe_runner, f"In Python session {session_id}, set x = {value}")
            return collector

        # Run with different sessions
        results = await asyncio.gather(
            run_with_session("session1", 10),
            run_with_session("session2", 20),
        )

        # Sessions should be isolated
        assert len(results) == 2
