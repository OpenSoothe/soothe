"""Tests for CLI Stream Display Pipeline (RFC-0020).

NOTE: Tool call display is handled by CliRenderer.on_tool_call/on_tool_result
via EventProcessor, NOT through the pipeline. The pipeline handles goal/step/subagent events.
Tool formatters remain for subagent dispatch display.
"""

from __future__ import annotations

from soothe_cli.cli.stream.context import PipelineContext
from soothe_cli.cli.stream.display_line import DisplayLine, indent_for_level
from soothe_cli.cli.stream.formatter import (
    abbreviate_text,
    format_goal_done,
    format_goal_header,
    format_step_done,
    format_step_header,
    format_subagent_done,
    format_subagent_milestone,
    format_tool_call,
    format_tool_result,
)
from soothe_cli.cli.stream.pipeline import StreamDisplayPipeline


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

    def test_format_level2_flat(self) -> None:
        line = DisplayLine(
            level=2,
            content="Step 1: test",
            icon="●",
            indent="",
        )
        assert line.format() == "● Step 1: test"

    def test_format_with_status(self) -> None:
        line = DisplayLine(
            level=2,
            content="tool()",
            icon="⚙",
            indent="",
            status="running",
        )
        assert line.format() == "⚙ tool() [running]"

    def test_format_with_duration_ms(self) -> None:
        line = DisplayLine(
            level=3,
            content="Done",
            icon="✓",
            indent="",
            duration_ms=150,
        )
        assert line.format() == "✓ Done (150ms)"

    def test_format_with_duration_seconds(self) -> None:
        line = DisplayLine(
            level=3,
            content="Done",
            icon="✓",
            indent="",
            duration_ms=1500,
        )
        assert line.format() == "✓ Done (1.5s)"


class TestIndentForLevel:
    """Tests for indent_for_level function."""

    def test_level1_empty(self) -> None:
        assert indent_for_level(1) == ""

    def test_level2_flat_indent(self) -> None:
        assert indent_for_level(2) == ""

    def test_level3_flat_indent(self) -> None:
        assert indent_for_level(3) == ""


