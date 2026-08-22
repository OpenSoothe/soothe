"""Unit tests for Eval text recovery (RFC-905 fail-safe)."""

from __future__ import annotations

from soothe.sloop.eval.text_recovery import recover_proposals_from_text


def test_recover_from_markdown_fenced_json() -> None:
    """Subtasks in a markdown JSON fence are recovered."""
    text = (
        "I need to decompose the task because the previous step only scanned "
        "for dead code.\n\n"
        "```json\n"
        '{"subtasks": [\n'
        '  {"description": "Verify the flagged unused variables", "in_scope": true, "necessary_for_user_goal": true},\n'
        '  {"description": "Remove any confirmed dead code", "in_scope": true, "necessary_for_user_goal": true}\n'
        "]}\n"
        "```\n"
    )
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-1")
    assert len(proposals) == 1
    assert proposals[0].parent_step_id == "EVAL-1"
    assert len(proposals[0].subtasks) == 2
    assert proposals[0].subtasks[0].description == "Verify the flagged unused variables"
    assert proposals[0].subtasks[1].description == "Remove any confirmed dead code"


def test_recover_from_plain_json() -> None:
    """Subtasks as a bare JSON object (no fence) are recovered."""
    text = (
        "Based on my analysis, remaining work:\n"
        '{"subtasks": [{"description": "Run linters and tests"}]}'
    )
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-2")
    assert len(proposals) == 1
    assert len(proposals[0].subtasks) == 1
    assert proposals[0].subtasks[0].description == "Run linters and tests"


def test_missing_scope_defaults_true() -> None:
    """Subtasks without in_scope/necessary_for_user_goal default to True."""
    text = '{"subtasks": [{"description": "do work"}]}'
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-3")
    assert len(proposals) == 1
    sub = proposals[0].subtasks[0]
    assert sub.in_scope is True
    assert sub.necessary_for_user_goal is True


def test_no_json_returns_empty() -> None:
    """Text without any JSON returns empty list."""
    text = "The goal is complete. All dead code has been removed."
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-4")
    assert proposals == []


def test_empty_text_returns_empty() -> None:
    """Empty text returns empty list."""
    assert recover_proposals_from_text("", parent_step_id="EVAL-5") == []


def test_malformed_json_returns_empty() -> None:
    """Malformed JSON returns empty list without raising."""
    text = '{"subtasks": [{"description": "broken",}'
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-6")
    assert proposals == []


def test_no_subtasks_key_returns_empty() -> None:
    """JSON without a subtasks key returns empty list."""
    text = '{"coverage": "complete", "reasoning": "all good"}'
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-7")
    assert proposals == []


def test_empty_subtasks_array_returns_empty() -> None:
    """JSON with empty subtasks array returns empty list."""
    text = '{"subtasks": []}'
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-8")
    assert proposals == []


def test_subtask_missing_description_skipped() -> None:
    """Subtasks without a description are skipped; valid ones are kept."""
    text = '{"subtasks": [{"description": "valid task"},{"in_scope": true}]}'
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-9")
    assert len(proposals) == 1
    assert len(proposals[0].subtasks) == 1
    assert proposals[0].subtasks[0].description == "valid task"


def test_multiple_subtasks_preserve_order() -> None:
    """Multiple subtasks are recovered in order."""
    text = (
        '{"subtasks": ['
        '{"description": "first"},'
        '{"description": "second"},'
        '{"description": "third"}'
        "]}"
    )
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-10")
    assert len(proposals) == 1
    descs = [s.description for s in proposals[0].subtasks]
    assert descs == ["first", "second", "third"]


def test_json_after_prose_recovered() -> None:
    """JSON embedded after a paragraph of prose is recovered."""
    text = (
        "The previous step only identified dead code but did not remove it. "
        "I need to decompose to complete the goal.\n\n"
        '{"subtasks": [{"description": "Remove dead code", "in_scope": true, "necessary_for_user_goal": true}]}'
    )
    proposals = recover_proposals_from_text(text, parent_step_id="EVAL-11")
    assert len(proposals) == 1
    assert proposals[0].subtasks[0].description == "Remove dead code"
