"""Tests for failure intent classifier (IG-433)."""

from soothe.sloop.utils.failure_intent_classifier import (
    classify_failure_intent_keyword,
)


class TestFailureIntentClassifier:
    def test_missing_prerequisite_keywords(self) -> None:
        intent = classify_failure_intent_keyword("library not found: libfoo")
        assert intent.category == "missing_prerequisite"
        assert intent.suggested_action == "create_prerequisite"

    def test_permission_denied(self) -> None:
        intent = classify_failure_intent_keyword("Error: permission denied")
        assert intent.category == "permission_denied"
        assert intent.suggested_action == "escalate"

    def test_unknown_failure(self) -> None:
        intent = classify_failure_intent_keyword("something unexpected happened")
        assert intent.category == "unknown"