class TestFormatters:
    """Tests for formatter functions."""

    def test_abbreviate_text_short(self) -> None:
        """Short text is not abbreviated."""
        result = abbreviate_text("Short text")
        assert result == "Short text"

    def test_abbreviate_text_long(self) -> None:
        """Long text is abbreviated with ellipsis."""
        text = "Run cloc on src/ and tests/ directories to count Soothe source and test code"
        result = abbreviate_text(text, max_length=50)
        assert "Run cloc on src/ and" in result
        assert "..." in result
        assert "test code" in result
        assert len(result) < len(text)

    def test_abbreviate_text_preserves_threshold(self) -> None:
        """Text at max_length threshold is not abbreviated."""
        text = "Exactly fifty characters long text here okay"
        result = abbreviate_text(text, max_length=50)
        assert result == text  # Should not be abbreviated

    def test_format_goal_header(self) -> None:
        line = format_goal_header("Analyze codebase")
        assert line.level == 1
        assert line.content == "🚩 Analyze codebase"
        assert line.icon == "●"

    def test_format_step_header_sequential(self) -> None:
        line = format_step_header("Read files", parallel=False)
        assert line.level == 2
        assert line.content == "⏩ Read files"
        assert line.icon == "○"  # Hollow circle for in-progress
        assert line.status is None

    def test_format_step_header_parallel(self) -> None:
        line = format_step_header("Read files", parallel=True)
        assert line.content == "⏩ Read files (parallel)"
        assert line.icon == "○"

    def test_format_tool_call_sequential(self) -> None:
        line = format_tool_call("read_file", '"config.yml"', running=False)
        assert line.level == 2
        assert line.content == '🔧 read_file("config.yml")'
        assert line.status is None

    def test_format_tool_call_parallel(self) -> None:
        line = format_tool_call("read_file", '"config.yml"', running=True)
        assert line.status == "running"

    def test_format_tool_result_success(self) -> None:
        line = format_tool_result("Read 42 lines", 150, is_error=False)
        assert line.level == 3
        assert line.content == "✨ Read 42 lines"
        assert line.icon == "✓"
        assert line.duration_ms == 150

    def test_format_tool_result_error(self) -> None:
        line = format_tool_result("File not found", 10, is_error=True)
        assert line.icon == "✗"

    def test_format_subagent_milestone(self) -> None:
        line = format_subagent_milestone("arxiv: 15 results")
        assert line.level == 3
        assert line.content == "🕵🏻‍♂️ arxiv: 15 results"
        assert line.icon == "✓"

    def test_format_subagent_done(self) -> None:
        line = format_subagent_done("5 papers found", 45.2)
        assert line.content == "🕵🏻‍♂️ Done: 5 papers found"
        assert line.duration_ms == 45200

    def test_format_step_done(self) -> None:
        line = format_step_done("Read files", 3.2)
        assert line.level == 2
        assert line.content == "✅ Read files"
        assert line.icon == "●"  # Solid circle for completed
        assert line.duration_ms == 3200

    def test_format_step_done_with_long_description(self) -> None:
        """Long step descriptions are abbreviated."""
        description = "Run cloc on src/ and tests/ directories to count Soothe source and test code"
        line = format_step_done(description, 11.4, tool_call_count=1)

        assert "Run cloc on src/ and" in line.content
        assert "... test code" in line.content
        assert "[1 tools]" in line.content
        assert len(line.content) < len(description) + 20  # Should be shorter

    def test_format_step_done_with_short_description(self) -> None:
        """Short step descriptions are not abbreviated."""
        line = format_step_done("Read config", 3.2, tool_call_count=2)

        assert "Read config" in line.content
        assert "..." not in line.content

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
    """Tests for StreamDisplayPipeline.

    Note: Tool events are handled by CliRenderer.on_tool_call/on_tool_result
    via EventProcessor. The pipeline focuses on goal/step/subagent events.
    """

    def test_goal_started(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        event = {
            "type": "soothe.cognition.agent_loop.started",
            "goal": "Analyze codebase",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].content == "🚩 Analyze codebase"
        assert lines[0].icon == "●"

    def test_step_started(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        pipeline.process({"type": "soothe.cognition.agent_loop.started", "goal": "test"})

        event = {
            "type": "soothe.cognition.plan.step_started",
            "step_id": "s1",
            "description": "Read config",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].icon == "○"  # Hollow circle for started step
        assert lines[0].content == "⏩ Read config"

    def test_subagent_dispatched(self) -> None:
        """Test subagent dispatch shows as tool call."""
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.subagent.research.dispatched",
            "name": "research",
            "query": "quantum computing papers",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "🔧 research_subagent" in lines[0].content
        assert lines[0].icon == "⚙"

    def test_subagent_step_hidden_at_normal(self) -> None:
        """IG-089: Subagent internal steps hidden at normal verbosity."""
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.subagent.research.step",
            "step_type": "query",
            "action": "arxiv search",
            "target": "quantum computing",
        }
        lines = pipeline.process(event)

        # Internal steps hidden at normal verbosity
        assert len(lines) == 0

    def test_subagent_step_shown_at_detailed(self) -> None:
        """IG-089: Subagent internal steps visible at detailed verbosity."""
        pipeline = StreamDisplayPipeline(verbosity="detailed")

        event = {
            "type": "soothe.subagent.research.step",
            "step_type": "query",
            "action": "arxiv search",
            "target": "quantum computing",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].icon == "✓"
        assert "🕵🏻‍♂️" in lines[0].content

    def test_subagent_judgement_shown_at_normal(self) -> None:
        """IG-089: Subagent judgement visible at normal verbosity."""
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.subagent.research.judgement",
            "judgement": "Need more sources: statistics gap",
            "action": "continue",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "🌀 Need more sources" in lines[0].content
        assert lines[0].icon == "→"  # Arrow for continue action

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
            "type": "soothe.cognition.agent_loop.completed",
            "goal": "test",
            "total_steps": 3,
        }
        lines = pipeline.process(event)
        assert len(lines) == 1

        # Goal start should not show at quiet
        event = {
            "type": "soothe.cognition.agent_loop.started",
            "goal": "test",
        }
        lines = pipeline.process(event)
        assert len(lines) == 0

    def test_goal_completion(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        pipeline._context.current_goal = "Analyze codebase"
        pipeline._context.goal_start_time = 0.0
        pipeline._context.steps_completed = 3

        event = {
            "type": "soothe.cognition.agent_loop.completed",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].icon == "●"
        assert "🏆" in lines[0].content
        assert "complete" in lines[0].content
        assert "3 steps" in lines[0].content

    def test_tool_events_handled_by_pipeline(self) -> None:
        """Tool events are INTERNAL (RFC-0020) - not displayed via pipeline.

        Tool display is via LangChain tool_calls → CliRenderer.on_tool_call.
        Tool events (soothe.tool.*) are for logging/metrics only, not display.
        They should be filtered out at NORMAL verbosity.
        """
        pipeline = StreamDisplayPipeline(verbosity="normal")

        # Tool events should NOT be visible at NORMAL verbosity (INTERNAL)
        # Using actual registered events from file_ops/events.py
        event = {
            "type": "soothe.tool.file_ops.read",
            "tool": "read_file",
            "path": "config.yml",
        }
        lines = pipeline.process(event)
        assert len(lines) == 0  # Filtered out (INTERNAL tier)

        # Tool write events should also NOT be visible
        event = {
            "type": "soothe.tool.file_ops.write",
            "tool": "write_file",
            "path": "config.yml",
        }
        lines = pipeline.process(event)
        assert len(lines) == 0  # Filtered out (INTERNAL tier)

        # Tool search events should also NOT be visible
        event = {
            "type": "soothe.tool.file_ops.search_started",
            "tool": "search_files",
            "pattern": "*.py",
        }
        lines = pipeline.process(event)
        assert len(lines) == 0  # Filtered out (INTERNAL tier)

    def test_subagent_completed(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.subagent.research.completed",
            "summary": "5 papers found",
            "duration_s": 45.2,
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "Done: 5 papers" in lines[0].content
        assert lines[0].duration_ms == 45200

    def test_loop_agent_reason_shown_at_normal(self) -> None:
        """Loop agent Reason event emits one concise summary line (RFC-603: no percentage)."""
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.cognition.agent_loop.reason",
            "status": "continue",
            "progress": 0.5,
            "confidence": 0.8,
            "next_action": "I'll check your config files next.",
            "iteration": 1,
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "I'll check your config files next." in lines[0].content
        # RFC-603: Percentage display removed per user request
        assert "80% sure" not in lines[0].content
        assert lines[0].icon == "→"

    def test_loop_agent_reason_done_shows_checkmark(self) -> None:
        """Reason event with status=done shows checkmark icon."""
        pipeline = StreamDisplayPipeline(verbosity="normal")

        event = {
            "type": "soothe.cognition.agent_loop.reason",
            "status": "done",
            "progress": 1.0,
            "confidence": 0.95,
            "next_action": "I'm sharing the final result now.",
            "iteration": 3,
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "I'm sharing the final result now." in lines[0].content
        # RFC-603: Percentage display removed per user request
        assert "95% sure" not in lines[0].content
        assert lines[0].icon == "✓"

    def test_step_completed_with_tool_call_count(self) -> None:
        """Step completion shows tool call count when > 0."""
        pipeline = StreamDisplayPipeline(verbosity="normal")
        pipeline._context.current_step_description = "Explore project structure"

        event = {
            "type": "soothe.cognition.agent_loop.step.completed",
            "step_id": "step_1",
            "success": True,
            "summary": "Done",
            "duration_ms": 1500,
            "tool_call_count": 5,
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "Explore project structure" in lines[0].content
        assert "[5 tools]" in lines[0].content
        assert lines[0].icon == "●"  # Solid circle for completed
        assert lines[0].duration_ms == 1500

    def test_step_completed_without_tool_calls(self) -> None:
        """Step completion without tool calls shows just description."""
        pipeline = StreamDisplayPipeline(verbosity="normal")
        pipeline._context.current_step_description = "Analyze config"

        event = {
            "type": "soothe.cognition.agent_loop.step.completed",
            "step_id": "step_2",
            "success": True,
            "summary": "Done",
            "duration_ms": 800,
            "tool_call_count": 0,
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "Analyze config" in lines[0].content
        assert "[0 tools]" not in lines[0].content  # Should not show when 0

    def test_step_completed_uses_tracked_description_by_step_id(self) -> None:
        """Step completion keeps description when current step context has moved."""
        pipeline = StreamDisplayPipeline(verbosity="normal")

        pipeline.process(
            {
                "type": "soothe.cognition.plan.step_started",
                "step_id": "step_a",
                "description": "Search root directory",
            }
        )
        pipeline.process(
            {
                "type": "soothe.cognition.plan.step_started",
                "step_id": "step_b",
                "description": "Search src directory",
            }
        )

        lines = pipeline.process(
            {
                "type": "soothe.cognition.agent_loop.step.completed",
                "step_id": "step_a",
                "duration_ms": 2000,
                "tool_call_count": 2,
            }
        )

        assert len(lines) == 1
        assert "Search root directory" in lines[0].content
        assert "[2 tools]" in lines[0].content

    def test_loop_agent_reason_deduped_in_short_window(self) -> None:
        pipeline = StreamDisplayPipeline(verbosity="normal")
        event = {
            "type": "soothe.cognition.agent_loop.reason",
            "status": "continue",
            "progress": 0.4,
            "confidence": 0.8,
            "next_action": "I'm searching for README files.",
            "iteration": 1,
        }

        lines1 = pipeline.process(event)
        lines2 = pipeline.process(event)
        assert len(lines1) == 1
        assert lines2 == []
