"""Tests for RFC-214 user message envelopes."""

from __future__ import annotations

from soothe.core.prompts.user_envelope import (
    build_execute_step_envelope,
    build_plan_context_envelope,
)


def test_execute_envelope_includes_response_language_hint() -> None:
    envelope = build_execute_step_envelope(
        goal="请总结项目",
        step_description="Read README",
        execution_hints=None,
    )
    assert "<response_language_hint>" in envelope
    assert "same natural language as the user's goal" in envelope
    assert "<CONTEXT_INFO>" in envelope


def test_execute_envelope_strips_trailing_iteration_suffix_from_goal() -> None:
    envelope = build_execute_step_envelope(
        goal="analyze why the exec interrupted. how to fix (iteration 1/99)",
        step_description="Do the thing",
        execution_hints=None,
    )
    assert (
        "<CURRENT_GOAL>\nanalyze why the exec interrupted. how to fix\n</CURRENT_GOAL>" in envelope
    )
    assert "(iteration 1/99)" not in envelope


def test_execute_envelope_slash_skill_surfaces_primary_query_first() -> None:
    """Long expanded goal + /skill: submission → USER_PRIMARY_QUERY before full context."""
    long_skill = "Skill: demo\n\n" + ("body line\n" * 40)
    envelope = build_execute_step_envelope(
        goal=long_skill,
        step_description="Run the planned step",
        goal_user_submission="/skill:demo summarize the README",
    )
    assert "<USER_PRIMARY_QUERY>" in envelope
    assert "summarize the README" in envelope
    assert "<FULL_GOAL_AND_SKILL_CONTEXT>" in envelope
    assert envelope.index("<USER_PRIMARY_QUERY>") < envelope.index("<FULL_GOAL_AND_SKILL_CONTEXT>")
    assert envelope.index("<FULL_GOAL_AND_SKILL_CONTEXT>") < envelope.index("<USER_QUERY>")


def test_plan_context_envelope_slash_skill_surfaces_primary_query() -> None:
    envelope = build_plan_context_envelope(
        goal="Skill: x\n\n" + "y" * 30,
        iteration=1,
        max_iterations=8,
        goal_user_submission="/skill:x fix the bug in auth",
    )
    assert "<USER_PRIMARY_QUERY>" in envelope
    assert "fix the bug in auth" in envelope
    assert "Execute iteration: 1/8" in envelope
    assert "<FULL_GOAL_AND_SKILL_CONTEXT>" in envelope
    assert envelope.startswith("<GOAL_PROGRESS>\n<USER_PRIMARY_QUERY>")


def test_plan_context_envelope_includes_response_language_hint() -> None:
    envelope = build_plan_context_envelope(
        goal="Résumé demandé",
        iteration=1,
        max_iterations=5,
    )
    assert "<response_language_hint>" in envelope
    assert "same natural language as the user's goal" in envelope
