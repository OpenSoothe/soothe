"""Tests for ``soothe.relay.message`` short-circuit in EventProcessor (IG-335).

Verifies that when the Claude subagent emits translated LangChain messages on
the ``custom`` channel via the relay protocol, EventProcessor reroutes them
through the ``messages`` path so they render with the parent task's
``[Task(claude):<tcid>]`` scope binding established by IG-334.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soothe_cli.shared.event_processor import EventProcessor


@dataclass
class _RecordingRenderer:
    calls: list[tuple[str, tuple, dict]] = field(default_factory=list)

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        self.calls.append(
            (
                "on_assistant_text",
                (text,),
                {"is_main": is_main, "is_streaming": is_streaming, "task_scope": task_scope},
            )
        )

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,
        *,
        is_main: bool,
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        self.calls.append(
            (
                "on_tool_call",
                (name, args, tool_call_id),
                {"is_main": is_main, "task_scope": task_scope},
            )
        )

    def on_tool_result(
        self,
        name: str,
        result: str,
        tool_call_id: str,
        *,
        is_error: bool,
        is_main: bool,
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        self.calls.append(
            (
                "on_tool_result",
                (name, result, tool_call_id),
                {"is_error": is_error, "is_main": is_main, "task_scope": task_scope},
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


def _bind_namespace_to_task(processor: EventProcessor, namespace: tuple[str, ...]) -> None:
    """Simulate the parent main-graph emitting a ``task(subagent_type='claude')`` call.

    The subgraph ``namespace`` then binds to that task scope via
    ``_maybe_bind_task_namespace`` (IG-334), so subsequent relay messages on
    that namespace surface with ``task_scope=("tcid","claude")``.
    """
    processor._emit_tool_call_for_renderer(
        "task",
        {"description": "explore", "subagent_type": "claude"},
        "tcid",
        is_main=True,
        namespace=(),
    )
    processor._maybe_bind_task_namespace(namespace)


def _relay_event(message: dict[str, Any], namespace: list[str]) -> dict[str, Any]:
    return {
        "type": "event",
        "mode": "custom",
        "namespace": namespace,
        "data": {
            "type": "soothe.relay.message",
            "message": message,
            "metadata": {"lc_agent_name": "claude"},
        },
    }


class TestRelayRouting:
    def test_relay_assistant_text_renders_with_task_scope(self) -> None:
        renderer = _RecordingRenderer()
        processor = EventProcessor(renderer, verbosity="normal")
        _bind_namespace_to_task(processor, ("tools:abc",))

        processor.process_event(
            _relay_event(
                {
                    "type": "AIMessageChunk",
                    "id": "claude-ai-1",
                    "content": "exploring repository",
                },
                namespace=["tools:abc"],
            )
        )

        assistant_calls = [c for c in renderer.calls if c[0] == "on_assistant_text"]
        assert len(assistant_calls) == 1
        assert assistant_calls[0][1][0] == "exploring repository"
        assert assistant_calls[0][2]["task_scope"] == ("tcid", "claude")
        assert assistant_calls[0][2]["is_main"] is False

    def test_relay_tool_call_renders_with_task_scope(self) -> None:
        renderer = _RecordingRenderer()
        processor = EventProcessor(renderer, verbosity="normal")
        _bind_namespace_to_task(processor, ("tools:xyz",))

        processor.process_event(
            _relay_event(
                {
                    "type": "ai",
                    "id": "claude-tc-1",
                    "content": "",
                    "tool_calls": [
                        {
                            "name": "Read",
                            "args": {"file_path": "/tmp/x.md"},
                            "id": "tu-1",
                            "type": "tool_call",
                        }
                    ],
                },
                namespace=["tools:xyz"],
            )
        )

        # Filter out the parent ``task`` tool call (recorded by the binding helper).
        scoped_calls = [
            c for c in renderer.calls if c[0] == "on_tool_call" and c[2]["task_scope"] is not None
        ]
        assert len(scoped_calls) == 1
        assert scoped_calls[0][1][0] == "Read"
        assert scoped_calls[0][1][2] == "tu-1"
        assert scoped_calls[0][2]["task_scope"] == ("tcid", "claude")
        assert scoped_calls[0][2]["is_main"] is False

    def test_relay_tool_result_renders_with_task_scope(self) -> None:
        renderer = _RecordingRenderer()
        processor = EventProcessor(renderer, verbosity="normal")
        _bind_namespace_to_task(processor, ("tools:xyz",))

        processor.process_event(
            _relay_event(
                {
                    "type": "ai",
                    "id": "claude-tc-2",
                    "content": "",
                    "tool_calls": [
                        {
                            "name": "Read",
                            "args": {"file_path": "/tmp/x.md"},
                            "id": "tu-2",
                            "type": "tool_call",
                        }
                    ],
                },
                namespace=["tools:xyz"],
            )
        )
        processor.process_event(
            _relay_event(
                {
                    "type": "tool",
                    "id": None,
                    "name": "Read",
                    "tool_call_id": "tu-2",
                    "content": "ok",
                    "status": "success",
                },
                namespace=["tools:xyz"],
            )
        )

        result_calls = [c for c in renderer.calls if c[0] == "on_tool_result"]
        assert len(result_calls) == 1
        assert result_calls[0][1][2] == "tu-2"
        assert result_calls[0][2]["task_scope"] == ("tcid", "claude")
        assert result_calls[0][2]["is_error"] is False

    def test_relay_error_status_routes_through_messages(self) -> None:
        renderer = _RecordingRenderer()
        processor = EventProcessor(renderer, verbosity="normal")
        _bind_namespace_to_task(processor, ("tools:err",))

        processor.process_event(
            _relay_event(
                {
                    "type": "tool",
                    "id": None,
                    "name": "Edit",
                    "tool_call_id": "tu-err",
                    "content": "boom",
                    "status": "error",
                },
                namespace=["tools:err"],
            )
        )

        result_calls = [c for c in renderer.calls if c[0] == "on_tool_result"]
        assert len(result_calls) == 1
        assert result_calls[0][2]["is_error"] is True

    def test_relay_envelope_is_not_progress_event(self) -> None:
        renderer = _RecordingRenderer()
        processor = EventProcessor(renderer, verbosity="normal")
        _bind_namespace_to_task(processor, ("tools:abc",))

        processor.process_event(
            _relay_event(
                {
                    "type": "AIMessageChunk",
                    "id": "claude-ai-2",
                    "content": "hello",
                },
                namespace=["tools:abc"],
            )
        )

        progress_calls = [c for c in renderer.calls if c[0] == "on_progress_event"]
        assert progress_calls == []

    def test_malformed_relay_event_is_dropped_silently(self) -> None:
        renderer = _RecordingRenderer()
        processor = EventProcessor(renderer, verbosity="normal")

        processor.process_event(
            {
                "type": "event",
                "mode": "custom",
                "namespace": ["tools:abc"],
                "data": {"type": "soothe.relay.message"},
            }
        )

        assert renderer.calls == []
