"""Tests for structured plan parser (IG-433)."""

from soothe.sloop.cognition.parser import parse_plan_from_text


def test_regex_still_works_sync() -> None:
    plan = parse_plan_from_text("Goal", "**Step 1: Alpha**")
    assert plan.steps[0].description == "Alpha"
