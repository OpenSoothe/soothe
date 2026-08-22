"""Tests for plan-mode step-result extraction (extract-before-synthesize).

When the planning agent follows the plan-mode addendum and outputs the plan
as its final message (``## Plan: <title>``), ``node_plan_review`` extracts it
directly from the step result instead of making an LLM synthesis call.
"""

from __future__ import annotations

from soothe.sloop.plans.plan_mode_review import _PLAN_TITLE_RE


def _has_plan_marker(text: str) -> bool:
    return bool(_PLAN_TITLE_RE.search(text or ""))


def _extract_body(text: str) -> str:
    """Mirror the trim logic in ``_extract_plan_from_step_result``."""
    content = (text or "").strip()
    if not content or not _has_plan_marker(content):
        return ""
    match = _PLAN_TITLE_RE.search(content)
    if match and match.start() > 0:
        content = content[match.start() :].strip()
    return content


def test_marker_matches_standard_plan_title() -> None:
    assert _has_plan_marker("## Plan: Refactor auth\n\n### Goal\nfoo")


def test_marker_matches_indented_title() -> None:
    assert _has_plan_marker("  ## Plan: Refactor auth\nbody")


def test_marker_requires_title_text() -> None:
    # "## Plan:" with no title text after the colon must NOT match — the
    # agent produced an empty/malformed plan.
    assert not _has_plan_marker("## Plan:\nbody")


def test_marker_rejects_narration() -> None:
    assert not _has_plan_marker("Let me look at the auth files...\nNow I will check...")


def test_marker_rejects_empty() -> None:
    assert not _has_plan_marker("")


def test_marker_rejects_subheading_only() -> None:
    assert not _has_plan_marker("### Goal\nno plan title here")


def test_extract_returns_full_plan_when_well_formed() -> None:
    text = "## Plan: Refactor auth\n\n### Goal\nFix the token refresh bug.\n"
    body = _extract_body(text)
    assert body.startswith("## Plan: Refactor auth")
    assert "### Goal" in body


def test_extract_trims_leading_preface() -> None:
    # Agent occasionally emits a short prose lead-in despite the addendum.
    text = (
        "I've finished researching the codebase.\n## Plan: Refactor auth\n\n### Goal\nFix the bug."
    )
    body = _extract_body(text)
    assert body.startswith("## Plan: Refactor auth")
    assert "I've finished researching" not in body


def test_extract_returns_empty_when_no_marker() -> None:
    assert _extract_body("Let me check the files...") == ""
    assert _extract_body("") == ""
    assert _extract_body("### Goal\nno title") == ""


def test_extract_preserves_trailing_sections() -> None:
    text = (
        "## Plan: Add caching\n\n"
        "### Goal\nSpeed up reads.\n\n"
        "### Changes\n1. Add Redis client\n\n"
        "### Tests\nUpdate cache tests\n"
    )
    body = _extract_body(text)
    assert "### Changes" in body
    assert "### Tests" in body
    assert body.endswith("Update cache tests")


def test_extract_accepts_minimal_solution_report_without_context() -> None:
    """A trivial non-codebase plan (Goal/Solution/Changes, no Context) extracts.

    The new solution-report template makes Context/Tests/Sequence optional so a
    goal like "count from 1 to 5" doesn't force fake file paths. Extraction only
    requires the ``## Plan:`` marker — it must not reject a plan for omitting
    the old codebase-only sections.
    """
    text = (
        "## Plan: Count from 1 to 5\n\n"
        "### Goal\nPrint the numbers 1 through 5.\n\n"
        "### Solution\nOutput each integer in order.\n\n"
        "### Changes\n1. Print 1\n2. Print 2\n3. Print 3\n4. Print 4\n5. Print 5\n"
    )
    body = _extract_body(text)
    assert body.startswith("## Plan: Count from 1 to 5")
    assert "### Solution" in body
    assert "### Changes" in body
    # Old codebase-only sections are absent — and that's valid now.
    assert "### Context" not in body
    assert "### Tests" not in body
    assert "### Sequence" not in body
