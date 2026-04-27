"""Unit tests for RFC-0019 unified event processing.

Tests EventProcessor with mock renderers to verify:
- Event routing to correct callbacks
- State management (deduplication, streaming)
- Plan event handling
- Error propagation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from soothe.core.event_catalog import PLAN_CREATED

from soothe_cli.shared.event_processor import EventProcessor
from soothe_cli.shared.processor_state import ProcessorState


@dataclass
class MockRenderer:
    """Mock renderer for testing that records all callback invocations."""

    calls: list[tuple[str, tuple, dict]] = field(default_factory=list)

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,
    ) -> None:
        self.calls.append(
            ("on_assistant_text", (text,), {"is_main": is_main, "is_streaming": is_streaming})
        )

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,
        *,
        is_main: bool,
    ) -> None:
        self.calls.append(("on_tool_call", (name, args, tool_call_id), {"is_main": is_main}))

    def on_tool_result(
        self,
        name: str,
        result: str,
        tool_call_id: str,
        *,
        is_error: bool,
        is_main: bool,
    ) -> None:
        self.calls.append(
            (
                "on_tool_result",
                (name, result, tool_call_id),
                {"is_error": is_error, "is_main": is_main},
            )
        )

    def on_status_change(self, state: str) -> None:
        self.calls.append(("on_status_change", (state,), {}))

    def on_error(self, error: str, *, context: str | None = None) -> None:
        self.calls.append(("on_error", (error,), {"context": context}))

    def on_progress_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        namespace: tuple[str, ...],
    ) -> None:
        self.calls.append(("on_progress_event", (event_type, data), {"namespace": namespace}))

    def on_plan_created(self, plan: Any) -> None:
        self.calls.append(("on_plan_created", (plan,), {}))

    def on_plan_step_started(self, step_id: str, description: str) -> None:
        self.calls.append(("on_plan_step_started", (step_id, description), {}))

    def on_plan_step_completed(
        self,
        step_id: str,
        success: bool,  # noqa: FBT001
        duration_ms: int,
    ) -> None:
        self.calls.append(("on_plan_step_completed", (step_id, success, duration_ms), {}))

    def on_turn_end(self) -> None:
        self.calls.append(("on_turn_end", (), {}))


class TestProcessorState:
    """Tests for ProcessorState dataclass."""

    def test_initial_state(self):
        """Test initial state values."""
        state = ProcessorState()
        assert state.seen_message_ids == set()
        assert state.pending_tool_calls == {}
        assert state.name_map == {}
        assert state.current_plan is None
        assert state.thread_id == ""
        assert state.multi_step_active is False

    def test_reset_turn(self):
        """Test reset_turn clears turn-specific state."""
        state = ProcessorState()
        state.pending_tool_calls["tc1"] = {"name": "test", "args_str": "{}", "emitted": False}
        state.seen_message_ids.add("msg1")
        state.multi_step_active = True

        state.reset_turn()

        assert state.pending_tool_calls == {}
        # seen_message_ids and multi_step_active preserved
        assert "msg1" in state.seen_message_ids
        assert state.multi_step_active is True

    def test_clear_session(self):
        """Test clear_session resets all session state."""
        state = ProcessorState()
        state.pending_tool_calls["tc1"] = {"name": "test"}
        state.seen_message_ids.add("msg1")
        state.multi_step_active = True
        state.current_plan = MagicMock()

        state.clear_session()

        assert state.pending_tool_calls == {}
        assert state.seen_message_ids == set()
        assert state.multi_step_active is False
        assert state.current_plan is None


class TestEventProcessorStatusHandling:
    """Tests for status event handling."""

    def test_status_event_calls_on_status_change(self):
        """Test status events route to on_status_change."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        processor.process_event({"type": "status", "state": "running", "thread_id": "t1"})

        assert ("on_status_change", ("running",), {}) in renderer.calls

    def test_status_idle_calls_on_turn_end(self):
        """Test idle status calls on_turn_end."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        processor.process_event({"type": "status", "state": "idle", "thread_id": "t1"})

        assert ("on_turn_end", (), {}) in renderer.calls

    def test_status_updates_thread_id(self):
        """Test status event updates processor thread_id."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        processor.process_event({"type": "status", "state": "running", "thread_id": "new-thread"})

        assert processor.thread_id == "new-thread"

    def test_thread_change_clears_session(self):
        """Test changing thread clears session state."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        # Setup initial thread
        processor.process_event({"type": "status", "state": "running", "thread_id": "t1"})
        processor._state.seen_message_ids.add("msg1")

        # Change thread
        processor.process_event({"type": "status", "state": "running", "thread_id": "t2"})

        assert processor._state.seen_message_ids == set()


class TestEventProcessorErrorHandling:
    """Tests for error event handling."""

    def test_error_event_calls_on_error(self):
        """Test error events route to on_error."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        processor.process_event(
            {"type": "error", "message": "Something went wrong", "code": "TEST_ERROR"}
        )

        assert ("on_error", ("Something went wrong",), {"context": "TEST_ERROR"}) in renderer.calls


