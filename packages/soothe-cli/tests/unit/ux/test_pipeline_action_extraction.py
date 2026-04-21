"""Unit tests for StreamDisplayPipeline action extraction (IG-143)."""

from soothe_cli.cli.stream import StreamDisplayPipeline


def test_on_loop_agent_reason_extracts_next_action():
    """IG-225: Verify next_action extraction with split reasoning."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "next_action": "Gathering metrics",
        "confidence": 0.85,
        "status": "working",
        "assessment_reasoning": "Progress check",
        "plan_reasoning": "Continue gathering",
    }

    lines = pipeline.process(event)
    # IG-225: Should show 3 lines (judgement + assessment + plan)
    assert len(lines) == 3
    assert "Gathering metrics" in lines[0].content
    # RFC-603: Percentage display removed per user request
    assert "85% sure" not in lines[0].content
    assert "Assessment:" in lines[1].content
    assert "Plan:" in lines[2].content


def test_on_loop_agent_reason_derives_from_status():
    """IG-225: Verify status → action fallback when next_action missing."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    # Test valid status values
    test_cases = [
        ("done", "Completing final analysis"),
        ("replan", "Trying alternative approach"),
        ("working", "Processing next step"),
    ]

    for status, expected_text in test_cases:
        event = {
            "type": "soothe.cognition.agent_loop.reasoned",
            "status": status,
            "confidence": 0.75,
            "assessment_reasoning": "Progress check",
            "plan_reasoning": "Continue",
        }

        lines = pipeline.process(event)
        # IG-225: Should show 3 lines (judgement + assessment + plan)
        assert len(lines) == 3, f"Failed for status={status}"
        assert expected_text in lines[0].content, f"Failed for status={status}"

    # Unknown/invalid status should return empty (skip emission)
    unknown_event = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "status": "unknown",
        "confidence": 0.75,
    }
    lines = pipeline.process(unknown_event)
    assert len(lines) == 0  # Skip unknown status


def test_on_loop_agent_reason_deduplicates_repeated():
    """IG-225: Verify 5s dedup window for repeated actions."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "next_action": "Working on task",
        "confidence": 0.80,
        "status": "working",
        "assessment_reasoning": "Progress check",
        "plan_reasoning": "Continue working",
    }

    # First emission - IG-225: 3 lines
    lines1 = pipeline.process(event)
    assert len(lines1) == 3

    # Same action within 5s should be suppressed
    lines2 = pipeline.process(event)
    assert len(lines2) == 0


def test_on_loop_agent_reason_formats_confidence():
    """IG-225: Verify confidence percentage formatting."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "next_action": "Building summary",
        "confidence": 0.923,
        "status": "working",
        "assessment_reasoning": "Progress check",
        "plan_reasoning": "Continue building",
    }

    lines = pipeline.process(event)
    # IG-225: Should show 3 lines
    assert len(lines) == 3
    # RFC-603: Percentage display removed per user request
    assert "92% sure" not in lines[0].content


def test_on_loop_agent_reason_defaults_confidence_when_missing():
    """IG-225: Verify default 80% confidence when missing or zero."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    # Test with confidence=0
    event1 = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "next_action": "Analyzing",
        "confidence": 0,
        "status": "working",
        "assessment_reasoning": "Progress check",
        "plan_reasoning": "Continue analyzing",
    }
    lines1 = pipeline.process(event1)
    # IG-225: Should show 3 lines
    assert len(lines1) == 3
    # RFC-603: Percentage display removed per user request
    assert "80% sure" not in lines1[0].content

    # Test with confidence missing
    event2 = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "next_action": "Processing",
        "status": "working",
        "assessment_reasoning": "Progress check",
        "plan_reasoning": "Continue processing",
    }
    lines2 = pipeline.process(event2)
    # IG-225: Should show 3 lines
    assert len(lines2) == 3
    # RFC-603: Percentage display removed per user request
    assert "80% sure" not in lines2[0].content


def test_on_loop_agent_reason_returns_empty_when_missing_all():
    """IG-225: Verify graceful skip when all metadata absent."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "status": "",  # Empty status
    }

    lines = pipeline.process(event)
    assert len(lines) == 0


def test_on_loop_agent_reason_uses_complete_action_for_done():
    """IG-225: Verify 'complete' action icon for done status."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "next_action": "Finishing analysis",
        "confidence": 0.95,
        "status": "done",
        "assessment_reasoning": "Goal complete",
        "plan_reasoning": "Finalize results",
    }

    lines = pipeline.process(event)
    # IG-225: Should show 3 lines
    assert len(lines) == 3
    # format_judgement uses "✓" icon for "complete" action
    assert lines[0].icon == "✓"


def test_on_loop_agent_reason_uses_continue_icon_for_working():
    """IG-225: Verify 'continue' action icon for working status."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": "soothe.cognition.agent_loop.reasoned",
        "next_action": "Processing files",
        "confidence": 0.85,
        "status": "working",
        "assessment_reasoning": "Progress check",
        "plan_reasoning": "Continue processing",
    }

    lines = pipeline.process(event)
    # IG-225: Should show 3 lines
    assert len(lines) == 3
    # format_judgement uses "→" icon for "continue" action
    assert lines[0].icon == "→"
