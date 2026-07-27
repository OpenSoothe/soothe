"""Token budget tracking and display on step cards."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe_cli.tui import theme
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def _mock_theme_colors() -> MagicMock:
    colors = MagicMock()
    colors.warning = "#ff0000"
    colors.cognition = "#00ff00"
    return colors


def _extract_content_text(content: object) -> str:
    if hasattr(content, "plain"):
        return content.plain
    return str(content)


def test_record_token_usage_accumulates() -> None:
    card = CognitionStepMessage("TKN-01", "Run analysis", id="stp-tkn")
    assert card._input_tokens == 0
    assert card._output_tokens == 0

    card.record_token_usage(100, 50)
    assert card._input_tokens == 100
    assert card._output_tokens == 50

    card.record_token_usage(200, 75)
    assert card._input_tokens == 300
    assert card._output_tokens == 125


def test_token_budget_suffix_empty_when_no_tokens() -> None:
    card = CognitionStepMessage("TKN-02", "Empty", id="stp-tkn-empty")
    assert card._token_budget_suffix() == ""


def test_token_budget_suffix_formats_counts() -> None:
    card = CognitionStepMessage("TKN-03", "Format", id="stp-tkn-fmt")
    card.record_token_usage(1500, 300)
    suffix = card._token_budget_suffix()
    assert suffix == " · in:1.5K out:300"


def test_token_budget_suffix_formats_large_counts() -> None:
    card = CognitionStepMessage("TKN-04", "Large", id="stp-tkn-large")
    card.record_token_usage(2_500_000, 100_000)
    suffix = card._token_budget_suffix()
    assert suffix == " · in:2.5M out:100.0K"


def test_token_budget_suffix_input_only() -> None:
    card = CognitionStepMessage("TKN-05", "InputOnly", id="stp-tkn-in")
    card.record_token_usage(500, 0)
    suffix = card._token_budget_suffix()
    assert "in:500" in suffix
    assert "out:0" in suffix


def test_token_budget_suffix_output_only() -> None:
    card = CognitionStepMessage("TKN-06", "OutputOnly", id="stp-tkn-out")
    card.record_token_usage(0, 200)
    suffix = card._token_budget_suffix()
    assert "in:0" in suffix
    assert "out:200" in suffix


def test_record_token_usage_refreshes_running_status_line() -> None:
    """Token counts appear in the running status line immediately, like tool stats."""
    card = CognitionStepMessage("TKN-07", "Token stats", id="stp-tkn-run")
    card._status = "running"
    card._start_time = 0.0
    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget

    with patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()):
        card.record_token_usage(1200, 340)

    assert mock_status_widget.update.called
    text = _extract_content_text(mock_status_widget.update.call_args[0][0])
    assert "in:1.2K" in text
    assert "out:340" in text
    assert "Running..." in text


def test_subagent_completion_status_includes_token_suffix() -> None:
    """Task (SubAgent) cards show token usage on the completion footer."""
    from soothe_cli.tui.widgets.messages.cognition_subagent import create_subagent_card

    card = create_subagent_card(
        step_id="ZCH-01",
        description="Scan repo",
        subagent_type="deep_research",
        task_idx=0,
        id="subagent-tokens",
    )
    card.record_token_usage(900, 120)
    card._status_widget = MagicMock()
    card._detail_widget = MagicMock()
    card.set_complete(True, 5000, 2, "Done")
    text = _extract_content_text(card._status_widget.update.call_args[0][0])
    assert "in:900" in text
    assert "out:120" in text
