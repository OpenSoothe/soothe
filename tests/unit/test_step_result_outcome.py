"""Unit tests for StepResult outcome metadata (RFC-211).

Tests that StepResult correctly uses outcome metadata instead of output field.
"""

from soothe.cognition.loop_agent.schemas import StepResult


def test_step_result_no_output_field():
    """StepResult should not have 'output' field (RFC-211)."""
    result = StepResult(
        step_id="test_step",
        success=True,
        outcome={"type": "file_read", "tool_name": "read_file", "size_bytes": 1024},
        duration_ms=100,
        thread_id="test_thread",
    )

    # Should not have output attribute
    assert not hasattr(result, "output"), "StepResult should not have 'output' field"

    # Should have outcome attribute
    assert hasattr(result, "outcome"), "StepResult must have 'outcome' field"
    assert result.outcome["type"] == "file_read"


def test_step_result_to_evidence_string_file_read():
    """Test evidence string generation for file_read outcome."""
    result = StepResult(
        step_id="step1",
        success=True,
        outcome={
            "type": "file_read",
            "tool_name": "read_file",
            "success_indicators": {"lines": 100, "files_found": 2},
            "entities": ["src/main.py", "src/utils.py"],
        },
        duration_ms=100,
        thread_id="thread1",
    )

    # Truncated evidence
    evidence_truncated = result.to_evidence_string(truncate=True)
    assert "✓" in evidence_truncated
    assert "100 lines" in evidence_truncated
    assert "2 files" in evidence_truncated

    # Full evidence
    evidence_full = result.to_evidence_string(truncate=False)
    assert "✓" in evidence_full
    assert "100 lines" in evidence_full


def test_step_result_to_evidence_string_web_search():
    """Test evidence string generation for web_search outcome."""
    result = StepResult(
        step_id="step2",
        success=True,
        outcome={
            "type": "web_search",
            "tool_name": "web_search",
            "success_indicators": {"results_count": 5},
            "entities": ["example.com", "test.org"],
        },
        duration_ms=200,
        thread_id="thread1",
    )

    evidence = result.to_evidence_string(truncate=True)
    assert "✓" in evidence
    assert "5 results" in evidence


def test_step_result_to_evidence_string_error():
    """Test evidence string generation for failed step."""
    result = StepResult(
        step_id="step3",
        success=False,
        outcome={"type": "error", "error": "File not found"},
        error="File not found",
        error_type="execution",
        duration_ms=50,
        thread_id="thread1",
    )

    evidence = result.to_evidence_string()
    assert "✗" in evidence
    assert "Error" in evidence
    assert "File not found" in evidence


def test_step_result_to_evidence_string_generic():
    """Test evidence string generation for generic outcome."""
    result = StepResult(
        step_id="step4",
        success=True,
        outcome={
            "type": "generic",
            "tool_name": "unknown_tool",
            "size_bytes": 512,
        },
        duration_ms=150,
        thread_id="thread1",
    )

    evidence = result.to_evidence_string()
    assert "✓" in evidence
    assert "512 bytes" in evidence or "unknown_tool" in evidence


def test_step_result_outcome_metadata_structure():
    """Test that outcome metadata has correct structure."""
    result = StepResult(
        step_id="step5",
        success=True,
        outcome={
            "type": "file_read",
            "tool_name": "ls",
            "tool_call_id": "call_123",
            "success_indicators": {"lines": 50, "files_found": 3},
            "entities": ["src/", "tests/", "docs/"],
            "size_bytes": 2048,
        },
        duration_ms=100,
        thread_id="thread1",
    )

    # Verify outcome structure
    assert result.outcome["type"] == "file_read"
    assert result.outcome["tool_name"] == "ls"
    assert result.outcome["tool_call_id"] == "call_123"
    assert result.outcome["success_indicators"]["lines"] == 50
    assert len(result.outcome["entities"]) == 3
    assert result.outcome["size_bytes"] == 2048
