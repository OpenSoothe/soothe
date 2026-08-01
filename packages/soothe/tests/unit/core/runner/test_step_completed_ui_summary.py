"""UI summary for step_completed must not treat recoverable tool errors as failures."""

from __future__ import annotations

from soothe.runner._runner_strange_loop import _step_completed_ui_summary


def test_success_keeps_done_preview_despite_recoverable_error() -> None:
    summary = _step_completed_ui_summary(
        {
            "success": True,
            "output_preview": "Done [67 tools]",
            "error": "Error: No files matched pattern '**/MSE-01*'",
        }
    )
    assert summary == "Done [67 tools]"


def test_failure_prefers_error_text() -> None:
    summary = _step_completed_ui_summary(
        {
            "success": False,
            "output_preview": "Failed",
            "error": "All tool calls failed",
        }
    )
    assert summary == "Error: All tool calls failed"


def test_success_without_preview_defaults_to_done() -> None:
    assert _step_completed_ui_summary({"success": True}) == "Done"
