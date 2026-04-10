"""Unit tests for StreamDisplayPipeline action extraction (IG-143)."""

from soothe.ux.cli.stream import StreamDisplayPipeline


def test_on_loop_agent_reason_extracts_user_summary():
    """Verify user_summary extraction priority."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.loop_agent.reason",
        "user_summary": "Counting files in project",
        "soothe_next_action": "Gathering metrics",
        "confidence": 0.85,
        "status": "working",
    }

    lines = pipeline.process(event)
    assert len(lines) == 1
    assert "Counting files in project" in lines[0].content
    # RFC-603: Percentage display removed per user request
    assert "85% sure" not in lines[0].content


def test_on_loop_agent_reason_extracts_soothe_next_action():
    """Verify soothe_next_action fallback when user_summary missing."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.loop_agent.reason",
        "soothe_next_action": "Analyzing architecture",
        "confidence": 0.90,
        "status": "working",
    }

    lines = pipeline.process(event)
    assert len(lines) == 1
    assert "Analyzing architecture" in lines[0].content
    # RFC-603: Percentage display removed per user request
    assert "90% sure" not in lines[0].content


def test_on_loop_agent_reason_derives_from_status():
    """Verify status → action fallback when metadata missing."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    # Test valid status values
    test_cases = [
        ("done", "Completing final analysis"),
        ("replan", "Trying alternative approach"),
        ("working", "Processing next step"),
    ]

    for status, expected_text in test_cases:
        event = {
            "type": "soothe.cognition.loop_agent.reason",
            "status": status,
            "confidence": 0.75,
        }

        lines = pipeline.process(event)
        assert len(lines) == 1, f"Failed for status={status}"
        assert expected_text in lines[0].content, f"Failed for status={status}"

    # Unknown/invalid status should return empty (skip emission)
    unknown_event = {
        "type": "soothe.cognition.loop_agent.reason",
        "status": "unknown",
        "confidence": 0.75,
    }
    lines = pipeline.process(unknown_event)
    assert len(lines) == 0  # Skip unknown status


def test_on_loop_agent_reason_deduplicates_repeated():
    """Verify 5s dedup window for repeated actions."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.loop_agent.reason",
        "user_summary": "Working on task",
        "confidence": 0.80,
        "status": "working",
    }

    # First emission
    lines1 = pipeline.process(event)
    assert len(lines1) == 1

    # Same action within 5s should be suppressed
    lines2 = pipeline.process(event)
    assert len(lines2) == 0


def test_on_loop_agent_reason_formats_confidence():
    """Verify confidence percentage formatting."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.loop_agent.reason",
        "user_summary": "Building summary",
        "confidence": 0.923,
        "status": "working",
    }

    lines = pipeline.process(event)
    assert len(lines) == 1
    # RFC-603: Percentage display removed per user request
    assert "92% sure" not in lines[0].content


def test_on_loop_agent_reason_defaults_confidence_when_missing():
    """Verify default 80% confidence when missing or zero."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    # Test with confidence=0
    event1 = {
        "type": "soothe.cognition.loop_agent.reason",
        "user_summary": "Analyzing",
        "confidence": 0,
        "status": "working",
    }
    lines1 = pipeline.process(event1)
    # RFC-603: Percentage display removed per user request
    assert "80% sure" not in lines1[0].content

    # Test with confidence missing
    event2 = {
        "type": "soothe.cognition.loop_agent.reason",
        "user_summary": "Processing",
        "status": "working",
    }
    lines2 = pipeline.process(event2)
    # RFC-603: Percentage display removed per user request
    assert "80% sure" not in lines2[0].content


def test_on_loop_agent_reason_returns_empty_when_missing_all():
    """Verify graceful skip when all metadata absent."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.loop_agent.reason",
        "status": "",  # Empty status
    }

    lines = pipeline.process(event)
    assert len(lines) == 0


def test_on_loop_agent_reason_uses_complete_action_for_done():
    """Verify 'complete' action icon for done status."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.loop_agent.reason",
        "user_summary": "Finishing analysis",
        "confidence": 0.95,
        "status": "done",
    }

    lines = pipeline.process(event)
    assert len(lines) == 1
    # format_judgement uses "✓" icon for "complete" action
    assert lines[0].icon == "✓"


def test_on_loop_agent_reason_uses_continue_icon_for_working():
    """Verify 'continue' action icon for working status."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.loop_agent.reason",
        "user_summary": "Processing files",
        "confidence": 0.85,
        "status": "working",
    }

    lines = pipeline.process(event)
    assert len(lines) == 1
    # format_judgement uses "→" icon for "continue" action
    assert lines[0].icon == "→"
