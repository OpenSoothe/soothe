"""Unit tests for plan artifact helpers (RFC-633)."""

from __future__ import annotations

from pathlib import Path

from soothe.sloop.plans.artifact import (
    parse_plan_review_answers,
    slugify_plan_name,
    strip_empty_plan_sections,
    strip_plan_frontmatter,
    update_plan_artifact_status,
    write_plan_artifact,
)


def test_slugify_plan_name_from_heading() -> None:
    assert slugify_plan_name("# Continue Mermaid Flow\n\nbody") == "continue-mermaid-flow"


def test_strip_plan_frontmatter() -> None:
    raw = "---\nstatus: draft\n---\n\n# Plan\n\nBody.\n"
    assert strip_plan_frontmatter(raw) == "# Plan\n\nBody."
    assert strip_plan_frontmatter("# Already clean") == "# Already clean"


def test_write_and_update_plan_artifact(tmp_path: Path) -> None:
    path = write_plan_artifact(
        tmp_path,
        "# Plan\n\n1. Do the thing\n",
        title="Continue Mermaid Flow",
        goal_id="g1",
        loop_id="loop1",
        status="draft",
    )
    assert path.is_file()
    assert ".soothe/plans/" in str(path).replace("\\", "/")
    text = path.read_text(encoding="utf-8")
    assert "status: draft" in text
    assert "# Plan" in text
    update_plan_artifact_status(path, "approved")
    assert "status: approved" in path.read_text(encoding="utf-8")


def test_parse_plan_review_answers() -> None:
    assert parse_plan_review_answers(("Approve", "looks good")) == (
        "approve",
        "looks good",
    )
    assert parse_plan_review_answers(("reject", "nope")) == ("reject", "nope")
    assert parse_plan_review_answers(("Refine", "tighten scope")) == (
        "refine",
        "tighten scope",
    )
    # Free-text body (no action prefix) → refine with that text.
    assert parse_plan_review_answers(("Please add error handling", "")) == (
        "refine",
        "Please add error handling",
    )
    assert parse_plan_review_answers(("Reject", "tighten scope")) == ("reject", "tighten scope")
    assert parse_plan_review_answers(("Reject", "")) == ("reject", "")
    assert parse_plan_review_answers(("Approve", "")) == ("approve", "")


def test_strip_empty_plan_sections_removes_none_bodies() -> None:
    """Sections with a bare ``None`` / ``N/A`` body are removed."""
    plan = (
        "## Plan: Do the thing\n\n"
        "### Goal\nDo the thing.\n\n"
        "### Solution\nWe will do it.\n\n"
        "### Design principles\nNone\n\n"
        "### Architecture changes\nN/A\n\n"
        "### Changes\n1. Step one.\n\n"
        "### Risks & assumptions\nNone.\n\n"
        "### Open questions\n- None\n"
    )
    result = strip_empty_plan_sections(plan)
    assert "### Design principles" not in result
    assert "### Architecture changes" not in result
    assert "### Risks & assumptions" not in result
    assert "### Open questions" not in result
    # Required sections with real content are preserved.
    assert "### Goal" in result
    assert "### Solution" in result
    assert "### Changes" in result
    assert "1. Step one." in result


def test_strip_empty_plan_sections_preserves_real_content() -> None:
    """Sections with actual content (even short) are left untouched."""
    plan = (
        "## Plan: Fix bug\n\n"
        "### Goal\nFix the bug.\n\n"
        "### Solution\nPatch the file.\n\n"
        "### Risks & assumptions\nNone of the public API changes.\n\n"
        "### Changes\n1. Fix it.\n"
    )
    result = strip_empty_plan_sections(plan)
    # ``None of the public API changes`` is real content, not a placeholder.
    assert "### Risks & assumptions" in result
    assert "None of the public API changes" in result


def test_strip_empty_plan_sections_passthrough_clean_plan() -> None:
    """A plan with no placeholder sections is unchanged (trailing whitespace stripped)."""
    plan = (
        "## Plan: Count\n\n"
        "### Goal\nCount to five.\n\n"
        "### Solution\nOutput 1-5.\n\n"
        "### Changes\n1. Print numbers.\n"
    )
    assert strip_empty_plan_sections(plan) == plan.strip()


def test_strip_empty_plan_sections_empty_input() -> None:
    assert strip_empty_plan_sections("") == ""
    assert strip_empty_plan_sections("   ") == ""
