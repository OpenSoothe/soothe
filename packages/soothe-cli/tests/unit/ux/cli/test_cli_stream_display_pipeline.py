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
from soothe_sdk.core.subagent_wire import SUBAGENT_CLAUDE_STEP_COMPLETED

_STEP_DONE_MARK = "\u2705\ufe0f"


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

    def test_level3_tree_indent(self) -> None:
        """IG-182: Level 3 uses 2-space indent for tree children (step results)."""
        assert indent_for_level(3) == "  "


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
        assert line.content == "📍 Analyze codebase"
        assert line.icon == "●"

    def test_format_step_header_sequential(self) -> None:
        line = format_step_header("Read files", parallel=False)
        assert line.level == 2
        assert line.content == "❇️ Read files"
        assert line.icon == "○"  # Hollow circle for in-progress
        assert line.status is None

    def test_format_step_header_parallel(self) -> None:
        line = format_step_header("Read files", parallel=True)
        assert line.content == "❇️ Read files (parallel)"
        assert line.icon == "○"

    def test_format_tool_call_sequential(self) -> None:
        line = format_tool_call("read_file", '"config.yml"', running=False)
        assert line.level == 2
        assert line.content == '🔧 ReadFile("config.yml")'
        assert line.status is None

    def test_format_tool_call_parallel(self) -> None:
        line = format_tool_call("read_file", '"config.yml"', running=True)
        assert line.status == "running"

    def test_format_tool_result_success(self) -> None:
        line = format_tool_result("Read 42 lines", 150, is_error=False)
        assert line.level == 3
        assert line.content == "✨ Read 42 lines"
        assert line.icon == "●"
        assert line.duration_ms == 150

    def test_format_tool_result_error(self) -> None:
        line = format_tool_result("File not found", 10, is_error=True)
        assert line.icon == "✗"

    def test_format_subagent_milestone(self) -> None:
        line = format_subagent_milestone("arxiv: 15 results")
        assert line.level == 2
        assert line.content == "arxiv: 15 results"
        assert line.icon == "●"
        assert line.indent == ""

    def test_format_subagent_milestone_task_scope(self) -> None:
        line = format_subagent_milestone(
            "arxiv: 15 results",
            task_scope=("functions.task:0", "explore"),
        )
        assert line.content == "Task(explore):#0 arxiv: 15 results"
        assert line.icon == "⚙"

    def test_format_subagent_done(self) -> None:
        """IG-256: Subagent done shows triple success markers."""
        line = format_subagent_done("5 papers found", 45.2)
        assert "5 papers found" in line.content
        assert line.duration_ms == 45200

    def test_format_subagent_done_task_scope_flat(self) -> None:
        line = format_subagent_done(
            "2 findings, 4 iterations (medium)",
            5.9,
            task_scope=("functions.task:0", "explore"),
            task_description="Count README files",
        )
        assert line.icon == "⚙"
        assert line.indent == ""
        assert line.content == 'Task(explore, "Count README files") -> ✓ Completed (5900ms)'
        assert line.duration_ms is None

    def test_format_subagent_done_task_scope_with_answer_summary(self) -> None:
        """IG-344: Optional answer tail after completion metrics inside Task scope."""
        line = format_subagent_done(
            "$0.01, session=abc12345",
            40.852,
            task_scope=("functions.task:0", "claude"),
            task_description="Count README files",
            answer_summary="Found 88 README files in the workspace.",
        )
        assert (
            line.content
            == 'Task(claude, "Count README files") -> ✓ Completed (40852ms): Found 88 README files in the workspace.'
        )

    def test_format_step_done(self) -> None:
        """Success with no description emits nothing (no generic Step line)."""
        lines = format_step_done(3.2)
        assert lines == []

    def test_format_step_done_with_tool_calls(self) -> None:
        """Same suppression when tool count is set but description is missing."""
        lines = format_step_done(11.4, tool_call_count=1)
        assert lines == []

    def test_format_step_done_without_tool_calls(self) -> None:
        """Empty description still suppresses generic Step (done)."""
        lines = format_step_done(3.2, tool_call_count=0)
        assert lines == []

    def test_format_step_done_with_description(self) -> None:
        """Step description appears after ✅️ like goal text after 🏆."""
        lines = format_step_done(2.0, step_description="Read README header", tool_call_count=4)
        assert lines[0].content == f"{_STEP_DONE_MARK} Read README header (done, 4 tools)"

    def test_format_step_done_with_error(self) -> None:
        """Failure line matches success structure; detail on second flat row."""
        lines = format_step_done(2.1, success=False, error_msg="File not found")
        assert len(lines) == 2
        assert lines[0].content == "✗ Step (failed)"
        assert lines[0].icon == "●"
        assert lines[1].content == "Error: File not found"
        assert lines[1].icon == ""
        assert lines[1].indent == ""

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

    def test_claude_step_wire_emits_task_scoped_milestone(self) -> None:
        """IG-344: Claude tool-use wire events render as Task-scoped milestones."""
        pipeline = StreamDisplayPipeline()
        event = {
            "type": SUBAGENT_CLAUDE_STEP_COMPLETED,
            "tool_name": "Glob",
            "input_preview": "pattern=**/*.md",
            "task_scope": ("functions.task:0", "claude"),
        }
        lines = pipeline.process(event)
        assert len(lines) == 1
        assert lines[0].icon == "⚙"
        assert "Task(claude):#0" in lines[0].content
        assert "Glob" in lines[0].content

    def test_goal_started(self) -> None:
        pipeline = StreamDisplayPipeline()
        event = {
            "type": "soothe.cognition.agent_loop.started",
            "goal": "Analyze codebase",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].content == "📍 Analyze codebase"
        assert lines[0].icon == "●"

    def test_step_started(self) -> None:
        """IG-182: Step started shows hollow circle icon."""
        pipeline = StreamDisplayPipeline()
        pipeline.process({"type": "soothe.cognition.agent_loop.started", "goal": "test"})

        event = {
            "type": "soothe.cognition.plan.step.started",
            "step_id": "s1",
            "description": "Read config",
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].icon == "○"  # Hollow circle for started step
        assert lines[0].content == "❇️ Read config"
        assert lines[0].indent == ""  # Level 2: flat layout

    def test_subagent_dispatched(self) -> None:
        """Legacy dispatched events are not on the curated wire; pipeline skips them."""
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.subagent.research.dispatched",
            "name": "research",
            "query": "quantum computing papers",
        }
        lines = pipeline.process(event)

        assert len(lines) == 0

    def test_subagent_step_hidden_at_normal(self) -> None:
        """IG-089: Subagent internal steps hidden at normal verbosity."""
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.subagent.research.step",
            "step_type": "query",
            "action": "arxiv search",
            "target": "quantum computing",
        }
        lines = pipeline.process(event)

        # Internal steps hidden at normal verbosity
        assert len(lines) == 0

    def test_subagent_explore_milestone_with_task_scope(self) -> None:
        """Curated explore milestone uses Task(explore, "...") when task_scope is set."""
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.subagent.explore.milestone",
            "decision": "expand query",
            "findings_count": 3,
            "iterations_used": 2,
            "task_scope": ("functions.task:1", "explore"),
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert lines[0].icon == "⚙"
        assert lines[0].content == "Task(explore):#1 expand query (3 findings, 2 iter)"

    def test_subagent_judgement_shown_at_normal(self) -> None:
        """Judgement wire types are not routed through the curated pipeline."""
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.subagent.research.judgement",
            "judgement": "Need more sources: statistics gap",
            "action": "continue",
        }
        lines = pipeline.process(event)

        assert len(lines) == 0

    def test_subagent_step_hidden_for_internal(self) -> None:
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.subagent.research.step",
            "step_type": "reasoning",  # Not a query/analyze type
            "action": "thinking",
        }
        lines = pipeline.process(event)

        assert len(lines) == 0

    def test_goal_start_and_completion_both_emit_lines(self) -> None:
        """Fixed UX ceiling shows goal header and completion (no quiet/normal split)."""
        lines_done = StreamDisplayPipeline().process(
            {
                "type": "soothe.cognition.agent_loop.completed",
                "goal": "test",
                "total_steps": 3,
            }
        )
        assert len(lines_done) == 1

        lines_start = StreamDisplayPipeline().process(
            {
                "type": "soothe.cognition.agent_loop.started",
                "goal": "test",
            }
        )
        assert len(lines_start) == 1

    def test_goal_completion(self) -> None:
        pipeline = StreamDisplayPipeline()
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
        pipeline = StreamDisplayPipeline()

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
        """Wire ``*.completed`` without task_scope renders (IG-340 suppresses when scoped)."""
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.subagent.research.completed",
            "result_count": 5,
            "answer_length": 1200,
            "duration_s": 45.2,
        }
        lines = pipeline.process(event)

        assert len(lines) == 1
        assert "1200 chars" in lines[0].content
        assert lines[0].duration_ms == 45200

    def test_explore_completed_includes_search_target_in_done_line(self) -> None:
        """IG-340: Wire completed event suppressed when task_scope is present.

        The task ToolMessage result path produces the authoritative completion
        line, so the curated wire event is redundant when inside a Task scope.
        """
        pipeline = StreamDisplayPipeline()
        event = {
            "type": "soothe.subagent.explore.completed",
            "total_findings": 2,
            "duration_s": 12.0,
            "search_target": "Count README files",
            "task_scope": ("functions.task:0", "explore"),
        }
        lines = pipeline.process(event)
        assert len(lines) == 0  # Suppressed to avoid duplicate with task ToolMessage result

    def test_explore_completed_without_task_scope_still_shown(self) -> None:
        """IG-340: Without task_scope, wire completed event renders normally."""
        pipeline = StreamDisplayPipeline()
        event = {
            "type": "soothe.subagent.explore.completed",
            "total_findings": 2,
            "duration_ms": 12000,
            "search_target": "Count README files",
        }
        lines = pipeline.process(event)
        assert len(lines) == 1
        assert "Completed" in lines[0].content

    def test_loop_agent_reason_shown_at_normal(self) -> None:
        """IG-225: Loop agent Reason event shows judgement + plan reasoning."""
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.cognition.agent_loop.reasoned",
            "status": "continue",
            "progress": 0.5,
            "confidence": 0.8,
            "next_action": "I'll check your config files next.",
            "iteration": 1,
            "assessment_reasoning": "Progress looks good",
            "plan_reasoning": "Continue checking files",
        }
        lines = pipeline.process(event)

        # IG-257: Only show 2 lines: judgement + plan (assessment removed)
        assert len(lines) == 2
        assert "I'll check your config files next." in lines[0].content
        assert "Continue checking files" in lines[1].content
        # IG-257: No "Plan:" prefix, just emoji + text
        assert "Plan:" not in lines[1].content
        # RFC-603: Percentage display removed per user request
        assert "80% sure" not in lines[0].content
        assert lines[0].icon == "○"
        # IG-225: Plan uses level=2 (flat, no indent)
        assert lines[1].indent == ""

    def test_loop_agent_reason_done_shows_checkmark(self) -> None:
        """IG-225: Reason event with status=done shows checkmark and plan reasoning."""
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.cognition.agent_loop.reasoned",
            "status": "done",
            "progress": 1.0,
            "confidence": 0.95,
            "next_action": "I'm sharing the final result now.",
            "iteration": 3,
            "assessment_reasoning": "Goal is complete",
            "plan_reasoning": "Share results",
        }
        lines = pipeline.process(event)

        # IG-257: Only show 2 lines for done status: judgement + plan
        assert len(lines) == 2
        assert "I'm sharing the final result now." in lines[0].content
        assert "Share results" in lines[1].content
        # IG-257: No "Plan:" prefix
        assert "Plan:" not in lines[1].content
        # RFC-603: Percentage display removed per user request
        assert "95% sure" not in lines[0].content
        assert lines[0].icon == "●"  # Solid bullet for done status
        # IG-225: Plan uses level=2 (flat, no indent)
        assert lines[1].indent == ""

    def test_default_goal_achieved_skips_redundant_reasoning(self) -> None:
        """IG-265: Skip redundant reasoning line for default "Goal achieved successfully"."""
        pipeline = StreamDisplayPipeline()

        event = {
            "type": "soothe.cognition.agent_loop.reasoned",
            "status": "done",
            "progress": 1.0,
            "confidence": 1.0,
            "next_action": "Goal achieved successfully",
            "iteration": 2,
            "plan_action": "keep",
        }
        lines = pipeline.process(event)

        # IG-265: Should show only 1 line (judgement), skip duplicate reasoning
        assert len(lines) == 1
        assert "Goal achieved successfully" in lines[0].content
        # IG-265: Badge removed from CLI display (kept in event data for logs)
        assert "[keep]" not in lines[0].content
        # No second 💭 line (skip duplicate)
        assert len([line for line in lines if "💭" in line.content]) == 0

    def test_step_completed_with_tool_call_count(self) -> None:
        """IG-333: Step completion line includes description and tool metadata."""
        pipeline = StreamDisplayPipeline()
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
        assert lines[0].content == f"{_STEP_DONE_MARK} Explore project structure (done, 5 tools)"
        assert lines[0].icon == "●"
        assert lines[0].indent == ""
        assert lines[0].duration_ms == 1500

    def test_step_completed_without_tool_calls(self) -> None:
        """Step completion without tools omits tool suffix."""
        pipeline = StreamDisplayPipeline()
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
        assert lines[0].content == f"{_STEP_DONE_MARK} Analyze config (done)"
        assert lines[0].icon == "●"

    def test_step_completed_suppresses_when_no_description(self) -> None:
        """No redundant ● Step (done) when completion arrives without step context."""
        pipeline = StreamDisplayPipeline()
        pipeline.process({"type": "soothe.cognition.agent_loop.started", "goal": "test"})

        lines = pipeline.process(
            {
                "type": "soothe.cognition.agent_loop.step.completed",
                "step_id": "orphan",
                "success": True,
                "duration_ms": 38000,
                "tool_call_count": 1,
            }
        )

        assert lines == []

    def test_step_completed_uses_tracked_description_by_step_id(self) -> None:
        """Pipeline resolves description by step_id for parallel step tracking."""
        pipeline = StreamDisplayPipeline()

        pipeline.process(
            {
                "type": "soothe.cognition.plan.step.started",
                "step_id": "step_a",
                "description": "Search root directory",
            }
        )
        pipeline.process(
            {
                "type": "soothe.cognition.plan.step.started",
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
        assert lines[0].content == f"{_STEP_DONE_MARK} Search root directory (done, 2 tools)"
        assert lines[0].icon == "●"

    def test_loop_agent_reason_deduped_in_short_window(self) -> None:
        """IG-225: Duplicate reason events show lines on first call only."""
        pipeline = StreamDisplayPipeline()
        event = {
            "type": "soothe.cognition.agent_loop.reasoned",
            "status": "continue",
            "progress": 0.4,
            "confidence": 0.8,
            "next_action": "I'm searching for README files.",
            "iteration": 1,
            "assessment_reasoning": "Progress check",
            "plan_reasoning": "Continue search",
        }

        lines1 = pipeline.process(event)
        lines2 = pipeline.process(event)
        # IG-257: First call shows 2 lines (judgement + plan, assessment removed)
        assert len(lines1) == 2
        # Second call should be deduped (no lines)
        assert lines2 == []

    def test_capability_browser_step_renders_at_normal_verbosity(self) -> None:
        """Browser step.completed wire events are NORMAL tier — visible at normal."""
        pipeline = StreamDisplayPipeline()
        event = {
            "type": "soothe.subagent.browser.step.completed",
            "step_index": 3,
            "url": "https://example.com/news",
            "action_preview": "scroll",
            "title": "News",
            "status": "running",
        }
        lines = pipeline.process(event)
        assert len(lines) == 1
        assert "scroll" in lines[0].content
