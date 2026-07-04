"""Tests for structured turn event stats in cli.log."""

from __future__ import annotations

import json

from soothe_cli.runtime.state.session_stats import (
    TurnEventStats,
    TurnLatencyStats,
    build_goal_completed_log_event,
    build_turn_finished_log_event,
    format_cli_log_event,
)


def test_to_log_dict_omits_zero_counters() -> None:
    stats = TurnEventStats(total=10, messages=8, custom=2)
    assert stats.to_log_dict() == {
        "total": 10,
        "modes": {"messages": 8, "custom": 2},
    }


def test_to_log_dict_includes_activity_latency_and_degradation() -> None:
    stats = TurnEventStats(
        total=847,
        messages=612,
        updates=89,
        custom=146,
        tool_calls=42,
        tool_results=38,
        text_chunks=120,
        skipped=1,
        filtered_early=2,
        inbound_dropped=1,
        latency=TurnLatencyStats(
            time_to_first_chunk_ms=890.0,
            synthesis_visible_ms=11_200.0,
            goal_completion_applied=True,
        ),
    )
    payload = stats.to_log_dict()
    assert payload["total"] == 847
    assert payload["modes"] == {"messages": 612, "updates": 89, "custom": 146}
    assert payload["activity"] == {
        "tool_calls": 42,
        "tool_results": 38,
        "text_chunks": 120,
    }
    assert payload["degradation"] == {
        "skipped": 1,
        "filtered_early": 2,
        "inbound_dropped": 1,
    }
    assert payload["latency"] == {"ttfc_ms": 890, "synthesis_ms": 11200}


def test_build_goal_completed_log_event() -> None:
    stats = TurnEventStats(total=100, messages=80, custom=20, tool_calls=3)
    event = build_goal_completed_log_event(
        stats,
        status="done",
        goal_progress="complete",
        total_steps=5,
        elapsed_seconds=12.34,
    )
    assert event == {
        "event": "goal_completed",
        "status": "done",
        "progress": "complete",
        "steps": 5,
        "elapsed_s": 12.3,
        "events": {
            "total": 100,
            "modes": {"messages": 80, "custom": 20},
            "activity": {"tool_calls": 3},
        },
    }


def test_build_turn_finished_log_event() -> None:
    stats = TurnEventStats(total=12, messages=10, custom=2)
    event = build_turn_finished_log_event(stats, wall_seconds=8.76)
    assert event == {
        "event": "turn_finished",
        "wall_s": 8.8,
        "events": {
            "total": 12,
            "modes": {"messages": 10, "custom": 2},
        },
    }


def test_format_cli_log_event_is_compact_sorted_json() -> None:
    stats = TurnEventStats(total=100, messages=80, custom=20, tool_calls=3)
    line = format_cli_log_event(
        build_goal_completed_log_event(
            stats,
            status="done",
            goal_progress="complete",
            total_steps=5,
            elapsed_seconds=12.3,
        )
    )
    parsed = json.loads(line)
    assert parsed["event"] == "goal_completed"
    assert parsed["events"]["activity"]["tool_calls"] == 3
    assert line == json.dumps(parsed, separators=(",", ":"), sort_keys=True)
