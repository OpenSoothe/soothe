"""Tests for CLI Stream Display Pipeline (RFC-0020)."""

from __future__ import annotations

import pytest

from soothe.ux.cli.stream.context import PipelineContext, ToolCallInfo
from soothe.ux.cli.stream.display_line import DisplayLine, indent_for_level
from soothe.ux.cli.stream.formatter import (
    format_goal_done,
    format_goal_header,
    format_step_done,
    format_step_header,
    format_subagent_done,
    format_subagent_milestone,
    format_tool_call,
    format_tool_result,
)
from soothe.ux.cli.stream.pipeline import StreamDisplayPipeline


class TestDisplayLine:
    """Tests for DisplayLine dataclass."""

    def test_format_level1_no_indent(self) -> None:
        line = DisplayLine(
            level=1,
            content="Goal: test",
            icon="●",
            indent="",
        )
        assert line.format() == "● Goal: test"

    def test_format_level2_with_indent(self) -> None:
        line = DisplayLine(
            level=2,
            content="Step 1: test",
            icon="●",  # Icon is separate from tree connector in indent
            indent="  └ ",
        )
        assert line.format() == "  └ ● Step 1: test"

    def test_format_with_status(self) -> None:
        line = DisplayLine(
            level=2,
            content="tool()",
            icon="⚙",
            indent="  └ ",
            status="running",
        )
        assert line.format() == "  └ ⚙ tool() [running]"

    def test_format_with_duration_ms(self) -> None:
        line = DisplayLine(
            level=3,
            content="Done",
            icon="✓",
            indent="     └ ",
            duration_ms=150,
        )
        assert line.format() == "     └ ✓ Done (150ms)"

    def test_format_with_duration_seconds(self) -> None:
        line = DisplayLine(
            level=3,
            content="Done",
            icon="✓",
            indent="     └ ",
            duration_ms=1500,
        )
        assert line.format() == "     └ ✓ Done (1.5s)"


class TestIndentForLevel:
    """Tests for indent_for_level function."""

    def test_level1_empty(self) -> None:
        assert indent_for_level(1) == ""

    def test_level2_step_indent(self) -> None:
        assert indent_for_level(2) == "  └ "

    def test_level3_result_indent(self) -> None:
        assert indent_for_level(3) == "     └ "


class TestFormatters:
    """Tests for formatter functions."""

    def test_format_goal_header(self) -> None:
        line = format_goal_header("Analyze codebase")
        assert line.level == 1
        assert line.content == "Goal: Analyze codebase"
        assert line.icon == "●"

    def test_format_step_header_sequential(self) -> None:
        line = format_step_header(1, "Read files", parallel=False)
        assert line.level == 2
        assert line.content == "Step 1: Read files"
        assert line.icon == "└"
        assert line.status is None

    def test_format_step_header_parallel(self) -> None:
        line = format_step_header(1, "Read files", parallel=True)
        assert line.content == "Step 1: Read files (parallel)"

    def test_format_tool_call_sequential(self) -> None:
        line = format_tool_call("read_file", '"config.yml"', running=False)
        assert line.level == 2
        assert line.content == 'read_file("config.yml")'
        assert line.status is None

    def test_format_tool_call_parallel(self) -> None:
        line = format_tool_call("read_file", '"config.yml"', running=True)
        assert line.status == "running"

    def test_format_tool_result_success(self) -> None:
        line = format_tool_result("Read 42 lines", 150, is_error=False)
        assert line.level == 3
        assert line.content == "Read 42 lines"
        assert line.icon == "✓"
        assert line.duration_ms == 150

    def test_format_tool_result_error(self) -> None:
        line = format_tool_result("File not found", 10, is_error=True)
        assert line.icon == "✗"

    def test_format_subagent_milestone(self) -> None:
        line = format_subagent_milestone("arxiv: 15 results")
        assert line.level == 3
        assert line.content == "arxiv: 15 results"
        assert line.icon == "✓"

    def test_format_subagent_done(self) -> None:
        line = format_subagent_done("5 papers found", 45.2)
        assert line.content == "Done: 5 papers found"
        assert line.duration_ms == 45200

    def test_format_step_done(self) -> None:
        line = format_step_done(1, 3.2)
        assert line.level == 2
        assert line.content == "Step 1 done"
        assert line.duration_ms == 3200

    def test_format_goal_done(self) -> None:
        line = format_goal_done("Analyze codebase", 3, 38.1)
        assert line.level == 1
        assert "complete" in line.content
        assert "3 steps" in line.content


