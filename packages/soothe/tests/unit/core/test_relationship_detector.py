"""Tests for Autopilot relationship detector (soothe.cognition.relationship_detector)."""

from soothe.cognition import Goal
from soothe.cognition.goal_engine.relationship_detector import (
    _AUTO_APPLY_CONFIDENCE,
    _FLAG_FOR_REVIEW_CONFIDENCE,
    Relationship,
    _extract_artifact_refs,
    _significant_words,
    auto_apply_relationships,
    detect_relationships,
)


class TestSignificantWords:
    """Tests for stop word filtering."""

    def test_removes_stop_words(self) -> None:
        result = _significant_words("the cat and the dog are playing")
        assert "cat" in result
        assert "dog" in result
        assert "the" not in result
        assert "and" not in result
        assert "are" not in result

    def test_removes_punctuation(self) -> None:
        result = _significant_words("hello, world. test")
        assert "hello" in result
        assert "world" in result
        assert "test" in result

    def test_short_words_filtered(self) -> None:
        result = _significant_words("a b c abc xy")
        assert "abc" in result
        assert "xy" not in result

    def test_empty_string(self) -> None:
        assert _significant_words("") == set()

    def test_case_insensitive(self) -> None:
        result = _significant_words("Python PYTHON python")
        assert result == {"python"}


class TestExtractArtifactRefs:
    """Tests for artifact reference extraction."""

    def test_extracts_quoted_strings(self) -> None:
        refs = _extract_artifact_refs('The output file is "report.csv" and "data.json"')
        assert "report.csv" in refs
        assert "data.json" in refs

    def test_extracts_file_paths(self) -> None:
        refs = _extract_artifact_refs("Write to output.json and process input.csv")
        assert "output.json" in refs
        assert "input.csv" in refs

    def test_no_refs_in_plain_text(self) -> None:
        refs = _extract_artifact_refs("Analyze the data and produce a summary")
        assert refs == []

    def test_empty_string(self) -> None:
        assert _extract_artifact_refs("") == []


class TestDetectRelationships:
    """Tests for relationship detection between goals."""

    def test_detects_informs_via_shared_keywords(self) -> None:
        completed = Goal(id="g1", description="Analyze sales data and build quarterly report")
        pending = Goal(id="g2", description="Build sales report for management")
        all_goals = [completed, pending]

        relationships = detect_relationships(completed, all_goals)
        informs = [r for r in relationships if r.rel_type == "informs" and r.from_goal == "g1" and r.to_goal == "g2"]
        assert len(informs) > 0
        assert informs[0].confidence >= _FLAG_FOR_REVIEW_CONFIDENCE

    def test_detects_depends_on_via_artifact_ref(self) -> None:
        completed = Goal(id="g1", description="Generate the report.csv file")
        pending = Goal(id="g2", description="Email the report.csv to stakeholders")
        all_goals = [completed, pending]

        relationships = detect_relationships(completed, all_goals)
        depends = [r for r in relationships if r.rel_type == "depends_on"]
        assert len(depends) > 0
        assert depends[0].confidence >= _AUTO_APPLY_CONFIDENCE

    def test_no_relationship_for_unrelated_goals(self) -> None:
        completed = Goal(id="g1", description="Configure the CI pipeline")
        pending = Goal(id="g2", description="Write the marketing copy")
        all_goals = [completed, pending]

        relationships = detect_relationships(completed, all_goals)
        assert len(relationships) == 0

    def test_skips_completed_goals(self) -> None:
        completed = Goal(id="g1", description="Analyze sales data and build report")
        also_completed = Goal(id="g2", description="Sales report and data analysis", status="completed")
        all_goals = [completed, also_completed]

        relationships = detect_relationships(completed, all_goals)
        assert len(relationships) == 0

    def test_skips_self(self) -> None:
        completed = Goal(id="g1", description="Test goal")
        all_goals = [completed]

        relationships = detect_relationships(completed, all_goals)
        assert len(relationships) == 0

    def test_detects_informs_skips_failed_goals(self) -> None:
        completed = Goal(id="g1", description="Analyze sales data and build report")
        failed = Goal(id="g2", description="Sales report and data analysis", status="failed")
        all_goals = [completed, failed]

        relationships = detect_relationships(completed, all_goals)
        assert len(relationships) == 0


class TestAutoApplyRelationships:
    """Tests for automatic relationship application."""

    def test_auto_applies_high_confidence(self) -> None:
        rel = Relationship(
            from_goal="g1",
            to_goal="g2",
            rel_type="informs",
            confidence=0.9,
            reason="Test",
        )
        goals = [
            Goal(id="g1", description="Source"),
            Goal(id="g2", description="Target"),
        ]
        applied, flagged = auto_apply_relationships([rel], goals)
        assert len(applied) == 1
        assert len(flagged) == 0
        assert "g1" in getattr(goals[1], "informs", [])

    def test_flags_medium_confidence(self) -> None:
        rel = Relationship(
            from_goal="g1",
            to_goal="g2",
            rel_type="informs",
            confidence=0.6,
            reason="Test",
        )
        goals = [
            Goal(id="g1", description="Source"),
            Goal(id="g2", description="Target"),
        ]
        applied, flagged = auto_apply_relationships([rel], goals)
        assert len(applied) == 0
        assert len(flagged) == 1

    def test_ignores_low_confidence(self) -> None:
        rel = Relationship(
            from_goal="g1",
            to_goal="g2",
            rel_type="informs",
            confidence=0.3,
            reason="Test",
        )
        goals = [
            Goal(id="g1", description="Source"),
            Goal(id="g2", description="Target"),
        ]
        applied, flagged = auto_apply_relationships([rel], goals)
        assert len(applied) == 0
        assert len(flagged) == 0

    def test_handles_missing_target_goal(self) -> None:
        rel = Relationship(
            from_goal="g1",
            to_goal="missing",
            rel_type="informs",
            confidence=0.9,
            reason="Test",
        )
        goals = [Goal(id="g1", description="Source")]
        applied, flagged = auto_apply_relationships([rel], goals)
        assert len(applied) == 0
        assert len(flagged) == 0

    def test_does_not_duplicate_existing_relationship(self) -> None:
        goals = [
            Goal(id="g1", description="Source"),
            Goal(id="g2", description="Target", informs=["g1"]),
        ]
        rel = Relationship(
            from_goal="g1",
            to_goal="g2",
            rel_type="informs",
            confidence=0.9,
            reason="Test",
        )
        applied, flagged = auto_apply_relationships([rel], goals)
        assert len(applied) == 0
