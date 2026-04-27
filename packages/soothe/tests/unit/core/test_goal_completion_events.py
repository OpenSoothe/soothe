"""Wire-contract tests for IG-273 goal completion events.

Covers:
- ``AgenticLoopCompletedEvent`` exposes ``goal_completion_message`` (IG-273).
- ``AutonomousGoalCompletionEvent`` emits the canonical
  ``soothe.output.autonomous.goal_completion.reported`` type string.
- The SDK re-exports ``AUTONOMOUS_GOAL_COMPLETION`` and ``GOAL_COMPLETION_STREAMING``.
"""

from __future__ import annotations

from soothe.core.event_catalog import (
    AgenticLoopCompletedEvent,
    AutonomousGoalCompletionEvent,
)


def test_agentic_loop_completed_event_goal_completion_message_field() -> None:
    ev = AgenticLoopCompletedEvent(
        thread_id="t-1",
        status="done",
        goal_progress=1.0,
        evidence_summary="ev",
        goal_completion_message="All done. Here is the answer.",
    )
    d = ev.to_dict()
    assert d["type"] == "soothe.cognition.agent_loop.completed"
    assert d["goal_completion_message"] == "All done. Here is the answer."


def test_agentic_loop_completed_event_none_when_unset() -> None:
    ev = AgenticLoopCompletedEvent(
        thread_id="t-3",
        status="done",
        goal_progress=1.0,
        evidence_summary="ev",
    )
    d = ev.to_dict()
    # ``to_dict`` uses ``exclude_none=True``; the field should be absent
    # when the producer did not supply it.
    assert "goal_completion_message" not in d


def test_autonomous_goal_completion_event_emits_canonical_type_string() -> None:
    ev = AutonomousGoalCompletionEvent(
        goal_id="g-1",
        description="Write report",
        status="completed",
        summary="Here is the summary.",
    )
    d = ev.to_dict()
    assert d["type"] == "soothe.output.autonomous.goal_completion.reported"
    assert d["summary"] == "Here is the summary."


def test_sdk_public_reexports_goal_completion_streaming_and_autonomous_goal_completion() -> None:
    from soothe_sdk.core import (
        AUTONOMOUS_GOAL_COMPLETION,
        GOAL_COMPLETION_STREAMING,
    )

    assert GOAL_COMPLETION_STREAMING == "soothe.output.goal_completion.streaming"
    assert AUTONOMOUS_GOAL_COMPLETION == "soothe.output.autonomous.goal_completion.reported"
