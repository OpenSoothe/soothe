"""Fatal loop errors must surface to the TUI via wire-visible events.

When the execute engine emits a ``fatal_error`` event (e.g. LLM API 403),
the runner must translate it into a ``soothe.error.general.failed`` custom
event and a ``StrangeLoopCompletedEvent`` with ``status="fatal"`` so the
TUI shows the actual error instead of a generic "Stream ended unexpectedly".
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.events import ERROR, STRANGE_LOOP_COMPLETED
from soothe.runner._runner_strange_loop import StrangeLoopMixin


class _BareStrangeLoopMixin(StrangeLoopMixin):
    """Minimal mixin host for ``_run_strange_loop`` unit tests."""

    def __init__(self) -> None:
        self._agent = MagicMock()
        self._planner = MagicMock()
        self._config = MagicMock()
        self._current_thread_id = "thread-1"
        self._client_loop_id_for_stream = "loop-1"
        self._intent_classifier = None
        self._materialize_core_agent = AsyncMock(return_value=self._agent)
        self.get_sloop_shared_pool = AsyncMock(return_value=None)


class _FatalErrorStrangeLoop:
    """Fake StrangeLoop that yields a single fatal_error event."""

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def run_with_progress(self, **_kwargs: Any):
        yield (
            "fatal_error",
            {
                "error": "Permission/authentication error",
                "step_id": "KWR-e21433f3",
            },
        )


def _extract_custom_data(chunks: list[tuple]) -> list[dict[str, Any]]:
    """Extract data dicts from custom-mode stream chunks."""
    return [
        chunk[2]
        for chunk in chunks
        if isinstance(chunk, tuple) and len(chunk) >= 3 and chunk[1] == "custom"
    ]


@pytest.mark.asyncio
async def test_fatal_error_surfaces_error_and_completion_events() -> None:
    """The runner must emit a soothe.error event and a fatal completion event."""
    mixin = _BareStrangeLoopMixin()
    heartbeat = MagicMock()
    heartbeat.stop = AsyncMock()

    with (
        patch(
            "soothe.sloop.strange_loop.StrangeLoop",
            _FatalErrorStrangeLoop,
        ),
        patch(
            "soothe.sloop.clarification.build_clarification_policy_for_runner",
            return_value=MagicMock(),
        ),
        patch(
            "soothe.runner._runner_strange_loop._start_loop_heartbeat",
            return_value=heartbeat,
        ),
    ):
        chunks = [
            c
            async for c in mixin._run_strange_loop(
                "build an autopilot engine",
                thread_id="t1",
            )
        ]

    custom_data = _extract_custom_data(chunks)

    # A soothe.error.general.failed event must be present with the error text.
    error_events = [d for d in custom_data if d.get("type") == ERROR]
    assert error_events, "Expected a soothe.error.general.failed event in output"
    assert error_events[0]["error"] == "Permission/authentication error", (
        f"Expected error text, got: {error_events[0].get('error')}"
    )

    # A strange_loop.completed event must be present with status="fatal".
    completed_events = [d for d in custom_data if d.get("type") == STRANGE_LOOP_COMPLETED]
    assert completed_events, "Expected a strange_loop.completed event in output"
    assert completed_events[0]["status"] == "fatal", (
        f"Expected status='fatal', got: {completed_events[0].get('status')}"
    )