class TestEventProcessorPlanHandling:
    """Tests for plan event handling."""

    def test_plan_created_event(self):
        """Test plan created event updates state and calls renderer."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        plan_data = {
            "type": PLAN_CREATED,
            "goal": "Test goal",
            "steps": [
                {"id": "1", "description": "Step 1"},
                {"id": "2", "description": "Step 2"},
            ],
        }

        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": plan_data,
            }
        )

        assert processor.current_plan is not None
        assert processor.current_plan.goal == "Test goal"
        assert len(processor.current_plan.steps) == 2
        # on_plan_created should be called
        plan_calls = [c for c in renderer.calls if c[0] == "on_plan_created"]
        assert len(plan_calls) == 1

    def test_multi_step_plan_sets_flag(self):
        """Test multi-step plan sets multi_step_active flag."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        plan_data = {
            "type": PLAN_CREATED,
            "goal": "Multi-step goal",
            "steps": [
                {"id": "1", "description": "Step 1"},
                {"id": "2", "description": "Step 2"},
            ],
        }

        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": plan_data,
            }
        )

        assert processor.multi_step_active is True

    def test_single_step_plan_no_flag(self):
        """Test single-step plan doesn't set multi_step_active."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        plan_data = {
            "type": PLAN_CREATED,
            "goal": "Single step",
            "steps": [{"id": "1", "description": "Only step"}],
        }

        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": plan_data,
            }
        )

        assert processor.multi_step_active is False


class TestEventProcessorOutputEventRouting:
    """Tests for output-event routing behavior."""

    def test_agent_loop_completed_routes_to_progress_event(self) -> None:
        """Agent-loop completion must flow through progress-event suppression path."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal")

        completion_event = {
            "type": "event",
            "mode": "custom",
            "namespace": [],
            "data": {
                "type": "soothe.cognition.agent_loop.completed",
                "thread_id": "t",
                "status": "done",
                "goal_progress": 1.0,
                "final_stdout_message": "# Final Report\n\n1\tline one",
            },
        }

        processor.process_event(completion_event)

        progress_calls = [c for c in renderer.calls if c[0] == "on_progress_event"]
        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert len(progress_calls) == 1
        assert progress_calls[0][1][0] == "soothe.cognition.agent_loop.completed"
        assert assistant_calls == []

    def test_chitchat_output_event_still_routes_to_assistant_text(self) -> None:
        """Non-agentic output events should keep existing fast-path behavior."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal")

        chitchat_event = {
            "type": "event",
            "mode": "custom",
            "namespace": [],
            "data": {
                "type": "soothe.output.chitchat.responded",
                "content": "Hello from chitchat",
            },
        }

        processor.process_event(chitchat_event)

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        progress_calls = [c for c in renderer.calls if c[0] == "on_progress_event"]
        assert len(assistant_calls) == 1
        assert assistant_calls[0][1][0] == "Hello from chitchat"
        assert progress_calls == []

    def test_batch_mode_emits_agent_loop_completed_output(self) -> None:
        """Batch mode should render final stdout from agent_loop.completed."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal", final_output_mode="batch")

        completion_event = {
            "type": "event",
            "mode": "custom",
            "namespace": [],
            "data": {
                "type": "soothe.cognition.agent_loop.completed",
                "status": "done",
                "goal_progress": 1.0,
                "final_stdout_message": "Batch final report content",
            },
        }

        processor.process_event(completion_event)

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        progress_calls = [c for c in renderer.calls if c[0] == "on_progress_event"]
        assert len(assistant_calls) == 1
        assert assistant_calls[0][1][0] == "Batch final report content"
        assert len(progress_calls) == 1
        # final_stdout_message is removed before progress callback to avoid duplicate emission in renderer
        assert "final_stdout_message" not in progress_calls[0][1][1]

    def test_batch_mode_suppresses_synthesis_streaming_chunks(self) -> None:
        """Batch mode should ignore streaming final-report chunks."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal", final_output_mode="batch")

        stream_event = {
            "type": "event",
            "mode": "custom",
            "namespace": [],
            "data": {
                "type": "soothe.output.synthesis.streaming",
                "content": "stream chunk",
                "is_chunk": True,
            },
        }

        processor.process_event(stream_event)

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert assistant_calls == []

    def test_streaming_mode_drops_completed_final_stdout_from_progress_payload(self) -> None:
        """Streaming mode should not pass final_stdout_message to progress renderer."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal", final_output_mode="streaming")

        completion_event = {
            "type": "event",
            "mode": "custom",
            "namespace": [],
            "data": {
                "type": "soothe.cognition.agent_loop.completed",
                "status": "done",
                "goal_progress": 1.0,
                "final_stdout_message": "Batch payload should be dropped in streaming mode",
            },
        }

        processor.process_event(completion_event)

        progress_calls = [c for c in renderer.calls if c[0] == "on_progress_event"]
        assert len(progress_calls) == 1
        assert "final_stdout_message" not in progress_calls[0][1][1]

    def test_streaming_final_report_preserves_markdown_chunk_boundaries(self) -> None:
        """Streaming markdown chunks should preserve whitespace/newlines exactly."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal", final_output_mode="streaming")

        chunk_1 = "# README Files Count Report\n\n## 1. Executive Summary\n\nThis report "
        chunk_2 = "documents the comprehensive count.\n\n## 2. Methodology\n"

        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": {
                    "type": "soothe.output.synthesis.streaming",
                    "content": chunk_1,
                    "is_chunk": True,
                },
            }
        )
        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": {
                    "type": "soothe.output.synthesis.streaming",
                    "content": chunk_2,
                    "is_chunk": True,
                },
            }
        )
        # Completion event still flows as progress but should not carry final stdout payload.
        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": {
                    "type": "soothe.cognition.agent_loop.completed",
                    "status": "done",
                    "goal_progress": 1.0,
                    "final_stdout_message": chunk_1 + chunk_2,
                },
            }
        )

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert len(assistant_calls) == 2
        assert assistant_calls[0][1][0] == chunk_1
        assert assistant_calls[1][1][0] == chunk_2
        assert assistant_calls[0][2]["is_streaming"] is True
        assert assistant_calls[1][2]["is_streaming"] is True

        progress_calls = [c for c in renderer.calls if c[0] == "on_progress_event"]
        assert len(progress_calls) == 1
        assert progress_calls[0][1][0] == "soothe.cognition.agent_loop.completed"
        assert "final_stdout_message" not in progress_calls[0][1][1]

    def test_streaming_final_report_preserves_boundaries_when_is_chunk_false(self) -> None:
        """synthesis.streaming should preserve boundaries even when is_chunk is false."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal", final_output_mode="streaming")

        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": {
                    "type": "soothe.output.synthesis.streaming",
                    "content": "# Report\n\n",
                    "is_chunk": False,
                },
            }
        )
        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": {
                    "type": "soothe.output.synthesis.streaming",
                    "content": "## Executive Summary\n\n",
                    "is_chunk": False,
                },
            }
        )

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert len(assistant_calls) == 2
        assert assistant_calls[0][1][0] == "# Report\n\n"
        assert assistant_calls[1][1][0] == "## Executive Summary\n\n"
        assert assistant_calls[0][2]["is_streaming"] is True
        assert assistant_calls[1][2]["is_streaming"] is True


