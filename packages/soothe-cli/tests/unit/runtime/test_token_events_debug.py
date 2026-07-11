"""Tests for CLI token event debug tracing."""

from __future__ import annotations

import logging

from soothe_cli.runtime.token_events_debug import TokenEventTrace


def test_finish_turn_flags_missing_plan_phase_total(caplog) -> None:
    trace = TokenEventTrace()
    trace.note_plan_phase(label="Generating plan", total_tokens_used=None, has_total_field=False)
    trace.note_plan_phase(label="Generating plan", total_tokens_used=1200, has_total_field=True)

    with caplog.at_level(logging.DEBUG, logger="soothe_cli.token_events"):
        trace.finish_turn(
            loop_id="loop-1",
            baseline=0,
            goal_run=1200,
            display_total=1200,
            turn_input=0,
            turn_output=0,
            approximate=False,
        )

    summary = next(r for r in caplog.records if "turn summary" in r.message)
    assert "status=anomaly" in summary.message
    assert "plan_phase missing total_tokens_used" in summary.message


def test_finish_turn_ok_when_stream_and_backend_present(caplog) -> None:
    trace = TokenEventTrace()
    trace.note_stream_usage(input_tokens=100, output_tokens=50, total_tokens=150)
    trace.note_step_completed(step_id="S1", total_tokens_used=150, has_total_field=True)

    with caplog.at_level(logging.DEBUG, logger="soothe_cli.token_events"):
        trace.finish_turn(
            loop_id="loop-1",
            baseline=0,
            goal_run=150,
            display_total=150,
            turn_input=100,
            turn_output=50,
            approximate=False,
        )

    summary = next(r for r in caplog.records if "turn summary" in r.message)
    assert "status=ok" in summary.message
