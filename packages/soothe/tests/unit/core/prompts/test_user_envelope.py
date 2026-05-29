"""Tests for RFC-214 user message envelopes."""

from __future__ import annotations

from soothe.core.prompts.user_envelope import (
    build_execute_step_envelope,
    build_plan_context_envelope,
)


def test_execute_envelope_includes_response_language_hint() -> None:
    envelope = build_execute_step_envelope(
        "Read README",
        execution_hints=None,
    )
    assert "<response_language_hint>" in envelope
    assert "same natural language as the user's goal" in envelope
    assert "<CONTEXT_INFO>" in envelope


def test_execute_envelope_plain_goal_layout() -> None:
    envelope = build_execute_step_envelope(
        "Do the thing",
        execution_hints=None,
    )
    assert envelope.startswith("<USER_QUERY>")
    assert "<SKILL_CONTEXT>" not in envelope
    assert "<USER_PRIMARY_QUERY>" not in envelope
    assert "--- Context ---" in envelope
    assert envelope.index("</USER_QUERY>") < envelope.index("--- Context ---")


def test_execute_envelope_slash_skill_skill_context_after_user_query() -> None:
    """Skill reference only in SKILL_CONTEXT, same top-level shape as non-skill."""
    skill_ref = (
        "Skill: demo\n\n"
        "Skill folder: /skills/demo\n"
        "(Additional files may live under this directory — use filesystem tools to "
        "read them when SKILL.md is not sufficient.)\n\n" + ("body line\n" * 5)
    )
    envelope = build_execute_step_envelope(
        "Run the planned step",
        skill_context=skill_ref,
    )
    assert "<USER_PRIMARY_QUERY>" not in envelope
    assert "<FULL_GOAL_AND_SKILL_CONTEXT>" not in envelope
    assert "<SKILL_CONTEXT>" in envelope
    assert "Skill: demo" in envelope
    assert "Skill folder: /skills/demo" in envelope
    assert "User instruction" not in envelope
    uq = envelope.index("<USER_QUERY>")
    sk = envelope.index("<SKILL_CONTEXT>")
    ctx = envelope.index("--- Context ---")
    assert uq < sk < ctx


def test_plan_context_envelope_slash_skill_surfaces_primary_query() -> None:
    envelope = build_plan_context_envelope(
        goal="Skill: x\n\n" + "y" * 30,
        goal_user_submission="/skill:x fix the bug in auth",
    )
    assert "<USER_PRIMARY_QUERY>" in envelope
    assert "fix the bug in auth" in envelope
    assert "Execute iteration" not in envelope
    assert "<FULL_GOAL_AND_SKILL_CONTEXT>" in envelope
    assert envelope.startswith("<GOAL_PROGRESS>\n<USER_PRIMARY_QUERY>")


def test_plan_context_envelope_includes_response_language_hint() -> None:
    envelope = build_plan_context_envelope(
        goal="Résumé demandé",
    )
    assert "<response_language_hint>" in envelope
    assert "same natural language as the user's goal" in envelope


def test_plan_context_envelope_skill_reference_when_skill_context_provided() -> None:
    """skill_context param emits <SKILL_REFERENCE> block after GOAL_PROGRESS."""
    envelope = build_plan_context_envelope(
        goal="shanghai tomorrow",
        skill_context="Skill: weather\nSkill folder: /skills/weather\n\nWeather skill body here",
    )
    assert "<SKILL_REFERENCE>" in envelope
    assert "Weather skill body here" in envelope
    # SKILL_REFERENCE appears after GOAL_PROGRESS
    gp_idx = envelope.index("</GOAL_PROGRESS>")
    sr_idx = envelope.index("<SKILL_REFERENCE>")
    assert gp_idx < sr_idx


def test_plan_context_envelope_no_skill_reference_when_absent() -> None:
    """No <SKILL_REFERENCE> when skill_context is None or empty."""
    envelope = build_plan_context_envelope(goal="plain goal")
    assert "<SKILL_REFERENCE>" not in envelope
    envelope_empty = build_plan_context_envelope(goal="plain goal", skill_context="  ")
    assert "<SKILL_REFERENCE>" not in envelope_empty
