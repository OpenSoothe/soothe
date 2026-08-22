"""Smoke tests guarding the plan-mode prompt philosophy (ported from the old
planner subagent's solution-report design).

These pin that the plan-mode addendum and the synthesis system prompt encode
the old planner subagent's design tenets so a plan stays focused on the user's
request instead of always forcing a codebase-change template:

1. Solution report, not an investigation roadmap — "read / diagnose" steps are
   forbidden.
2. Task-kind awareness — Design principles / Architecture changes are optional
   so a trivial non-code task can omit them (no fake file paths).
3. A "Solution" section is required (the decided outcome), not just "Changes".
"""

from __future__ import annotations

from soothe.prompts.loader import load_prompt_fragment


def _addendum() -> str:
    return load_prompt_fragment("decompose/plan_mode_addendum.xml").render()


def _synthesis_system() -> str:
    return load_prompt_fragment("instructions/plan_synthesis_system.xml").render(user_goal="goal")


def test_addendum_framed_as_solution_report() -> None:
    """The addendum calls the deliverable a 'solution report', not just a plan."""
    text = _addendum()
    assert "solution report" in text.lower()
    assert "not an investigation roadmap" in text.lower()


def test_addendum_forbids_read_diagnose_as_changes() -> None:
    """Steps like 'read / diagnose / inspect' must be forbidden as Changes."""
    text = _addendum()
    lower = text.lower()
    assert "forbidden as steps" in lower
    assert "diagnose" in lower
    assert "investigate" in lower


def test_addendum_marks_optional_sections() -> None:
    """Design principles and Architecture changes must be optional (None-able)."""
    text = _addendum()
    assert "Design principles" in text
    assert "Architecture changes" in text
    assert "optional" in text.lower()
    # Trivial-task escape hatch so "count 1 to 5" doesn't invent file paths.
    assert "none" in text.lower()


def test_addendum_requires_solution_section() -> None:
    """A 'Solution' section is required (the decided outcome), not just Changes."""
    text = _addendum()
    assert "### Solution" in text
    assert "required" in text.lower()


def test_synthesis_prompt_mirrors_solution_report_philosophy() -> None:
    """The fallback synthesis prompt must match the same solution-report shape."""
    text = _synthesis_system()
    lower = text.lower()
    assert "solution report" in lower
    assert "### Solution" in text
    assert "### Goal" in text
    # Optional sections so a trivial task can omit them.
    assert "optional" in lower
    # No required codebase-only Context/Tests/Sequence sections.
    # (Sections may appear as examples, but they must not be required.)


def test_synthesis_prompt_scales_to_non_codebase_goals() -> None:
    """The synthesis prompt must allow omitting codebase-only sections for trivial tasks."""
    text = _synthesis_system()
    lower = text.lower()
    assert "scale the plan to the goal" in lower
    assert "non-code" in lower or "non-codebase" in lower
