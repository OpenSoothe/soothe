"""Token budget tracking and display on step cards."""

from __future__ import annotations

from soothe_cli.tui.widgets.messages import CognitionStepMessage


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