class TestEventProcessorMessageDeduplication:
    """Tests for message deduplication."""

    def test_duplicate_message_ignored(self):
        """Test same message ID is not processed twice."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer)

        msg_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "AIMessage",
                    "id": "msg-123",
                    "content": "Hello world",
                },
                {},
            ],
        }

        processor.process_event(msg_event)
        initial_calls = len(renderer.calls)

        processor.process_event(msg_event)
        assert len(renderer.calls) == initial_calls  # No new calls


class TestEventProcessorVerbosityFiltering:
    """Tests for verbosity-based filtering."""

    def test_quiet_verbosity_filters_tool_activity(self):
        """Test quiet verbosity filters tool activity events."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="quiet")

        # This should be filtered by quiet verbosity
        tool_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "ToolMessage",
                    "name": "read_file",
                    "content": "file contents",
                    "tool_call_id": "tc1",
                },
                {},
            ],
        }

        processor.process_event(tool_event)

        tool_result_calls = [c for c in renderer.calls if c[0] == "on_tool_result"]
        assert len(tool_result_calls) == 0

    def test_normal_verbosity_shows_tool_result(self) -> None:
        """Default (normal) verbosity must surface tool stderr lines (not only detailed)."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal")

        tool_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "ToolMessage",
                    "name": "read_file",
                    "content": "file contents",
                    "tool_call_id": "tc-normal",
                },
                {},
            ],
        }

        processor.process_event(tool_event)

        tool_result_calls = [c for c in renderer.calls if c[0] == "on_tool_result"]
        assert len(tool_result_calls) == 1
        assert tool_result_calls[0][1][0] == "read_file"

    def test_tool_message_dict_status_error_sets_is_error(self) -> None:
        """Explicit ToolMessage status=error must set is_error even when content is benign."""
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal")

        tool_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "ToolMessage",
                    "name": "read_file",
                    "content": "ok",
                    "tool_call_id": "tc-err-status",
                    "status": "error",
                },
                {},
            ],
        }

        processor.process_event(tool_event)

        tool_result_calls = [c for c in renderer.calls if c[0] == "on_tool_result"]
        assert len(tool_result_calls) == 1
        assert tool_result_calls[0][2]["is_error"] is True

    def test_quiet_cleans_and_extracts_answer(self) -> None:
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="quiet")

        msg_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "AIMessage",
                    "id": "msg-quiet",
                    "content": "The capital of France is Paris. Let me know if you'd like more.",
                },
                {},
            ],
        }

        processor.process_event(msg_event)

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert assistant_calls
        # Decorative filler is removed, first sentence extracted
        assert assistant_calls[0][1][0] == "The capital of France is Paris."

    def test_normal_removes_decorative_filler_preserves_identity(self) -> None:
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal")

        msg_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "AIMessage",
                    "id": "msg-brand",
                    "content": (
                        "Bonjour! The capital of France is Paris. "
                        "I'm Soothe, created by Dr. Xiaming Chen, "
                        "and I'm happy to help you with any questions you have!"
                    ),
                },
                {},
            ],
        }

        processor.process_event(msg_event)

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert assistant_calls
        # Brand/creator language is preserved (no longer filtered)
        # Decorative filler ("I'm happy to help...") is still removed
        assert "The capital of France is Paris" in assistant_calls[0][1][0]
        assert "I'm Soothe" in assistant_calls[0][1][0]

    def test_quiet_extracts_bare_numeric_answer(self) -> None:
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="quiet")

        msg_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "AIMessage",
                    "id": "msg-quiet-numeric",
                    "content": "That's 42!",
                },
                {},
            ],
        }

        processor.process_event(msg_event)

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert assistant_calls
        assert assistant_calls[0][1][0] == "42"

    def test_quiet_extracts_numeric_result_from_equation(self) -> None:
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="quiet")

        msg_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "AIMessage",
                    "id": "msg-quiet-equation",
                    "content": "25 + 17 = 42",
                },
                {},
            ],
        }

        processor.process_event(msg_event)

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert assistant_calls
        assert assistant_calls[0][1][0] == "42"

    def test_normal_strips_light_embellishment_from_answer(self) -> None:
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal")

        msg_event = {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "AIMessage",
                    "id": "msg-normal-embellished",
                    "content": "The capital of France is Paris, a beautiful and historic city! 🇫🇷",
                },
                {},
            ],
        }

        processor.process_event(msg_event)

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert assistant_calls
        assert assistant_calls[0][1][0] == "The capital of France is Paris."

    def test_normal_filters_protocol_but_shows_plan_update(self) -> None:
        renderer = MockRenderer()
        processor = EventProcessor(renderer, verbosity="normal")

        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": {
                    "type": "soothe.protocol.context.projected",
                    "entries": 3,
                },
            }
        )
        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": [],
                "data": {
                    "type": PLAN_CREATED,
                    "goal": "Analyze codebase structure",
                    "steps": [{"id": "1", "description": "Inspect files"}],
                },
            }
        )

        progress_calls = [c for c in renderer.calls if c[0] == "on_progress_event"]
        assert progress_calls == []
        plan_calls = [c for c in renderer.calls if c[0] == "on_plan_created"]
        assert len(plan_calls) == 1