class TestPipelineContext:
    """Tests for PipelineContext."""

    def test_start_tool_call(self) -> None:
        ctx = PipelineContext()
        ctx.start_tool_call("tc1", "read_file", '"file.txt"', 0.0)
        assert "tc1" in ctx.pending_tool_calls
        assert ctx.pending_tool_calls["tc1"].name == "read_file"

    def test_parallel_mode_detection(self) -> None:
        ctx = PipelineContext()
        ctx.start_tool_call("tc1", "tool1", "", 0.0)
        assert not ctx.parallel_mode

        ctx.start_tool_call("tc2", "tool2", "", 0.0)
        assert ctx.parallel_mode

    def test_complete_tool_call(self) -> None:
        ctx = PipelineContext()
        ctx.start_tool_call("tc1", "read_file", "", 0.0)
        ctx.start_tool_call("tc2", "glob", "", 0.0)
        assert ctx.parallel_mode

        ctx.complete_tool_call("tc1")
        assert ctx.parallel_mode  # Still parallel

        ctx.complete_tool_call("tc2")
        assert not ctx.parallel_mode  # No longer parallel

    def test_reset_step(self) -> None:
        ctx = PipelineContext()
        ctx.current_step_id = "s1"
        ctx.start_tool_call("tc1", "tool", "", 0.0)
        ctx.parallel_mode = True

        ctx.reset_step()

        assert ctx.current_step_id is None
        assert not ctx.pending_tool_calls
        assert not ctx.parallel_mode


class TestStreamDisplayPipeline:
    """Tests for StreamDisplayPipeline."""

    def test_goal_started(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        event = {
            "type": "soothe.agentic.loop.started",
            "goal": "Analyze codebase",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].content == "Goal: Analyze codebase"
        assert lines[0].icon == "●"

    def test_step_started(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        pipeline.process({"type": "soothe.agentic.loop.started", "goal": "test"})

        event = {
            "type": "soothe.cognition.plan.step_started",
            "step_id": "s1",
            "description": "Read config",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "Step 1" in lines[0].content
        assert "Read config" in lines[0].content

    def test_tool_call_visible_at_normal(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.tool.read_file.call_started",
            "tool_call_id": "tc1",
            "name": "read_file",
            "args": {"path": "config.yml"},
        }
        lines = pipeline.process(event)

        # Tool calls should be visible at NORMAL verbosity
        assert len(lines) == 1
        assert "read_file" in lines[0].content

    def test_tool_result_visible_at_normal(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")

        # First start the tool call
        pipeline.process(
            {
                "type": "soothe.tool.read_file.call_started",
                "tool_call_id": "tc1",
                "name": "read_file",
                "args": {},
            }
        )

        event = {
            "type": "soothe.tool.read_file.call_completed",
            "tool_call_id": "tc1",
            "result": "Read 42 lines",
            "duration_ms": 150,
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].icon == "✓"
        assert lines[0].duration_ms == 150

    def test_parallel_tool_detection(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        pipeline._context.current_step_description = "Test step"
        pipeline._context.steps_completed = 0

        # Start first tool
        pipeline.process(
            {
                "type": "soothe.tool.read_file.call_started",
                "tool_call_id": "tc1",
                "name": "read_file",
                "args": {},
            }
        )

        # Start second tool - should trigger parallel mode
        lines = pipeline.process(
            {
                "type": "soothe.tool.glob.call_started",
                "tool_call_id": "tc2",
                "name": "glob",
                "args": {},
            }
        )

        # Should emit step header with (parallel) and tool call
        assert pipeline._context.parallel_mode
        assert any("(parallel)" in line.content for line in lines)

    def test_subagent_step_shown_for_query(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.subagent.research.step",
            "step_type": "query",
            "action": "arxiv search",
            "target": "quantum computing",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].icon == "✓"

    def test_subagent_step_hidden_for_internal(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.subagent.research.step",
            "step_type": "reasoning",  # Not a query/analyze type
            "action": "thinking",
        }
        lines = pipeline.process(event)

        assert len(lines) == 0

    def test_quiet_mode_filters_most_events(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="quiet")

        # Goal completion should show at quiet
        event = {
            "type": "soothe.agentic.loop.completed",
            "goal": "test",
            "total_steps": 3,
        }
        lines = pipeline.process(event)
        assert len(lines) == 1

        # Tool calls should not show at quiet
        event = {
            "type": "soothe.tool.read_file.call_started",
            "tool_call_id": "tc1",
            "name": "read_file",
            "args": {},
        }
        lines = pipeline.process(event)
        assert len(lines) == 0

    def test_goal_completion(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        pipeline._context.current_goal = "Analyze codebase"
        pipeline._context.goal_start_time = 0.0
        pipeline._context.steps_completed = 3

        event = {
            "type": "soothe.agentic.loop.completed",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].icon == "●"
        assert "complete" in lines[0].content
        assert "3 steps" in lines[0].content
