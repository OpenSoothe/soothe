"""Tests for ``soothe.skills.budget`` (RFC-105)."""

from __future__ import annotations

from soothe_nano.skills.budget import format_skills_within_budget
from soothe_nano.skills.index import SkillIndexEntry


def _entry(
    name: str, description: str = "desc", *, when_to_use: str | None = None
) -> SkillIndexEntry:
    return SkillIndexEntry(
        name=name,
        description=description,
        tags="test",
        source="user",
        path="/tmp",
        mtime=0.0,
        when_to_use=when_to_use,
    )


class TestFormatSkillsWithinBudget:
    def test_full_listing_within_budget(self) -> None:
        entries = [_entry("a", "Alpha skill"), _entry("b", "Beta skill")]
        text, telemetry = format_skills_within_budget(
            entries, budget_chars=500, per_entry_cap_chars=250, min_per_entry_chars=20
        )
        assert "a" in text
        assert "b" in text
        assert telemetry["mode"] == "full"
        assert telemetry["included_count"] == 2

    def test_truncated_when_over_budget(self) -> None:
        entries = [_entry(f"skill_{i}", f"Description {i}" * 20) for i in range(20)]
        text, telemetry = format_skills_within_budget(
            entries, budget_chars=200, per_entry_cap_chars=250, min_per_entry_chars=20
        )
        assert telemetry["mode"] in ("truncated", "names_only")
        assert telemetry["included_count"] > 0

    def test_names_only_when_very_tight_budget(self) -> None:
        # With min_per_entry_chars=100 and budget=10, quota will be < min
        entries = [_entry("a", "Alpha"), _entry("b", "Beta"), _entry("c", "Gamma")]
        text, telemetry = format_skills_within_budget(
            entries, budget_chars=10, per_entry_cap_chars=250, min_per_entry_chars=100
        )
        assert telemetry["mode"] == "names_only"

    def test_empty_entries(self) -> None:
        text, telemetry = format_skills_within_budget(
            [], budget_chars=500, per_entry_cap_chars=250, min_per_entry_chars=20
        )
        assert text == ""
        assert telemetry["included_count"] == 0

    def test_when_to_use_included(self) -> None:
        entries = [_entry("a", "Alpha skill", when_to_use="Use for Python files")]
        text, telemetry = format_skills_within_budget(
            entries, budget_chars=500, per_entry_cap_chars=250, min_per_entry_chars=20
        )
        assert "Python" in text

    def test_per_entry_cap_truncates_description(self) -> None:
        long_desc = "A" * 500
        entries = [_entry("a", long_desc), _entry("b", "B" * 500)]
        # Small budget forces truncated mode, where cap applies
        text, telemetry = format_skills_within_budget(
            entries, budget_chars=100, per_entry_cap_chars=50, min_per_entry_chars=20
        )
        assert telemetry["mode"] in ("truncated", "names_only")
        assert long_desc not in text
