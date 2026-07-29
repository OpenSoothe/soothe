"""Unit tests for plan artifact helpers (RFC-633 / IG-658)."""

from __future__ import annotations

from pathlib import Path

from soothe.sloop.plans.artifact import (
    parse_planner_subagent_review_answers,
    slugify_plan_name,
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


def test_parse_planner_subagent_review_answers() -> None:
    assert parse_planner_subagent_review_answers(("Approve", "looks good")) == (
        "approve",
        "looks good",
    )
    assert parse_planner_subagent_review_answers(("reject", "nope")) == ("reject", "nope")
    assert parse_planner_subagent_review_answers(("Please add error handling", "")) == (
        "comments",
        "Please add error handling",
    )
    assert parse_planner_subagent_review_answers(("More comments", "tighten scope")) == (
        "comments",
        "tighten scope",
    )
    assert parse_planner_subagent_review_answers(("More comments", "")) == ("comments", "")
    assert parse_planner_subagent_review_answers(("Approve", "")) == ("approve", "")
